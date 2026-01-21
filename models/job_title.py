"""Job title models for normalization and clustering"""

from django.db import models
import re


class JobTitleCluster(models.Model):
    """
    Canonical job title cluster - groups related JobTitle records.
    
    Represents a single job title type across variations and seniority levels.
    """
    canonical_title = models.CharField(
        max_length=500,
        db_index=True,
        help_text="Canonical job title (e.g., 'Software Engineer')"
    )
    
    slug = models.SlugField(
        max_length=255,
        unique=True,
        db_index=True,
        null=True,  # Allow null during migration
        blank=True,
        help_text="URL-safe slug for job title (e.g., 'software-engineer')"
    )
    
    # Aggregated statistics
    total_filings = models.IntegerField(
        default=0,
        help_text="Total filings across all job titles in cluster"
    )
    
    avg_salary = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Average salary across all job titles in cluster"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'salary_job_title_cluster'
        indexes = [
            models.Index(fields=['canonical_title']),
            models.Index(fields=['slug']),
        ]
    
    def __str__(self):
        return self.canonical_title
    
    def generate_slug(self):
        """Generate URL-safe slug from canonical_title"""
        if not self.canonical_title:
            return ""
        
        from django.utils.text import slugify
        
        # Use Django's slugify to handle basic conversion
        base_slug = slugify(self.canonical_title)
        
        # Ensure uniqueness by checking database
        slug = base_slug
        counter = 1
        
        # Check if this slug already exists (excluding current instance)
        while JobTitleCluster.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        
        return slug
    
    def save(self, *args, **kwargs):
        """Auto-generate slug on save if not present"""
        if not self.slug and self.canonical_title:
            self.slug = self.generate_slug()
        super().save(*args, **kwargs)


