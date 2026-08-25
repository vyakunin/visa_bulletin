"""The "Median Salary" stat card rendered an average, one screen above the true median.

``get_job_title_statistics`` (and its siblings) alias ``Avg("wage_annual")`` to the key
``median_salary``. The job-title profile's header card printed that mean under the label
"Median Salary" with the subtitle "National Average", while the Salary Distribution card
directly below printed ``percentile_cont(0.50)`` over the SAME queryset. On
/job-title/senior-software-engineer/ that read as $141,112 and $135,000, ~$6k and one
screen apart, both looking to a visitor like "the median for this role" — wage
distributions are right-skewed, so the mean sits above the median on every such page.

The employer profile carried the identical pair (card + ladder on one screen); the salary
search page carried the mislabelled figure with no ladder to contradict it.

The three cards now read the p50 their own page already computes, so a page shows one
median. The label is now true of the number rather than of neither.

STILL OPEN, deliberately: the ``median_salary=Avg(...)`` alias survives at 18 call sites,
so every per-group "Median Salary" TABLE column (top employers, experience levels, metros,
companies, the trend chart) still renders a group mean. Closing that means a
percentile_cont over a GROUP BY on salary_record — a query-shape change on the pages whose
planner behaviour deployment.md documents at length — which is a cost decision, not a
label fix. Tracked on Notion 3bf62b8d409f810c836cc5f970b980c1.

See Notion 3bf62b8d409f810c836cc5f970b980c1.
"""

import unittest
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parents[1] / "webapp" / "templates" / "webapp"

# (template, the context path each page's median card must read)
_CARDS = {
    "job_title_profile.html": "stats.salary_percentiles.p50",
    "employer_profile.html": "stats.salary_percentiles.p50",
    "salary_search.html": "market_stats.salary_percentiles.p50",
}


def _median_card(template_name: str) -> str:
    """The one stat_card include on this page labelled "Median Salary"."""
    text = (_TEMPLATES / template_name).read_text()
    cards = [
        line
        for line in text.splitlines()
        if "stat_card.html" in line and 'label="Median Salary"' in line
    ]
    assert len(cards) == 1, f"{template_name}: expected 1 median card, got {len(cards)}"
    return cards[0]


class TestMedianCardsReadThePercentile(unittest.TestCase):
    def test_each_card_reads_the_p50_its_page_computes(self):
        for template_name, context_path in _CARDS.items():
            with self.subTest(template=template_name):
                self.assertIn(context_path, _median_card(template_name))

    def test_no_card_reads_the_avg_aliased_as_median_salary(self):
        for template_name in _CARDS:
            with self.subTest(template=template_name):
                self.assertNotIn("basic.median_salary", _median_card(template_name))

    def test_job_title_card_no_longer_calls_a_median_a_national_average(self):
        self.assertNotIn("National Average", _median_card("job_title_profile.html"))


class TestTheAliasIsStillAMean(unittest.TestCase):
    """Pins the residual honestly: if someone converts the alias to a real percentile,
    this test fails and points them at the tables that were left behind."""

    def test_the_stats_key_is_still_an_average(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "lib"
            / "business"
            / "salary"
            / "job_title_stats.py"
        ).read_text()
        self.assertIn(
            'median_salary=Avg("wage_annual")',
            source,
            "median_salary is no longer an Avg — re-check every 'Median Salary' TABLE "
            "column, which this change deliberately left rendering a group mean.",
        )


if __name__ == "__main__":
    unittest.main()
