from datetime import date


class FBSpilloverModel:
    """Models Family-Based visa spillover to Employment-Based pool."""

    def estimate_spillover(self, month: date, knowledge_date: date) -> int:
        """
        Estimate FB→EB spillover for a given month.

        Only occurs in Q4 of fiscal year (Jul-Sep).
        Uses statutory estimate for now (can be enhanced with DOS Annual Report data).
        """
        if month.month not in (7, 8, 9):
            return 0

        # Fallback: statutory estimate (~40K annually, so ~13K/month in Q4)
        # This is a conservative baseline.
        return 13_000
