"""Salary database models for DOL PERM and LCA disclosure data"""

from django.db import models

from .enums.visa_program import CaseStatus, VisaProgram, WageUnit

# Import IngestVersion to ensure it's registered in Django's app registry
# This is needed because Django's system check runs before AppConfig.ready()
from .ingest.ingest_version import IngestVersion  # noqa: F401

# Import JobTitle models to ensure they're registered for ForeignKey reference
# This is needed because Django's system check runs before AppConfig.ready()
from .job_title import JobTitle, JobTitleCluster  # noqa: F401


class EmployerCluster(models.Model):
    """
    Canonical employer cluster - groups related Employer records

    Represents a single company across all name variations and locations.
    """

    canonical_name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Canonical employer name (e.g., 'Google LLC')",
    )

    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        null=True,  # Temporary: allow null during migration
        blank=True,
        help_text="URL-safe slug for employer (e.g., 'google-llc')",
    )

    # Aggregated statistics across all employers in cluster
    total_lca_count = models.IntegerField(
        default=0,
        help_text="Total H-1B LCA applications across all employers in cluster",
    )

    total_perm_count = models.IntegerField(
        default=0, help_text="Total PERM applications across all employers in cluster"
    )

    avg_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average salary across all employers in cluster",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "salary_employer_cluster"
        indexes = [
            models.Index(fields=["canonical_name"]),
            models.Index(fields=["slug"]),
        ]

    def __str__(self):
        return f"{self.canonical_name} (Cluster {self.id})"

    def generate_slug(self):
        """Generate URL-safe slug from canonical_name"""
        if not self.canonical_name:
            return ""

        from django.utils.text import slugify

        # Use Django's slugify to handle basic conversion
        base_slug = slugify(self.canonical_name)

        # Ensure uniqueness by checking database
        slug = base_slug
        counter = 1

        # Check if this slug already exists (excluding current instance)
        while EmployerCluster.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        return slug

    def save(self, *args, **kwargs):
        """Auto-generate slug on save if not present"""
        if not self.slug and self.canonical_name:
            self.slug = self.generate_slug()
        super().save(*args, **kwargs)


