"""Enums for ingest pipeline

Performance consideration: Use IntegerChoices for high-volume data (faster, smaller).
Use TextChoices for low-volume metadata (readable, debuggable).

For ingest pipeline:
- DataDomain, SourceType: Low volume (hundreds of sources) → TextChoices OK
- IngestStatus, IngestStage: Low volume (thousands of runs) → IntegerChoices for performance
"""

from django.db import models


class DataDomain(models.TextChoices):
    """
    Data source domain (organization/system)

    Database stores: 'dol' or 'visa_bulletin' (strings)
    Low volume, readability preferred.
    """

    DOL = "dol", "Department of Labor"
    VISA_BULLETIN = "visa_bulletin", "Visa Bulletin"
    USCIS = "uscis", "USCIS"
    DOS = "dos", "Department of State"


class SourceType(models.TextChoices):
    """
    Type of data source within a domain

    Database stores: 'lca', 'perm', 'worksite', or 'bulletin' (strings)
    Low volume, readability preferred.
    """

    LCA = "lca", "LCA (H-1B)"
    PERM = "perm", "PERM (Salary)"
    WORKSITE = "worksite", "Worksite Location Data"
    BULLETIN = "bulletin", "Visa Bulletin"

    # VQS Supply Sources
    I485_INVENTORY = "i485_inventory", "USCIS I-485 Inventory"
    ISSUANCE = "issuance", "DOS Monthly Issuance"
    PERM_DISCLOSURE = "perm_disclosure", "PERM Disclosure (Supply)"


class IngestStatus(models.IntegerChoices):
    """
    Overall status of an ingest run

    Database stores: 0=invalid, 1-5 for valid statuses (integers)
    Used in frequent queries/filters - integers are faster.
    Value 0 is reserved for invalid/unknown (allows safe truthiness checks).
    """

    INVALID = 0, "Invalid/Unknown"
    PENDING = 1, "Pending"
    RUNNING = 2, "Running"
    COMPLETED = 3, "Completed"
    FAILED = 4, "Failed"
    CANCELLED = 5, "Cancelled"


class IngestStage(models.IntegerChoices):
    """
    Current stage within the pipeline

    Database stores: 0=invalid, 1-6 for valid stages (integers)
    Used in frequent queries/filters - integers are faster.
    Value 0 is reserved for invalid/unknown (allows safe truthiness checks).
    """

    INVALID = 0, "Invalid/Unknown"
    PENDING = 1, "Pending"
    DOWNLOADING = 2, "Downloading"
    PARSING = 3, "Parsing"
    TRANSFORMING = 4, "Transforming"
    LOADING = 5, "Loading to Database"
    COMPLETED = 6, "Completed"


class FormatVersion(models.TextChoices):
    """
    Format version for parser selection

    Database stores: 'legacy', 'modern', or 'unknown' (strings)
    Low volume (only in DataSource table), readability preferred.
    Used to explicitly select which parser to use.
    """

    LEGACY = "legacy", "Legacy Format (2001-2014)"
    MODERN = "modern", "Modern Format (2015+)"
    UNKNOWN = "unknown", "Unknown Format"
