"""H-1B petition approval-rate stats for an employer, from the USCIS Data Hub.

The employer profile page already shows an "Approval Rate" — but that's the LCA
CERTIFICATION rate (~99% for everyone; DOL rarely denies an LCA), which is
non-differentiating. The USCIS I-129 petition first-decision APPROVAL rate is the
meaningful signal: USCIS denies a real share of petitions, and the rate varies a lot
by employer. We aggregate the Data Hub's initial/continuing approval + denial counts
(lib/ingest/plugins/uscis_datahub.py) over an employer cluster.

The INITIAL approval rate (new petitions) is the headline — continuing (renewal)
petitions approve at near-100% for almost everyone, so a blended rate understates the
signal. Aggregates only, with small-n suppression.
"""

import logging
from dataclasses import dataclass

from django.db.models import Max, Min, Sum

from models.uscis_employer import UscisEmployerApproval

logger = logging.getLogger(__name__)

# Suppress the section for clusters with fewer than this many INITIAL decisions
# (approvals + denials) — a rate over a handful of petitions is noise.
MIN_INITIAL_DECISIONS = 100


@dataclass(frozen=True)
class ApprovalStats:
    """Aggregate USCIS I-129 approval/denial counts for one employer cluster."""

    fy_min: int
    fy_max: int
    initial_approvals: int
    initial_denials: int
    continuing_approvals: int
    continuing_denials: int

    @property
    def initial_decisions(self) -> int:
        return self.initial_approvals + self.initial_denials

    @property
    def total_decisions(self) -> int:
        return (
            self.initial_approvals
            + self.initial_denials
            + self.continuing_approvals
            + self.continuing_denials
        )

    @property
    def initial_approval_rate(self) -> float:
        """New-petition approval rate (%) — the headline signal."""
        d = self.initial_decisions
        return round(100.0 * self.initial_approvals / d, 1) if d else 0.0

    @property
    def overall_approval_rate(self) -> float:
        """Blended initial + continuing approval rate (%)."""
        approvals = self.initial_approvals + self.continuing_approvals
        d = self.total_decisions
        return round(100.0 * approvals / d, 1) if d else 0.0

    @property
    def fy_coverage(self) -> str:
        if self.fy_min == self.fy_max:
            return f"FY{self.fy_min}"
        return f"FY{self.fy_min}–FY{self.fy_max}"


def get_employer_approval_stats(cluster) -> ApprovalStats | None:
    """USCIS I-129 approval stats for one employer cluster, or None if too thin.

    ``cluster`` is any object with an ``id`` (an ``EmployerCluster``). Returns None
    when fewer than ``MIN_INITIAL_DECISIONS`` initial decisions are on record (the
    view then hides the section).
    """
    cluster_id = getattr(cluster, "id", None)
    if cluster_id is None:
        return None
    agg = UscisEmployerApproval.objects.filter(employer_cluster_id=cluster_id).aggregate(
        ia=Sum("initial_approval"),
        idn=Sum("initial_denial"),
        ca=Sum("continuing_approval"),
        cdn=Sum("continuing_denial"),
        fy_min=Min("fiscal_year"),
        fy_max=Max("fiscal_year"),
    )
    ia = agg["ia"] or 0
    idn = agg["idn"] or 0
    if ia + idn < MIN_INITIAL_DECISIONS:
        return None
    return ApprovalStats(
        fy_min=agg["fy_min"] or 0,
        fy_max=agg["fy_max"] or 0,
        initial_approvals=ia,
        initial_denials=idn,
        continuing_approvals=agg["ca"] or 0,
        continuing_denials=agg["cdn"] or 0,
    )