class JobTitle(models.Model):
    """
    Normalized job title entity.
    
    Groups salary records with same job title and seniority level.
    """
    
    # Original and normalized title
    title = models.CharField(
        max_length=500,
        help_text="Original job title from filing"
    )
    
    title_normalized = models.CharField(
        max_length=500,
        db_index=True,
        help_text="Normalized title for matching (no seniority indicators)"
    )
    
    # Experience/seniority level extracted from title
    experience_level = models.CharField(
        max_length=20,
        default='',
        blank=True,
        choices=[
            ('', 'Not Specified'),
            ('entry', 'Entry Level'),
            ('junior', 'Junior'),
            ('mid', 'Mid Level'),
            ('senior', 'Senior'),
            ('staff', 'Staff'),
            ('principal', 'Principal'),
            ('lead', 'Lead'),
            ('manager', 'Manager'),
            ('director', 'Director'),
        ],
        db_index=True,
        help_text="Extracted experience/seniority level"
    )
    
    # Link to canonical cluster
    canonical_cluster = models.ForeignKey(
        JobTitleCluster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='job_titles',
        help_text="Canonical job title cluster"
    )
    
    # Aggregated statistics
    total_filings = models.IntegerField(default=0)
    avg_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'salary_job_title'
        unique_together = ['title_normalized', 'experience_level']
        indexes = [
            models.Index(fields=['title_normalized']),
            models.Index(fields=['experience_level']),
        ]
    
    def __str__(self):
        if self.experience_level:
            return f"{self.format_experience_level(self.experience_level)} {self.title}"
        return self.title

    @property
    def experience_level_display(self) -> str:
        """Human-friendly display value for experience level."""
        return self.format_experience_level(self.experience_level)

    @staticmethod
    def format_experience_level(level: str | None, unspecified_label: str = "Unspecified") -> str:
        """Format an experience level for display (handles roman numerals)."""
        if not level:
            return unspecified_label

        normalized = level.strip().lower()
        roman_map = {
            'i': 'I',
            'ii': 'II',
            'iii': 'III',
            'iv': 'IV',
            'v': 'V',
        }
        if normalized in roman_map:
            return roman_map[normalized]

        return normalized.replace('_', ' ').title()
    
    # Clustering engine compatibility properties
    @property
    def name(self) -> str:
        """Alias for title (clustering engine compatibility)"""
        return self.title
    
    @property
    def name_normalized(self) -> str:
        """Alias for title_normalized (clustering engine compatibility)"""
        return self.title_normalized
    
    @staticmethod
    def normalize_title(title: str) -> str:
        """
        Normalize job title for matching.
        
        Removes seniority indicators, generic words, and standardizes format.
        Similar pattern to Employer.normalize_name but for job titles.
        """
        if not title:
            return ""
        
        normalized = title.lower().strip()
        
        # Seniority patterns (to be removed)
        # Note: Roman numerals (I, II, III, IV, V) are NOT removed as they mean different things at different companies
        level_marker_pattern = r'\b(i{1,3}|iv|v|[1-5])\b(?!\w)'
        has_level_marker = bool(re.search(level_marker_pattern, normalized))
        seniority_patterns = [
            r'\bentry[ -]level\b', r'\bentry\b', r'\bjunior\b', r'\bjr\.?\b',
            r'\bsenior\b', r'\bsr\.?\b', r'\blead\b', r'\bleading\b',
            r'\bstaff\b', r'\bprincipal\b',
            r'\bmanager\b', r'\bmgr\.?\b', r'\bmanaging\b',
            r'\bdirector\b', r'\bdir\.?\b',
            # Note: We keep level markers like "II", "III" etc. as they're company-specific
            r'\blevel\s*[i1234v5]\b',  # Remove "Level II", "Level 3" etc.
        ]

        role_word_patterns = {
            r'\blead\b', r'\bleading\b',
            r'\bstaff\b',
            r'\bprincipal\b',
            r'\bmanager\b', r'\bmgr\.?\b', r'\bmanaging\b',
            r'\bdirector\b', r'\bdir\.?\b',
        }

        patterns_to_apply = seniority_patterns
        if has_level_marker:
            patterns_to_apply = [
                pattern for pattern in seniority_patterns
                if pattern not in role_word_patterns
            ]

        has_role_word = any(re.search(pattern, normalized) for pattern in role_word_patterns)

        for pattern in patterns_to_apply:
            normalized = re.sub(pattern, ' ', normalized)

        if has_level_marker and has_role_word:
            normalized = re.sub(level_marker_pattern, ' ', normalized)
        
        # Standard normalization (from employer patterns)
        normalized = re.sub(r'\s*&\s*', ' and ', normalized)
        normalized = re.sub(r'\([^)]*\)', ' ', normalized)  # Remove parentheticals (certifications)
        normalized = re.sub(r'[-_]', ' ', normalized)
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+\d+\s+', ' ', normalized)
        normalized = re.sub(r'\s+\d+$', '', normalized)
        normalized = re.sub(r'^\d+\s+', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        
        # Title standardization
        title_equivalents = {
            'software developer': 'software engineer',
            'software dev': 'software engineer',
            'swe': 'software engineer',
            'programmer': 'software engineer',
            'data analyst': 'data scientist',
            'ml engineer': 'machine learning engineer',
            'registered nurse': 'nurse',
            'rn': 'nurse',
            'physician': 'doctor',
            'md': 'doctor',
        }
        
        for variant, canonical in title_equivalents.items():
            if normalized == variant:
                normalized = canonical
                break
        
        # Deduplicate words while preserving order
        # This handles cases like "software engineer software" or "director executive director"
        words = normalized.split()
        seen = set()
        deduped_words = []
        for word in words:
            if word not in seen:
                seen.add(word)
                deduped_words.append(word)
        normalized = ' '.join(deduped_words)
        
        return normalized
    
    @staticmethod
    def extract_experience_level(title: str) -> str:
        """
        Extract experience/seniority level from job title.
        
        Returns: Experience level code ('junior', 'senior', etc.) or empty string
        """
        if not title:
            return ''
        
        title_lower = title.lower()
        
        # Level markers take precedence over role words
        roman_levels = [
            ('v', r'\bv\b(?!\w)'),
            ('iv', r'\biv\b(?!\w)'),
            ('iii', r'\biii\b(?!\w)'),
            ('ii', r'\bii\b(?!\w)'),
            ('i', r'\bi\b(?!\w)'),
        ]
        for level, pattern in roman_levels:
            if re.search(pattern, title_lower):
                return level

        digit_match = re.search(r'\b([1-5])\b(?!\w)', title_lower)
        if digit_match:
            digit_to_roman = {
                '1': 'i',
                '2': 'ii',
                '3': 'iii',
                '4': 'iv',
                '5': 'v',
            }
            return digit_to_roman[digit_match.group(1)]

        # Seniority patterns (ordered by priority)
        seniority_checks = [
            ('director', [r'\bdirector\b', r'\bdir\.?\b']),
            ('manager', [r'\bmanager\b', r'\bmgr\.?\b', r'\bmanaging\b']),
            ('principal', [r'\bprincipal\b']),
            ('lead', [r'\blead\b', r'\bleading\b']),
            ('staff', [r'\bstaff\b']),
            ('senior', [r'\bsenior\b', r'\bsr\.?\b']),
            ('junior', [r'\bjunior\b', r'\bjr\.?\b']),
            ('entry', [r'\bentry[ -]level\b', r'\bentry\b']),
        ]
        
        for level, patterns in seniority_checks:
            for pattern in patterns:
                if re.search(pattern, title_lower):
                    return level
        
        return ''


class JobTitleClusteringReview(models.Model):
    """Review queue for ambiguous job title matches"""
    
    job_title1 = models.ForeignKey(
        JobTitle,
        on_delete=models.CASCADE,
        related_name='review_pairs_as_first'
    )
    
    job_title2 = models.ForeignKey(
        JobTitle,
        on_delete=models.CASCADE,
        related_name='review_pairs_as_second'
    )
    
    similarity_score = models.FloatField(help_text="Similarity score (0.0-1.0)")
    match_reason = models.TextField(blank=True)
    
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending Review'),
            ('same', 'Same Job Title'),
            ('different', 'Different Job Title'),
            ('skip', 'Skip'),
        ],
        default='pending',
        db_index=True
    )
    
    reviewed_by = models.CharField(max_length=100, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'salary_job_title_clustering_review'
        unique_together = ['job_title1', 'job_title2']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['similarity_score']),
        ]

