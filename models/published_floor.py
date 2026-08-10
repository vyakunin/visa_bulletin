"""PublishedFloor - a lower bound the State Department stated in a bulletin's PROSE.

A visa bulletin carries two kinds of information. The charts give this month's
cutoff per series, and the lettered notes underneath sometimes make a statement
about a **future** month. The July 2026 bulletin, section F:

    "It is likely that in October the final action date will advance to at least
    the final action date announced in the May 2026 Visa Bulletin"

That is a floor on a month whose bulletin does not exist yet. It constrains a
forecast, and nothing in the chart pipeline can carry it: `bulletin_parser` reads
only the four named tables, and no column anywhere holds the prose.

**Why its own model, not a column on VisaCutoffDate.** A cutoff row answers "what
was the value for this series in THIS bulletin". A floor answers "what did this
bulletin say about a LATER period", so the two disagree on every axis that
matters:

* **No row to hang it on.** The floor's subject is the target period (October
  2026), which has no bulletin and therefore no cutoff row. Attaching it to the
  July row would file a claim about October under a record of July.
* **Different writer.** Cutoff rows are ingested and re-ingested idempotently by
  the table parser, which would happily overwrite a hand-entered column on a
  re-run. A floor is entered by a human (or an agent reading for one) and must
  survive re-ingest of its source bulletin.
* **Cardinality.** One bulletin can state floors for several series and several
  target periods, and successive bulletins can restate or revise a floor for the
  same target. A column gives exactly one slot per cutoff row.

Consumed by `lib/business/vqs/october_reset.py`, which clamps the reset
distribution so a published forecast cannot contradict a floor DOS published.
"""

from django.db import models

from .bulletin import Bulletin
from .enums.action_type import ActionType
from .enums.country import Country
from .enums.visa_category import VisaCategory


class PublishedFloorManager(models.Manager):
    """Lookups that keep floors walk-forward safe."""

    def floor_for(
        self,
        visa_class: str,
        country: int,
        action_type: str,
        target_period,
        knowledge_date,
    ):
        """The floor governing one series/target, known at ``knowledge_date``.

        Only floors whose SOURCE bulletin had published by ``knowledge_date`` are
        visible, so a backtest replaying 2020 cannot see a statement made in 2026.
        The most recently published source wins when several bulletins speak to the
        same target period — a later bulletin restating a floor supersedes an
        earlier one.

        Returns a ``PublishedFloor`` or None.
        """
        return (
            self.filter(
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                target_period=target_period,
                source_bulletin__publication_date__lte=knowledge_date,
            )
            .select_related("source_bulletin")
            .order_by("-source_bulletin__publication_date")
            .first()
        )


class PublishedFloor(models.Model):
    """A lower bound on a future cutoff, quoted from a bulletin's notes section.

    Hand-entered per bulletin (see scripts/bulletin/record_published_floor.py):
    the prose is not persisted anywhere, so there is nothing to parse from.
    ``source_quote`` is the verbatim sentence, which is what lets a human audit
    the claim against the bulletin without re-reading travel.state.gov.
    """

    source_bulletin = models.ForeignKey(
        Bulletin,
        on_delete=models.CASCADE,
        related_name="published_floors",
        help_text="The bulletin whose notes section made the statement",
    )

    target_period = models.DateField(
        help_text="First day of the month the floor constrains (e.g. 2026-10-01). "
        "Later than the source bulletin's own month — a floor is about the future."
    )

    visa_category = models.CharField(
        max_length=20,
        choices=VisaCategory.choices,
        help_text="Family-Sponsored or Employment-Based",
    )

    visa_class = models.CharField(
        max_length=100, help_text="Series class as ingested, e.g. '2nd' (matches VisaCutoffDate)"
    )

    action_type = models.CharField(
        max_length=20,
        choices=ActionType.choices,
        help_text="Which chart the floor speaks to: Final Action or Dates for Filing",
    )

    country = models.IntegerField(
        choices=Country.choices, help_text="Country/region for chargeability"
    )

    floor_date = models.DateField(
        help_text="The cutoff will not be EARLIER than this date, per the source statement"
    )

    source_quote = models.TextField(
        help_text="Verbatim sentence(s) from the bulletin that state the floor. "
        "Required — it is the audit trail for a hand-entered claim."
    )

    source_section = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Lettered note the quote came from, e.g. 'F'. Blank if unrecorded.",
    )

    recorded_at = models.DateTimeField(
        auto_now_add=True, help_text="When this floor was entered into the database"
    )

    objects = PublishedFloorManager()

    class Meta:
        db_table = "published_floor"
        ordering = ["-target_period", "visa_class", "country"]
        constraints = [
            # One statement per (source, target, series). Re-recording the same
            # floor updates in place rather than duplicating — the record script
            # relies on this for idempotency.
            models.UniqueConstraint(
                fields=[
                    "source_bulletin",
                    "target_period",
                    "visa_category",
                    "visa_class",
                    "action_type",
                    "country",
                ],
                name="uniq_published_floor_source_target_series",
            )
        ]
        indexes = [
            models.Index(
                fields=["visa_class", "country", "action_type", "target_period"],
                name="pubfloor_series_target_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.visa_class} {Country(self.country).label} {self.action_type} "
            f"{self.target_period:%b %Y} >= {self.floor_date}"
        )

    def __repr__(self):
        return (
            f"<PublishedFloor: {self.visa_class}/{self.country}/{self.action_type} "
            f"target={self.target_period} floor={self.floor_date}>"
        )
