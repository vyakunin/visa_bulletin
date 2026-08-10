"""H-1B cap ("lottery") season pages — ``/h1b-lottery/`` and its two children.

The visa bulletin has one demand wave a month; the H-1B cap has three or four a
year — registration in March, results at the end of March, any additional
selection round in late summer, and the October 1 start. Each is an anticipation
window of the same shape the prediction pages already serve, and nothing on the
site answered them.

What separates these pages from the news-style coverage that ranks for these
queries today is that both numeric surfaces are sourced rather than asserted: the
selection rates are USCIS's own published registration statistics, and the
later-round filing waves are measured in the I-129 petition microdata we hold.
Neither is estimated here. See ``lib/business/i129/lottery_season.py``.

Deliberately cheap: one cached whole-table aggregate shared by all three views,
and a module-level table. No per-request scan.
"""

import json

from django.conf import settings
from django.shortcuts import render

from django_config.cache_utils import cache_page_skip_bots
from lib.business.i129.lottery_season import (
    BENEFICIARY_CENTRIC_RULE_URL,
    H1B_ANNUAL_CAP,
    SELECTION_HISTORY_UPDATED,
    USCIS_REGISTRATION_URL,
    USCIS_SELECTION_HISTORY,
    CapSeasonPhase,
    current_cap_season,
    filing_waves,
    latest_published_season,
)

LOTTERY_HUB_PATH = "/h1b-lottery/"
LOTTERY_ODDS_PATH = "/h1b-lottery/odds/"
LOTTERY_SECOND_ROUND_PATH = "/h1b-lottery/second-round/"

# The three pages are one cluster; every page links to the other two.
_SIBLINGS = (
    (LOTTERY_HUB_PATH, "Cap season calendar"),
    (LOTTERY_ODDS_PATH, "Selection odds by year"),
    (LOTTERY_SECOND_ROUND_PATH, "Second-round history"),
)


def _siblings(current_path: str) -> list[dict]:
    return [
        {"url": url, "label": label}
        for url, label in _SIBLINGS
        if url != current_path
    ]


def _faq_schema(faq: list[dict]) -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": item["q"],
                    "acceptedAnswer": {"@type": "Answer", "text": item["a"]},
                }
                for item in faq
            ],
        }
    )


def _phase_sentence(season) -> str:
    """One sentence saying where the cap season stands today."""
    year = season.registration_year
    return {
        CapSeasonPhase.BEFORE_REGISTRATION: (
            f"The FY{season.cap_fy} H-1B cap registration period has not opened yet. "
            f"USCIS announces the dates and the fee before it does; recent seasons "
            f"have registered in March."
        ),
        CapSeasonPhase.REGISTRATION: (
            f"The FY{season.cap_fy} H-1B cap registration period is the current "
            f"phase. Selection follows immediately after it closes, before the "
            f"filing window opens on April 1, {year}."
        ),
        CapSeasonPhase.INITIAL_FILING: (
            f"Selected FY{season.cap_fy} registrants are in the initial filing "
            f"window: petitions can be filed from April 1, {year}, and in the cap "
            f"seasons we hold petition data for, most receipts land in April, May "
            f"and June."
        ),
        CapSeasonPhase.LATER_ROUNDS: (
            f"The FY{season.cap_fy} initial filing window has closed. This is the "
            f"part of the year in which USCIS has run additional selection rounds "
            f"when filed petitions were not going to fill 85,000 slots — August "
            f"and September {year} is where those later petitions were received in "
            f"past seasons."
        ),
        CapSeasonPhase.EMPLOYMENT_STARTED: (
            f"FY{season.cap_fy} cap employment can begin from October 1, {year}. "
            f"The FY{season.cap_fy + 1} registration period follows in March "
            f"{year + 1}."
        ),
    }.get(season.phase, "")


def _hub_faq(season, latest, waves) -> list[dict]:
    rate = f"{latest.selection_rate_pct}%"
    with_wave = [w for w in waves if w.had_later_wave]
    if waves:
        second_a = (
            f"USCIS runs an additional selection round when the petitions filed "
            f"from the first round will not fill the 85,000 cap. In the "
            f"{len(waves)} cap seasons covered by our I-129 petition data "
            f"(FY{waves[0].cap_fy}-FY{waves[-1].cap_fy}), {len(with_wave)} show a "
            f"clear second wave of petition receipts after the initial filing "
            f"window closed. It is not announced in advance."
        )
    else:
        second_a = (
            "USCIS runs an additional selection round when the petitions filed "
            "from the first round will not fill the 85,000 cap. It is not "
            "announced in advance."
        )
    return [
        {
            "q": f"When is the H-1B lottery for FY{season.cap_fy}?",
            "a": (
                f"The H-1B cap season runs on the same annual cycle: USCIS opens "
                f"electronic registration in March {season.registration_year}, "
                f"notifies selected registrants before the filing window opens on "
                f"April 1, and cap employment begins on October 1, "
                f"{season.registration_year}. {_phase_sentence(season)}"
            ),
        },
        {
            "q": "What are the odds of being selected in the H-1B lottery?",
            "a": (
                f"In FY{latest.cap_fy}, the most recent cap season with published "
                f"USCIS figures, {latest.selected_registrations:,} of "
                f"{latest.eligible_registrations:,} eligible registrations were "
                f"selected — {rate}. The rate moves a lot year to year with the "
                f"size of the registration pool. Selection is not a visa: a "
                f"selected registration still has to be filed as a petition and "
                f"approved."
            ),
        },
        {
            "q": "Will there be a second H-1B lottery round?",
            "a": second_a,
        },
        {
            "q": "How many H-1B visas are available each year?",
            "a": (
                f"{H1B_ANNUAL_CAP:,} cap-subject H-1Bs a year: 65,000 under the "
                f"regular cap plus 20,000 reserved for beneficiaries with a U.S. "
                f"master's degree or higher. USCIS selects more registrations than "
                f"that because not every selected registrant files and not every "
                f"petition is approved."
            ),
        },
    ]


