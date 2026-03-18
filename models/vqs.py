from django.db import models


class PredictedBulletin(models.Model):
    """
    Represents a full set of predictions for a specific future bulletin month.
    This allows us to take a 'snapshot' of what the system predicted at a given time.
    """

    target_bulletin_month = models.DateField(unique=True)  # e.g., 2026-03-01
    prediction_date = models.DateField()  # When this calculation was made
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "models"
        ordering = ["-target_bulletin_month"]

    def __str__(self):
        return f"Prediction for {self.target_bulletin_month} (v{self.prediction_date})"


class PredictedCutoff(models.Model):
    """
    A single cutoff prediction within a PredictedBulletin.
    """

    bulletin = models.ForeignKey(
        PredictedBulletin, related_name="cutoffs", on_delete=models.CASCADE
    )
    visa_class = models.CharField(max_length=10)  # "1st", "2nd", etc.
    country = models.IntegerField()  # Country enum value
    action_type = models.CharField(max_length=20)  # "final_action" or "filing_date"

    predicted_date = models.DateField(null=True, blank=True)
    confidence_low = models.DateField(null=True, blank=True)
    confidence_high = models.DateField(null=True, blank=True)
    explanation_markdown = models.TextField(
        help_text="Why this prediction?", blank=True
    )

    expert_predictions = models.JSONField(
        default=dict, blank=True,
        help_text="Per-expert data: {name: {pred: 'YYYY-MM-DD', weight: 0.XX}}",
    )

    # For historical comparison (populated later when actual is known)
    actual_date = models.DateField(null=True, blank=True)
    accuracy_score = models.FloatField(null=True, blank=True)  # e.g. abs error in days

    class Meta:
        app_label = "models"
        indexes = [
            models.Index(fields=["bulletin", "visa_class", "country", "action_type"]),
        ]
        unique_together = ["bulletin", "visa_class", "country", "action_type"]

    def __str__(self):
        return f"{self.visa_class}/{self.country} ({self.action_type}): {self.predicted_date}"