class Employer(models.Model):
    """
    Employer entity - normalized from DOL disclosure data

    Handles employer name variations by storing both original
    and normalized names for matching.
    """

    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Employer name (original from DOL data)",
    )

    name_normalized = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Normalized name for matching (lowercase, cleaned)",
    )

    city = models.CharField(max_length=100, blank=True, help_text="Employer city")

    state = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        help_text="Employer state (2-letter code)",
    )

    # Link to canonical cluster
    canonical_cluster = models.ForeignKey(
        "EmployerCluster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employers",
        help_text="Canonical employer cluster this employer belongs to",
    )

    # Aggregated statistics (updated by import script)
    total_lca_count = models.IntegerField(
        default=0, help_text="Total H-1B LCA applications"
    )

    total_perm_count = models.IntegerField(
        default=0, help_text="Total PERM applications"
    )

    avg_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average salary across all records",
    )

    class Meta:
        db_table = "salary_employer"
        indexes = [
            models.Index(fields=["name_normalized"]),
            models.Index(fields=["state"]),
            models.Index(fields=["canonical_cluster"]),
        ]
        # Allow multiple entries for same employer name (different locations)
        unique_together = ["name_normalized", "city", "state"]

    def __str__(self):
        location = f"{self.city}, {self.state}" if self.city else self.state
        return f"{self.name} ({location})" if location else self.name

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize employer name for matching"""
        if not name:
            return ""
        import re

        # Import generic words from shared module (canonical definition)
        from lib.business.salary.generic_words import (
            DISTINGUISHING_GENERIC_WORDS,
            GENERIC_WORDS,
        )

        # Lowercase, strip
        normalized = name.lower().strip()

        # Handle abbreviations: & -> and (do this early, before punctuation removal)
        # Convert "&" to "and" with proper spacing - handle both "&" and " & " variations
        normalized = re.sub(r"\s*&\s*", " and ", normalized)

        # Detect double spaces that might represent missing "&" and convert to "and"
        # This fixes bucket mismatches like "APPLIED TESTESTING  GEOSCIENCES" vs "APPLIED TESTESTING & GEOSCIENCES"
        # Pattern: word double-space word - likely missing "&" (e.g., "TESTESTING  GEOSCIENCES" -> "TESTESTING and GEOSCIENCES")
        # RECALL FIX: Convert all double spaces to 'and' to improve recall (handles cases like double-space vs ampersand)
        normalized = re.sub(r"\b(\w+)\s{2,}(\w+)\b", r"\1 and \2", normalized)

        # Normalize multiple spaces to single space (after "&" and double-space conversion)
        normalized = re.sub(r"\s+", " ", normalized)

        # Normalize "and" spacing to single space (in case conversion created extra spaces)
        normalized = re.sub(r"\s+and\s+", " and ", normalized)

        # Remove standalone numbers (e.g., "Optim Dental 1" -> "Optim Dental")
        # This handles cases where numbers are added to distinguish locations/entities
        # Pattern: word space number space word (or end of string)
        normalized = re.sub(
            r"\s+\d+\s+", " ", normalized
        )  # Remove numbers with spaces on both sides
        normalized = re.sub(r"\s+\d+$", "", normalized)  # Remove trailing numbers
        normalized = re.sub(r"^\d+\s+", "", normalized)  # Remove leading numbers

        # Handle hyphens: remove entirely for compound words (e.g., "E-KO" -> "eko")
        # This is the original behavior that worked well for most cases
        # Edge cases like "Mercedes-Benz" vs "Mercedes Benz" will be handled by similarity matching
        normalized = normalized.replace("-", "")

        # Remove common corporate suffixes FIRST (before punctuation removal)
        # This handles cases like "Google, Inc." where comma/period are part of suffix
        # Note: These are also in GENERIC_WORDS, but removing as suffixes first is more
        # precise for formatted suffixes (handles punctuation variations).
        # GENERIC_WORDS will catch any remaining instances as standalone words.
        for suffix in [
            ", inc.",
            ", inc",
            " inc.",
            " inc",
            ", llc",
            " llc",
            ", corp.",
            ", corp",
            " corp.",
            " corp",
            ", ltd.",
            ", ltd",
            " ltd.",
            " ltd",
            ", l.p.",
            " l.p.",
            ", co.",
            ", co",
            " co.",
            " co",
            ", incorporated",
            " incorporated",
        ]:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]

        # Remove punctuation (keep spaces) - but handle periods in abbreviations
        # For abbreviations like "G.B." or "C.P.A.", periods should be removed entirely (not become spaces)
        # Pattern: single letter, period, single letter (e.g., "G.B." -> "GB")
        normalized = re.sub(r"\b([a-z])\.([a-z])\b", r"\1\2", normalized)
        # Pattern: single letter, period, space, single letter (e.g., "G. B." -> "GB")
        normalized = re.sub(r"\b([a-z])\.\s+([a-z])\b", r"\1\2", normalized)
        # For other periods (end of sentences, etc.), replace with space
        normalized = normalized.replace(".", " ")
        # Remove remaining punctuation including apostrophes (but keep alphanumeric and spaces)
        # Note: hyphens already removed above, so this won't affect them
        # Apostrophes are removed here to ensure consistent handling
        normalized = re.sub(r"[^\w\s]", " ", normalized)

        # Normalize multiple spaces to single space (do this after all punctuation removal)
        normalized = re.sub(r"\s+", " ", normalized)

        # Remove generic words that don't help distinguish between companies
        # Strategy: Only remove generic words if there are other distinguishing words.
        # If removing generic words would leave too few words, keep distinguishing generic words
        # to preserve distinctions (e.g., "LOGIC SOLUTIONS" vs "LOGIC SERVICES" should remain distinct).
        # IMPORTANT: Also keep certain critical generic words when there's only 1 non-generic word
        # to prevent false matches like "GRAHAM CAPITAL" vs "GRAHAM HOLDINGS"
        words = normalized.split()
        non_generic_words = [w for w in words if w not in GENERIC_WORDS]
        distinguishing_generic = [w for w in words if w in DISTINGUISHING_GENERIC_WORDS]

        # Critical generic words that should be kept when there's only 1 non-generic word
        # These help distinguish between different companies with the same base name
        # Includes: business type words (capital, holdings, etc.) and geographic indicators (usa, us)
        critical_generic_words = {
            "capital",
            "holdings",
            "technology",
            "tech",
            "consulting",
            "consultants",
            "partners",
            "associates",
            "management",
            "group",
            "groups",
            "usa",
            "us",  # Geographic indicators can distinguish entities (e.g., "Roca USA" vs "Roca")
        }
        critical_generic = [w for w in words if w in critical_generic_words]

        # If we have at least 2 non-generic words, remove all generic words
        # If we have exactly 1 non-generic word, keep distinguishing + critical generic words
        # This preserves distinctions like "GRAHAM CAPITAL" vs "GRAHAM HOLDINGS"
        # If we have 0 non-generic words (all generic), keep all words
        if len(non_generic_words) >= 2:
            # Multiple distinguishing words - remove all generic words
            filtered_words = non_generic_words
        elif len(non_generic_words) == 1:
            # Single distinguishing word - keep it plus distinguishing + critical generic words
            # This prevents false matches while still allowing legitimate matches
            filtered_words = (
                non_generic_words + distinguishing_generic + critical_generic
            )
        else:
            # All words are generic - keep them all (rare case, e.g., "The Company")
            filtered_words = words

        # Apply plural-to-singular normalization to non-generic words
        # This handles variations like "Solutions" vs "Solution", "Plans" vs "Plan"
        def plural_to_singular(word: str) -> str:
            """Convert plural to singular form (simple rules)"""
            if len(word) <= 2:
                return word  # Too short to be plural
            # Simple rule: if ends with 's' and not already singular-looking, remove 's'
            # Exceptions: words ending in 'ss' (keep), 'us' (keep), 'is' (keep)
            if word.endswith("ss") or word.endswith("us") or word.endswith("is"):
                return word
            if word.endswith("s"):
                return word[:-1]
            return word

        # Apply plural-to-singular to filtered words (only non-generic words)
        # Don't change generic words (e.g., "companies" should stay as is if "company" is generic)
        normalized_words = []
        for word in filtered_words:
            if word not in GENERIC_WORDS:
                # Apply plural-to-singular to non-generic words
                normalized_words.append(plural_to_singular(word))
            else:
                # Keep generic words as-is
                normalized_words.append(word)

        normalized = " ".join(normalized_words)

        return normalized.strip()


class SalaryRecord(models.Model):
    """
    Individual salary record from DOL PERM or LCA disclosure data

    Stores wage information, job details, and case metadata.
    """

    # Case identification
    case_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="DOL case number (unique identifier)",
    )

    visa_program = models.IntegerField(
        choices=VisaProgram.choices,
        db_index=True,
        help_text="Visa program type (H-1B, PERM, etc.)",
    )

    case_status = models.IntegerField(
        choices=CaseStatus.choices,
        blank=True,
        null=True,
        help_text="Case status (Certified, Denied, etc.)",
    )

    # Employer info (denormalized for query performance)
    employer = models.ForeignKey(
        Employer,
        on_delete=models.CASCADE,
        related_name="salary_records",
        null=True,
        blank=True,
    )

    employer_name = models.CharField(
        max_length=255, db_index=True, help_text="Employer name from DOL data"
    )

    # Job details
    job_title_entity = models.ForeignKey(
        "JobTitle",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_records",
        help_text="Link to normalized job title entity",
    )

    job_title = models.CharField(max_length=255, db_index=True, help_text="Job title")

    soc_code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Standard Occupational Classification code",
    )

    soc_title = models.CharField(
        max_length=255, blank=True, help_text="SOC occupation title"
    )

    # Work location
    worksite_city = models.CharField(
        max_length=100, blank=True, help_text="Work location city"
    )

    worksite_state = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        help_text="Work location state (2-letter code)",
    )

    # Wage information
    wage_from = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage offer (from/minimum)",
    )

    wage_to = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage offer (to/maximum, if range)",
    )

    wage_unit = models.CharField(
        max_length=20,
        choices=WageUnit.choices,
        default=WageUnit.YEAR,
        help_text="Unit of pay (year, month, hour, etc.)",
    )

    wage_annual = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
        help_text="Annualized wage (calculated)",
    )

    # Prevailing wage (DOL benchmark wage for comparison)
    # DOL determines prevailing wage as the average paid to similarly employed workers
    # in the geographic area. Used to ensure employers aren't underpaying foreign workers.
    prevailing_wage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="DOL's benchmark wage for similarly employed workers in the area",
    )

    prevailing_wage_unit = models.CharField(
        max_length=20,
        choices=WageUnit.choices,
        blank=True,
        null=True,  # Allow NULL when prevailing_wage is not provided
        help_text="Unit for prevailing wage (year, hour, etc.)",
    )

    # Dates
    case_submitted = models.DateField(
        null=True, blank=True, db_index=True, help_text="Date case was submitted"
    )

    decision_date = models.DateField(
        null=True, blank=True, db_index=True, help_text="Date of decision"
    )

    employment_start = models.DateField(
        null=True, blank=True, help_text="Employment start date"
    )

    employment_end = models.DateField(
        null=True, blank=True, help_text="Employment end date"
    )

    # Fiscal year for easy filtering
    fiscal_year = models.IntegerField(
        db_index=True, help_text="Fiscal year of the record"
    )

    # Data source tracking
    source_file = models.CharField(
        max_length=255, blank=True, db_index=True, help_text="Source CSV file name"
    )

    # Performance optimization: boolean flag for worksite records (indexed)
    # This avoids expensive LIKE queries on source_file
    is_worksite = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this record is from a worksite file (for efficient filtering)",
    )

    # Ingest version tracking (for rollback)
    # String reference - Django resolves after all models loaded
    # No circular dependency: IngestVersion doesn't import from salary
    # null=True allows None without explicit default (Django's default behavior)
    ingest_version = models.ForeignKey(
        "models.IngestVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="salary_records",
        help_text="Ingest version this record belongs to (for rollback)",
    )

    # Source file date tracking (for duplicate resolution)
    source_file_date = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Date when source file was created/modified (for duplicate resolution)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "salary_record"
        ordering = ["-decision_date", "-case_submitted"]
        indexes = [
            # Primary search indexes
            models.Index(fields=["employer_name", "job_title"]),
            models.Index(fields=["job_title", "worksite_state"]),
            models.Index(fields=["soc_code", "worksite_state"]),
            # Filter indexes
            models.Index(fields=["visa_program", "fiscal_year"]),
            models.Index(fields=["worksite_state", "fiscal_year"]),
            models.Index(
                fields=["worksite_state", "employer"], name="sr_worksite_employer"
            ),
            models.Index(fields=["wage_annual", "visa_program"]),
            # Date-based indexes
            models.Index(fields=["decision_date"]),
            models.Index(fields=["fiscal_year", "decision_date"]),
            # Performance: Composite index for employer filtering with worksite exclusion
            models.Index(fields=["employer", "is_worksite"]),
            # Employer-profile percentile/histogram: (employer, is_worksite, fiscal_year) + INCLUDE(wage_annual)
            # so SELECT wage_annual WHERE employer_id IN (...) AND is_worksite=false AND fiscal_year>=?
            # can use index-only scan and avoid 30k+ heap fetches (scan was ~6s, Python 0s).
            # name= required and must be ≤30 chars (Django E034; auto-generated name would exceed limit).
            models.Index(
                fields=["employer", "is_worksite", "fiscal_year"],
                include=["wage_annual"],
                name="sr_emp_wk_fy_inc_wage",
            ),
            # Clustering: Index for job title entity lookups (prevents slow COUNTs during clustering)
            models.Index(fields=["job_title_entity"]),
        ]

    def __str__(self):
        wage_str = f"${self.wage_annual:,.0f}" if self.wage_annual else "N/A"
        return f"{self.job_title} @ {self.employer_name} ({wage_str})"

    def save(self, *args, **kwargs):
        """Calculate annualized wage before saving"""
        if self.wage_from and self.wage_unit:
            self.wage_annual = self.calculate_annual_wage()
        super().save(*args, **kwargs)

    def calculate_annual_wage(self) -> float | None:
        """Convert wage to annual based on wage unit"""
        if not self.wage_from:
            return None

        wage = float(self.wage_from)

        match self.wage_unit:
            case WageUnit.YEAR:
                return wage
            case WageUnit.MONTH:
                return wage * 12
            case WageUnit.BI_WEEKLY:
                return wage * 26
            case WageUnit.WEEK:
                return wage * 52
            case WageUnit.HOUR:
                return wage * 2080  # Standard full-time hours
            case _:
                return wage  # Assume annual if unknown

    def to_dict(self) -> dict:
        """
        Serialize model instance to dictionary for JSON/YAML compatibility.

        Converts:
        - Decimal fields to float
        - Date fields to ISO format strings
        - ForeignKey fields to ID (or None)
        - Enum objects (IntegerChoices, TextChoices) to their values
        - Handles None values explicitly

        Returns:
            Dictionary representation suitable for JSON/YAML serialization
        """
        from datetime import date, datetime
        from decimal import Decimal

        result = {}

        # Get all field names
        for field in self._meta.get_fields():
            field_name = field.name

            # Skip reverse relations and many-to-many
            if field.many_to_many or (field.one_to_many and not field.concrete):
                continue

            # Get field value
            value = getattr(self, field_name, None)

            # Handle ForeignKey - use ID
            if field.many_to_one and value is not None:
                result[field_name + "_id"] = value.pk
                continue

            # Skip ForeignKey objects (we use _id above)
            if field.many_to_one and value is None:
                result[field_name + "_id"] = None
                continue

            # Convert Decimal to float
            if isinstance(value, Decimal):
                result[field_name] = float(value)
            # Convert date/datetime to ISO string
            elif isinstance(value, (date, datetime)):
                result[field_name] = value.isoformat() if value else None
            # Convert enum objects to their values (IntegerChoices or TextChoices)
            elif hasattr(value, "value"):  # IntegerChoices enum object
                result[field_name] = value.value
            # Handle None explicitly
            elif value is None:
                result[field_name] = None
            # Everything else as-is
            else:
                result[field_name] = value

        return result


class WorksiteRecord(models.Model):
    """
    Worksite location record from DOL Worksites disclosure files.

    These files focus on worksite locations rather than employers,
    so they have a different structure and use case.

    IMPORTANT:
    - Does NOT have employer_name or employer fields (by design)
    - REQUIRES salary data (wage_from, wage_unit, wage_annual) - NOT optional
    - Primary focus is on worksite location (city, state, zip)
    - Used for location-based analysis, not employer-based analysis
    """

    # Case identification (same as SalaryRecord)
    case_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="DOL case number (unique identifier)",
    )

    visa_program = models.IntegerField(
        choices=VisaProgram.choices,
        db_index=True,
        help_text="Visa program type (H-1B, PERM, etc.)",
    )

    case_status = models.IntegerField(
        choices=CaseStatus.choices,
        blank=True,
        null=True,
        help_text="Case status (Certified, Denied, etc.)",
    )

    # Worksite information (PRIMARY focus for these files)
    worksite_city = models.CharField(
        max_length=100, blank=True, db_index=True, help_text="Worksite city"
    )

    worksite_state = models.CharField(
        max_length=2,
        blank=True,
        db_index=True,
        help_text="Worksite state (2-letter code)",
    )

    worksite_zip = models.CharField(
        max_length=10, blank=True, help_text="Worksite ZIP code (if available)"
    )

    # Job details
    job_title = models.CharField(max_length=255, db_index=True, help_text="Job title")

    soc_code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Standard Occupational Classification code",
    )

    soc_title = models.CharField(
        max_length=255, blank=True, help_text="SOC occupation title"
    )

    # Wage information
    wage_from = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage rate (from)",
    )

    wage_to = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Wage rate (to)",
    )

    wage_unit = models.CharField(
        max_length=20,
        choices=WageUnit.choices,
        blank=True,
        help_text="Wage unit (hour, year, etc.)",
    )

    wage_annual = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        db_index=True,
        help_text="Annual wage (calculated)",
    )

    prevailing_wage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Prevailing wage for the position",
    )

    prevailing_wage_unit = models.CharField(
        max_length=20,
        choices=WageUnit.choices,
        blank=True,
        help_text="Prevailing wage unit",
    )

    # Dates
    case_submitted = models.DateField(
        null=True, blank=True, db_index=True, help_text="Date case was submitted"
    )

    decision_date = models.DateField(
        null=True, blank=True, db_index=True, help_text="Date of decision"
    )

    employment_start = models.DateField(
        null=True, blank=True, help_text="Employment start date"
    )

    employment_end = models.DateField(
        null=True, blank=True, help_text="Employment end date"
    )

    # Metadata
    fiscal_year = models.IntegerField(
        db_index=True, help_text="Fiscal year of the record"
    )

    source_file = models.CharField(
        max_length=255, blank=True, help_text="Source file name"
    )

    # Ingest version tracking (for rollback)
    ingest_version = models.ForeignKey(
        "models.IngestVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worksite_records",
        help_text="Ingest version this record belongs to (for rollback)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "worksite_record"
        ordering = ["-decision_date", "-case_submitted"]
        indexes = [
            # Location-based indexes (primary focus)
            models.Index(fields=["worksite_state", "fiscal_year"]),
            models.Index(fields=["worksite_city", "worksite_state"]),
            models.Index(fields=["job_title", "worksite_state"]),
            models.Index(fields=["soc_code", "worksite_state"]),
            # Filter indexes
            models.Index(fields=["visa_program", "fiscal_year"]),
            models.Index(fields=["wage_annual"]),
            # Date-based indexes
            models.Index(fields=["decision_date"]),
            models.Index(fields=["fiscal_year", "decision_date"]),
        ]

    def __str__(self):
        location = (
            f"{self.worksite_city}, {self.worksite_state}"
            if self.worksite_city
            else self.worksite_state
        )
        return f"{self.case_number} - {location} - {self.job_title}"

    def save(self, *args, **kwargs):
        """Calculate annualized wage before saving"""
        if self.wage_from and self.wage_unit:
            self.wage_annual = self.calculate_annual_wage()
        super().save(*args, **kwargs)

    def calculate_annual_wage(self) -> float | None:
        """Convert wage to annual based on wage unit"""
        if not self.wage_from:
            return None

        wage = float(self.wage_from)

        match self.wage_unit:
            case WageUnit.YEAR:
                return wage
            case WageUnit.MONTH:
                return wage * 12
            case WageUnit.BI_WEEKLY:
                return wage * 26
            case WageUnit.WEEK:
                return wage * 52
            case WageUnit.HOUR:
                return wage * 2080  # Standard full-time hours
            case _:
                return wage  # Assume annual if unknown

    def to_dict(self) -> dict:
        """
        Serialize model instance to dictionary for JSON/YAML compatibility.

        Converts:
        - Decimal fields to float
        - Date fields to ISO format strings
        - ForeignKey fields to ID (or None)
        - Enum objects (IntegerChoices, TextChoices) to their values
        - Handles None values explicitly

        Returns:
            Dictionary representation suitable for JSON/YAML serialization
        """
        from datetime import date, datetime
        from decimal import Decimal

        result = {}

        # Get all field names
        for field in self._meta.get_fields():
            field_name = field.name

            # Skip reverse relations and many-to-many
            if field.many_to_many or (field.one_to_many and not field.concrete):
                continue

            # Get field value
            value = getattr(self, field_name, None)

            # Handle ForeignKey - use ID
            if field.many_to_one and value is not None:
                result[field_name + "_id"] = value.pk
                continue

            # Skip ForeignKey objects (we use _id above)
            if field.many_to_one and value is None:
                result[field_name + "_id"] = None
                continue

            # Convert Decimal to float
            if isinstance(value, Decimal):
                result[field_name] = float(value)
            # Convert date/datetime to ISO string
            elif isinstance(value, (date, datetime)):
                result[field_name] = value.isoformat() if value else None
            # Convert enum objects to their values (IntegerChoices or TextChoices)
            elif hasattr(value, "value"):  # IntegerChoices enum object
                result[field_name] = value.value
            # Handle None explicitly
            elif value is None:
                result[field_name] = None
            # Everything else as-is
            else:
                result[field_name] = value

        return result


class ClusteringCheckpoint(models.Model):
    """
    Checkpoint storage for clustering script resumption.

    Stores processed items in database to avoid loading entire checkpoint into memory.
    Uses unique constraint to prevent duplicates.
    """

    phase = models.CharField(
        max_length=20,
        choices=[
            ("phase1", "Phase 1 (same normalized names)"),
            ("phase2", "Phase 2 (cross-normalized matches)"),
        ],
        db_index=True,
        help_text="Which phase this checkpoint item belongs to",
    )
    item_key = models.CharField(
        max_length=500,
        db_index=True,
        help_text="Unique key for the processed item (normalized name or pair key)",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "salary_clustering_checkpoint"
        unique_together = ["phase", "item_key"]
        indexes = [
            models.Index(fields=["phase", "item_key"]),
        ]

    def __str__(self):
        return f"{self.phase}: {self.item_key[:50]}"


class EmployerClusteringReview(models.Model):
    """
    Review queue for ambiguous employer clustering matches

    Stores potential matches that need human/LLM review.
    """

    employer1 = models.ForeignKey(
        Employer, on_delete=models.CASCADE, related_name="review_as_employer1"
    )
    employer2 = models.ForeignKey(
        Employer, on_delete=models.CASCADE, related_name="review_as_employer2"
    )

    similarity_score = models.FloatField(
        help_text="Similarity score from fuzzy matching (0-1)"
    )

    match_reason = models.TextField(
        blank=True,
        help_text="Why these employers might be the same (rule-based or LLM analysis)",
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ("pending", "Pending Review"),
            ("approved", "Approved - Same Employer"),
            ("rejected", "Rejected - Different Employers"),
        ],
        default="pending",
        db_index=True,
    )

    reviewed_by = models.CharField(
        max_length=50, blank=True, help_text="'human' or 'llm' or username"
    )

    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "salary_employer_clustering_review"
        unique_together = ["employer1", "employer2"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["similarity_score"]),
        ]

    def __str__(self):
        return f"Review: {self.employer1.name} vs {self.employer2.name} ({self.status})"
