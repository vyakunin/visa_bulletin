"""What a Visa Bulletin cell says when it does not say a date.

A bulletin cell carries one of three things: a cutoff date, "C" (Current — no
backlog, every priority date in that category/country is eligible), or "U"
(Unavailable — no numbers published this month). The first is a date; the other
two are states, and the whole point of naming them is that neither may be
smuggled into a date field. Substituting one (the bulletin's own month is the
tempting choice for Current, since it reads as "up to now") makes it
indistinguishable from a published cutoff downstream, which invents movement
that never happened.

This is the contract between the aggregator that builds a cutoff series and
every consumer of one — the dashboard table, the trend chart, the priority-date
landing pages. It lives here, alongside the other bulletin enums, because it is
the most constrained module all of them can import: the chart builder must stay
free of the Django model layer.
"""

CUTOFF_STATE_DATE = "date"
CUTOFF_STATE_CURRENT = "current"
CUTOFF_STATE_UNAVAILABLE = "unavailable"