def _odds_faq(latest, seasons) -> list[dict]:
    first = seasons[0]
    return [
        {
            "q": f"What was the H-1B selection rate in FY{latest.cap_fy}?",
            "a": (
                f"{latest.selected_registrations:,} of "
                f"{latest.eligible_registrations:,} eligible registrations were "
                f"selected for FY{latest.cap_fy} — {latest.selection_rate_pct}%. "
                f"These are USCIS's own published registration statistics."
            ),
        },
        {
            "q": "Did the 2025 rule change make the H-1B lottery fairer?",
            "a": (
                "From FY2025, USCIS selects by beneficiary rather than by "
                "registration, so a person entered by ten employers has the same "
                "odds as a person entered by one. Before that, registering the "
                "same beneficiary through several employers multiplied their "
                "chances, and over half of FY2024 registrations were for "
                "multi-registered beneficiaries."
            ),
        },
        {
            "q": "Why do the selection rates jump around so much?",
            "a": (
                f"The cap is fixed at {H1B_ANNUAL_CAP:,} while the registration "
                f"pool is not: it ran from {first.eligible_registrations:,} in "
                f"FY{first.cap_fy} to {max(s.eligible_registrations for s in seasons):,} "
                f"at its peak. A rate is selections divided by that pool, so it "
                f"falls when registrations surge and rises when they fall. The "
                f"$10-to-$215 registration fee and the beneficiary-centric rule "
                f"both shrank the pool, and a cooler hiring market moved it too."
            ),
        },
        {
            "q": "Does being selected mean I get an H-1B?",
            "a": (
                "No. Selection only earns the right to file the I-129 petition "
                "within the filing window. The petition still has to be filed and "
                "approved, and USCIS denies a real share of them. Every rate on "
                "this page is a rate of selection, nothing more."
            ),
        },
    ]


def _second_round_faq(season, waves) -> list[dict]:
    with_wave = [w for w in waves if w.had_later_wave]
    without = [w for w in waves if not w.had_later_wave]
    if with_wave:
        biggest = max(with_wave, key=lambda w: w.later_share_pct)
        happened = (
            f"In FY{biggest.cap_fy}, {biggest.later_share_pct}% of that season's "
            f"cap petitions were received after the initial filing window closed — "
            f"{biggest.later_window:,} petitions. "
        )
    else:
        happened = ""
    quiet = (
        f"Seasons with no additional round look completely different: "
        f"FY{without[0].cap_fy} shows {without[0].later_share_pct}%. "
        if without
        else ""
    )
    return [
        {
            "q": "Is there a second H-1B lottery round?",
            "a": (
                f"There is in some cap seasons. USCIS selects again from the "
                f"registrations already submitted when the petitions filed from the "
                f"first round will not fill the {H1B_ANNUAL_CAP:,} cap. {happened}"
                f"{quiet}It is decided after USCIS sees how many selectees actually "
                f"filed, so it is not announced in advance."
            ),
        },
        {
            "q": f"Will there be a second H-1B round for FY{season.cap_fy}?",
            "a": (
                f"Nothing published lets anyone answer that before USCIS does: the "
                f"decision depends on how many FY{season.cap_fy} selectees filed "
                f"during the initial window, which USCIS alone can count. What the "
                f"history below shows is how often it has happened and how large "
                f"the later waves were when it did. If a round is run, registrants "
                f"who were not selected the first time are notified in their USCIS "
                f"online account; there is nothing to re-submit."
            ),
        },
        {
            "q": "Do I need to register again for a second round?",
            "a": (
                "No. Additional rounds draw from the registrations already "
                "submitted that March. A registration that was not selected stays "
                "in the pool for the rest of that cap season."
            ),
        },
        {
            "q": "How is this measured?",
            "a": (
                "Each bar is the share of a cap season's selected-and-filed I-129 "
                "petitions that USCIS received after the initial filing window "
                "closed, from the FOIA-released petition microdata. It measures "
                "when petitions arrived, which is the trace an additional round "
                "leaves, rather than an announcement of one."
            ),
        },
    ]


