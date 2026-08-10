"""Record a floor the State Department published in a bulletin's notes section.

A bulletin's lettered notes sometimes bound a FUTURE month's cutoff from below —
July 2026, section F: "It is likely that in October the final action date will
advance to at least the final action date announced in the May 2026 Visa
Bulletin". The chart parser reads only the four named tables and the prose is
persisted nowhere, so there is nothing to parse after the fact; the bulletin HTML
is transient. This script is therefore the entry point: **an agent reads the
notes, resolves the referenced date, and passes the values in.** It validates and
writes; it does not interpret.

Resolving the floor date is the reader's job, not this script's. The statement
above names a bulletin ("the May 2026 Visa Bulletin"), not a date — look up that
bulletin's own cell for the series and pass the result to --floor-date.

Idempotent: re-recording the same (source bulletin, target period, series)
updates that row in place, so a re-run after a correction never duplicates.

Usage:
    bazel run //scripts/bulletin:record_published_floor -- \\
        --source-bulletin 2026-07 --target 2026-10 \\
        --visa-class 2nd --country india --action-type final_action \\
        --floor-date 2014-07-15 --section F \\
        --quote "It is likely that in October the final action date will advance ..."

    # inspect what is on file
    bazel run //scripts/bulletin:record_published_floor -- --list
    # validate without writing
    bazel run //scripts/bulletin:record_published_floor -- --dry-run ...

Reads: the bulletin table (source bulletin must already be ingested).
Writes: one published_floor row.
Consumed by: lib/business/vqs/october_reset.py, which clamps the October-reset
distribution so a published forecast cannot contradict the statement.
"""

import argparse
import logging
import sys
from datetime import date, timedelta

import django
from django.conf import settings

if not settings.configured:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.path.append(".")
    django.setup()

from lib.utils.logging_utils import ScriptLogger
from models.bulletin import Bulletin
from models.enums.action_type import ActionType
from models.enums.country import Country
from models.enums.visa_category import VisaCategory
from models.published_floor import PublishedFloor

logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# A floor is an auditable claim entered by hand, so the verbatim sentence is
# mandatory and a fragment too short to be a sentence is rejected — a quote
# nobody can check against the bulletin defeats the point of storing one.
MIN_QUOTE_CHARS = 40


class ValidationError(Exception):
    """A rejected input, reported with what to pass instead."""


def _parse_month(value: str, label: str) -> date:
    """YYYY-MM (or YYYY-MM-DD) to the first of that month."""
    parts = value.split("-")
    try:
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        if len(parts) == 3:
            return date(int(parts[0]), int(parts[1]), int(parts[2])).replace(day=1)
    except ValueError:
        pass
    raise ValidationError(f"--{label}: expected YYYY-MM, got {value!r}")


def _parse_country(value: str) -> int:
    if value.isdigit():
        country = Country(int(value)) if int(value) in Country.values else None
    else:
        country = Country.from_string(value)
    if country is None or country == Country.INVALID:
        valid = ", ".join(
            Country.slug_for_value(c.value) for c in Country if c != Country.INVALID
        )
        raise ValidationError(f"--country: unknown {value!r}. Valid: {valid}")
    return int(country)


def resolve_source_bulletin(source_period: date) -> Bulletin:
    bulletin = Bulletin.objects.filter(publication_date=source_period).first()
    if bulletin is None:
        latest = Bulletin.objects.order_by("-publication_date").first()
        newest = latest.publication_date.strftime("%Y-%m") if latest else "none"
        raise ValidationError(
            f"--source-bulletin: no bulletin ingested for "
            f"{source_period:%Y-%m}. Newest on file: {newest}. A floor hangs off "
            f"the bulletin that stated it, so ingest that bulletin first."
        )
    return bulletin


