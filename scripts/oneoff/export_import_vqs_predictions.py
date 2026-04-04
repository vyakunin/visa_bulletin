"""Export / import PredictedBulletin + PredictedCutoff for copying VQS rows between DBs.

Typical flow (local → prod):

  bazel run //scripts/oneoff:export_import_vqs_predictions -- export --output /tmp/vqs_predictions.json

Copy ``/tmp/vqs_predictions.json`` to the prod host (e.g. secure copy), then on prod:

  cd /opt/visa_bulletin && set -a && source .env && set +a && DB_HOST=localhost \\
    ./bazel-bin/scripts/oneoff/export_import_vqs_predictions import --input /path/to/vqs_predictions.json

Import uses ``(target_bulletin_month, prediction_date)`` as the natural key: existing rows are
replaced (cutoffs deleted and re-inserted). Other ``PredictedBulletin`` rows on prod are untouched
unless you import a bulletin with the same natural key.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import django

django.setup()

from django.db import transaction  # noqa: E402

from lib.utils.logging_utils import log_context  # noqa: E402
from models.vqs import PredictedBulletin, PredictedCutoff  # noqa: E402

logger = logging.getLogger(__name__)

VERSION = 1


def _date_from_json(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def _serialize_bulletin(pb: PredictedBulletin) -> dict[str, Any]:
    cutoffs = []
    for c in pb.cutoffs.order_by("visa_class", "country", "action_type"):
        cutoffs.append({
            "visa_class": c.visa_class,
            "country": c.country,
            "action_type": c.action_type,
            "predicted_date": c.predicted_date.isoformat() if c.predicted_date else None,
            "confidence_low": c.confidence_low.isoformat() if c.confidence_low else None,
            "confidence_high": c.confidence_high.isoformat() if c.confidence_high else None,
            "explanation_markdown": c.explanation_markdown or "",
            "expert_predictions": c.expert_predictions or {},
            "model_name": c.model_name or "",
            "movement_probability": c.movement_probability,
            "actual_date": c.actual_date.isoformat() if c.actual_date else None,
            "accuracy_score": c.accuracy_score,
        })
    return {
        "target_bulletin_month": pb.target_bulletin_month.isoformat(),
        "prediction_date": pb.prediction_date.isoformat(),
        "generated_at": pb.generated_at.isoformat() if pb.generated_at else None,
        "cutoffs": cutoffs,
    }


def cmd_export(args: argparse.Namespace) -> int:
    qs = PredictedBulletin.objects.order_by("target_bulletin_month", "prediction_date")
    if args.target_from:
        qs = qs.filter(target_bulletin_month__gte=date.fromisoformat(args.target_from))
    if args.target_to:
        qs = qs.filter(target_bulletin_month__lte=date.fromisoformat(args.target_to))

    bulletins = [_serialize_bulletin(pb) for pb in qs.prefetch_related("cutoffs")]
    payload = {
        "version": VERSION,
        "exported_at": datetime.now().astimezone().isoformat(),
        "bulletins": bulletins,
    }
    text = json.dumps(payload, indent=2, sort_keys=False)
    out = Path(args.output)
    out.write_text(text, encoding="utf-8")
    n_cutoffs = sum(len(b["cutoffs"]) for b in bulletins)
    logger.info(
        "Wrote %s PredictedBulletin rows (%s cutoffs) to %s",
        len(bulletins),
        n_cutoffs,
        out,
    )
    return 0


def _parse_generated_at(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now()


def cmd_import(args: argparse.Namespace) -> int:
    path = Path(args.input)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("version") != VERSION:
        logger.warning("Unexpected payload version %s (expected %s)", raw.get("version"), VERSION)

    bulletins: list[dict[str, Any]] = raw["bulletins"]
    replaced = 0
    created = 0
    cutoff_total = 0

    with transaction.atomic():
        for b in bulletins:
            tbm = _date_from_json(b["target_bulletin_month"])
            pd = _date_from_json(b["prediction_date"])
            assert tbm is not None and pd is not None

            gen_at = _parse_generated_at(b.get("generated_at"))
            pb, was_created = PredictedBulletin.objects.get_or_create(
                target_bulletin_month=tbm,
                prediction_date=pd,
                defaults={"generated_at": gen_at},
            )
            if not was_created:
                pb.generated_at = gen_at
                pb.save(update_fields=["generated_at"])
                PredictedCutoff.objects.filter(bulletin=pb).delete()
                replaced += 1
            else:
                created += 1

            rows: list[PredictedCutoff] = []
            for c in b["cutoffs"]:
                rows.append(
                    PredictedCutoff(
                        bulletin=pb,
                        visa_class=c["visa_class"],
                        country=int(c["country"]),
                        action_type=c["action_type"],
                        predicted_date=_date_from_json(c.get("predicted_date")),
                        confidence_low=_date_from_json(c.get("confidence_low")),
                        confidence_high=_date_from_json(c.get("confidence_high")),
                        explanation_markdown=c.get("explanation_markdown") or "",
                        expert_predictions=c.get("expert_predictions") or {},
                        model_name=c.get("model_name") or "",
                        movement_probability=c.get("movement_probability"),
                        actual_date=_date_from_json(c.get("actual_date")),
                        accuracy_score=c.get("accuracy_score"),
                    )
                )
            PredictedCutoff.objects.bulk_create(rows, batch_size=500)
            cutoff_total += len(rows)

    logger.info(
        "Import done: %s created, %s replaced, %s cutoffs inserted",
        created,
        replaced,
        cutoff_total,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_export = sub.add_parser("export", help="Write JSON snapshot from current database")
    p_export.add_argument(
        "--output",
        "-o",
        required=True,
        help="Output JSON path (e.g. /tmp/vqs_predictions.json)",
    )
    p_export.add_argument(
        "--target-from",
        metavar="YYYY-MM-DD",
        help="Only bulletins with target_bulletin_month >= this (first of month)",
    )
    p_export.add_argument(
        "--target-to",
        metavar="YYYY-MM-DD",
        help="Only bulletins with target_bulletin_month <= this",
    )

    p_import = sub.add_parser("import", help="Load JSON snapshot into current database")
    p_import.add_argument(
        "--input",
        "-i",
        required=True,
        help="Input JSON path from export",
    )

    args = parser.parse_args()
    log_context("Export or import VQS PredictedBulletin / PredictedCutoff rows between environments")

    if args.cmd == "export":
        return cmd_export(args)
    if args.cmd == "import":
        return cmd_import(args)
    return 1


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