def _base_context(request, path: str, faq: list[dict]) -> dict:
    canonical = request.build_absolute_uri(path)
    return {
        "canonical_url": canonical,
        "og_url": canonical,
        "faq": faq,
        "structured_data": _faq_schema(faq),
        "siblings": _siblings(path),
        "uscis_registration_url": USCIS_REGISTRATION_URL,
        "beneficiary_rule_url": BENEFICIARY_CENTRIC_RULE_URL,
        "history_updated": SELECTION_HISTORY_UPDATED,
        "annual_cap": H1B_ANNUAL_CAP,
    }


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def h1b_lottery_hub_view(request):
    """``/h1b-lottery/`` — the cap-season calendar and where today falls in it."""
    season = current_cap_season()
    latest = latest_published_season()
    waves = filing_waves()
    faq = _hub_faq(season, latest, waves)

    context = _base_context(request, LOTTERY_HUB_PATH, faq)
    context.update(
        {
            "page_title": (
                f"H-1B Lottery FY{season.cap_fy}: Cap Season Calendar, Dates and "
                f"Selection Odds"
            ),
            "page_heading": f"H-1B Lottery FY{season.cap_fy}",
            "page_description": (
                f"Where the FY{season.cap_fy} H-1B cap season stands: the "
                f"registration, filing and additional-round windows, USCIS's "
                f"published selection rates through FY{latest.cap_fy}, and how "
                f"often a second round has actually happened."
            ),
            "season": season,
            "lead_answer": _phase_sentence(season),
            "latest": latest,
            "first_season_fy": USCIS_SELECTION_HISTORY[0].cap_fy,
            "recent_seasons": USCIS_SELECTION_HISTORY[-3:],
            "waves": waves,
            "waves_with_later": [w for w in waves if w.had_later_wave],
        }
    )
    return render(request, "webapp/h1b_lottery_hub.html", context)


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def h1b_lottery_odds_view(request):
    """``/h1b-lottery/odds/`` — published selection rates, cap season by cap season."""
    season = current_cap_season()
    latest = latest_published_season()
    faq = _odds_faq(latest, USCIS_SELECTION_HISTORY)

    context = _base_context(request, LOTTERY_ODDS_PATH, faq)
    context.update(
        {
            "page_title": (
                f"H-1B Lottery Odds by Year: Selection Rates Through "
                f"FY{latest.cap_fy}"
            ),
            "page_heading": "H-1B Lottery Selection Odds by Year",
            "page_description": (
                f"H-1B cap selection rates for every season from "
                f"FY{USCIS_SELECTION_HISTORY[0].cap_fy} to FY{latest.cap_fy}, from "
                f"USCIS's published registration statistics: eligible "
                f"registrations, selections, and what the FY2025 "
                f"beneficiary-centric rule changed."
            ),
            "season": season,
            "latest": latest,
            "seasons": USCIS_SELECTION_HISTORY,
            "lead_answer": (
                f"USCIS selected {latest.selected_registrations:,} of "
                f"{latest.eligible_registrations:,} eligible registrations for the "
                f"FY{latest.cap_fy} H-1B cap — a {latest.selection_rate_pct}% "
                f"selection rate. The rate has ranged from "
                f"{min(s.selection_rate_pct for s in USCIS_SELECTION_HISTORY)}% to "
                f"{max(s.selection_rate_pct for s in USCIS_SELECTION_HISTORY)}% "
                f"across the seasons below, driven almost entirely by how big the "
                f"registration pool was that year."
            ),
        }
    )
    return render(request, "webapp/h1b_lottery_odds.html", context)


@cache_page_skip_bots(settings.CACHE_TIMEOUT)
def h1b_lottery_second_round_view(request):
    """``/h1b-lottery/second-round/`` — how often a later round has happened."""
    season = current_cap_season()
    waves = filing_waves()
    faq = _second_round_faq(season, waves)
    with_wave = [w for w in waves if w.had_later_wave]

    context = _base_context(request, LOTTERY_SECOND_ROUND_PATH, faq)
    context.update(
        {
            "page_title": (
                f"Will There Be a Second H-1B Lottery Round? FY{season.cap_fy} and "
                f"the History"
            ),
            "page_heading": "Second H-1B Lottery Rounds",
            "page_description": (
                "How often USCIS has run an additional H-1B selection round, "
                "measured in the I-129 petition microdata: the share of each cap "
                "season's petitions that arrived after the initial filing window "
                "closed."
            ),
            "season": season,
            "waves": waves,
            "waves_with_later": with_wave,
            "first_wave_fy": waves[0].cap_fy if waves else None,
            "last_wave_fy": waves[-1].cap_fy if waves else None,
            "lead_answer": (
                f"USCIS runs an additional H-1B selection round when the petitions "
                f"filed from the first round will not fill the {H1B_ANNUAL_CAP:,} "
                f"cap. It has happened in {len(with_wave)} of the {len(waves)} cap "
                f"seasons covered by our petition data, and it leaves an "
                f"unmistakable trace: a second wave of petition receipts months "
                f"after the initial filing window closed."
            )
            if waves
            else (
                f"USCIS runs an additional H-1B selection round when the petitions "
                f"filed from the first round will not fill the {H1B_ANNUAL_CAP:,} cap."
            ),
        }
    )
    return render(request, "webapp/h1b_lottery_second_round.html", context)