def validate(
    *,
    source_bulletin: Bulletin,
    target_period: date,
    floor_date: date,
    quote: str,
    visa_class: str,
    action_type: str,
    visa_category: str,
) -> None:
    """Reject the inputs that would store a claim nobody can act on."""
    if target_period <= source_bulletin.publication_date:
        raise ValidationError(
            f"--target {target_period:%Y-%m} is not after the source bulletin "
            f"({source_bulletin.publication_date:%Y-%m}). A floor is a statement "
            f"about a LATER period; for the source bulletin's own month, the "
            f"cutoff table already carries the value."
        )
    if floor_date >= target_period:
        raise ValidationError(
            f"--floor-date {floor_date} is not earlier than the target period "
            f"{target_period:%Y-%m}. A final action / filing date is a priority "
            f"date, always in the past relative to the bulletin that publishes it."
        )
    if action_type not in ActionType.values:
        raise ValidationError(
            f"--action-type: unknown {action_type!r}. Valid: {', '.join(ActionType.values)}"
        )
    if visa_category not in VisaCategory.values:
        raise ValidationError(
            f"--category: unknown {visa_category!r}. Valid: {', '.join(VisaCategory.values)}"
        )
    if not visa_class.strip():
        raise ValidationError("--visa-class must not be empty")
    if len(quote.strip()) < MIN_QUOTE_CHARS:
        raise ValidationError(
            f"--quote is {len(quote.strip())} chars; at least {MIN_QUOTE_CHARS} are "
            f"required. Store the verbatim sentence — it is the only way a human "
            f"can audit a hand-entered floor against the bulletin."
        )


def record_floor(
    *,
    source_period: date,
    target_period: date,
    visa_class: str,
    country: int,
    action_type: str,
    floor_date: date,
    quote: str,
    section: str = "",
    visa_category: str = VisaCategory.EMPLOYMENT_BASED,
    dry_run: bool = False,
) -> tuple[PublishedFloor | None, str]:
    """Validate and upsert one floor. Returns (row, "created"|"updated"|"unchanged")."""
    source_bulletin = resolve_source_bulletin(source_period)
    validate(
        source_bulletin=source_bulletin,
        target_period=target_period,
        floor_date=floor_date,
        quote=quote,
        visa_class=visa_class,
        action_type=action_type,
        visa_category=visa_category,
    )

    key = {
        "source_bulletin": source_bulletin,
        "target_period": target_period,
        "visa_category": visa_category,
        "visa_class": visa_class,
        "action_type": action_type,
        "country": country,
    }
    values = {"floor_date": floor_date, "source_quote": quote.strip(), "source_section": section}

    existing = PublishedFloor.objects.filter(**key).first()
    if dry_run:
        return existing, "would_update" if existing else "would_create"
    if existing and all(getattr(existing, f) == v for f, v in values.items()):
        return existing, "unchanged"

    row, created = PublishedFloor.objects.update_or_create(defaults=values, **key)
    return row, "created" if created else "updated"


def list_floors() -> list[PublishedFloor]:
    return list(PublishedFloor.objects.select_related("source_bulletin").all())


def report_effect(
    visa_class: str, country: int, action_type: str, knowledge_date: date
) -> None:
    """Print the October-reset estimate this floor governs.

    Recording a floor is only half the job — the point is what it does to the
    forecast, and a floor that binds nothing (or that never reaches the estimator
    because the series is not Unavailable at ``knowledge_date``) looks exactly
    like a successful write. So show the end state, not the click.
    """
    from lib.business.vqs.october_reset import describe_reset, estimate_october_reset

    est = estimate_october_reset(visa_class, country, action_type, knowledge_date)
    if not est.is_unavailable:
        logger.info(
            "Effect: series is not an end-of-FY Unavailable at %s, so the reset "
            "estimator does not run and the floor is inert until it is.",
            knowledge_date,
        )
        return
    logger.info(
        "Effect at knowledge date %s: method=%s anchor=%s n_precedents=%d",
        knowledge_date,
        est.method,
        est.pre_u_cutoff,
        est.n_precedents,
    )
    logger.info(
        "  point=%s  80%% range %s .. %s  floor=%s (precedents below it: %s)",
        est.point,
        est.ci_low,
        est.ci_high,
        est.floor,
        est.diagnostics.get("n_precedents_below_floor"),
    )
    logger.info("  explainer: %s", describe_reset(est, f"{visa_class} {Country(country).label}"))


def _print_floors(rows: list[PublishedFloor]) -> None:
    if not rows:
        logger.info("No published floors on file.")
        return
    logger.info("%d published floor(s):", len(rows))
    for r in rows:
        logger.info(
            "  %s %s %s | target %s | >= %s | from %s bulletin%s",
            r.visa_class,
            Country(r.country).label.split(" (")[0],
            r.action_type,
            r.target_period.strftime("%Y-%m"),
            r.floor_date,
            r.source_bulletin.publication_date.strftime("%Y-%m"),
            f" §{r.source_section}" if r.source_section else "",
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record a published floor read from a bulletin's notes section."
    )
    parser.add_argument("--source-bulletin", help="Bulletin that made the statement, YYYY-MM")
    parser.add_argument("--target", help="Month the floor constrains, YYYY-MM")
    parser.add_argument("--visa-class", help="Series class as ingested, e.g. 2nd")
    parser.add_argument("--country", help="Country slug (india, china, ...) or enum value")
    parser.add_argument(
        "--action-type", default=ActionType.FINAL_ACTION, help="final_action (default) or filing"
    )
    parser.add_argument(
        "--category",
        default=VisaCategory.EMPLOYMENT_BASED,
        help="employment_based (default) or family_sponsored",
    )
    parser.add_argument("--floor-date", help="The bound itself, YYYY-MM-DD")
    parser.add_argument("--quote", help="Verbatim sentence(s) from the bulletin")
    parser.add_argument("--quote-file", help="Read the quote from a file instead of --quote")
    parser.add_argument("--section", default="", help="Lettered note, e.g. F")
    parser.add_argument("--dry-run", action="store_true", help="Validate, write nothing")
    parser.add_argument("--list", action="store_true", help="List recorded floors and exit")
    parser.add_argument(
        "--effect",
        action="store_true",
        help="Print the October-reset estimate for the series and exit, writing "
        "nothing. Needs --visa-class/--country (+ --knowledge-date).",
    )
    parser.add_argument(
        "--knowledge-date",
        help="As-of date for --effect and for the post-write report, YYYY-MM-DD. "
        "Defaults to the day before the target period.",
    )
    args = parser.parse_args()

    script_logger.log_call(
        args={
            "source_bulletin": args.source_bulletin,
            "target": args.target,
            "visa_class": args.visa_class,
            "country": args.country,
            "action_type": args.action_type,
            "floor_date": args.floor_date,
            "list": args.list,
            "dry_run": args.dry_run,
        },
        context="Recording a DOS-published floor read from bulletin prose",
    )

    if args.list:
        _print_floors(list_floors())
        return 0

    if args.effect:
        if not (args.visa_class and args.country and args.knowledge_date):
            parser.error("--effect needs --visa-class, --country and --knowledge-date")
        report_effect(
            args.visa_class,
            _parse_country(args.country),
            args.action_type,
            date.fromisoformat(args.knowledge_date),
        )
        return 0

    required = ["source_bulletin", "target", "visa_class", "country", "floor_date"]
    missing = [f"--{f.replace('_', '-')}" for f in required if not getattr(args, f)]
    if missing:
        parser.error(f"missing required argument(s): {', '.join(missing)} (or use --list)")

    quote = args.quote
    if args.quote_file:
        with open(args.quote_file) as fh:
            quote = fh.read()
    if not quote:
        parser.error("one of --quote or --quote-file is required")

    try:
        row, outcome = record_floor(
            source_period=_parse_month(args.source_bulletin, "source-bulletin"),
            target_period=_parse_month(args.target, "target"),
            visa_class=args.visa_class,
            country=_parse_country(args.country),
            action_type=args.action_type,
            floor_date=date.fromisoformat(args.floor_date),
            quote=quote,
            section=args.section,
            visa_category=args.category,
            dry_run=args.dry_run,
        )
    except ValidationError as err:
        logger.error("Rejected: %s", err)
        return 2
    except ValueError as err:
        logger.error("Rejected: --floor-date must be YYYY-MM-DD (%s)", err)
        return 2

    logger.info("%s: %s", outcome, row if row else "(nothing on file yet)")

    target_period = _parse_month(args.target, "target")
    knowledge_date = (
        date.fromisoformat(args.knowledge_date)
        if args.knowledge_date
        else target_period - timedelta(days=1)
    )
    report_effect(
        args.visa_class, _parse_country(args.country), args.action_type, knowledge_date
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
