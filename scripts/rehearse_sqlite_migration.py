#!/usr/bin/env python3
"""Rehearse canonical migration and rollback using a certified backup clone."""

from __future__ import annotations

import argparse
import json

from scripts.certify_sqlite_backup import _canonical_absolute_path, _write_report_atomic
from waterfallhunter.core.migration_rehearsal import (
    MigrationRehearsalError,
    rehearse_migration_and_rollback,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup-certification", required=True, type=_canonical_absolute_path)
    parser.add_argument("--migration-target", required=True, type=_canonical_absolute_path)
    parser.add_argument("--rollback-target", required=True, type=_canonical_absolute_path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--report", required=True, type=_canonical_absolute_path)
    args = parser.parse_args()
    if args.report.parent != args.backup_certification.parent:
        parser.error("rehearsal report must remain beside the independent backup")
    try:
        certification = json.loads(
            args.backup_certification.read_text(encoding="utf-8")
        )
        if not isinstance(certification, dict):
            raise MigrationRehearsalError("BACKUP_CERTIFICATION_INVALID")
        report = rehearse_migration_and_rollback(
            backup_certification=certification,
            migration_target=args.migration_target,
            rollback_target=args.rollback_target,
            source_revision=args.source_revision,
        )
        _write_report_atomic(args.report, report)
    except (MigrationRehearsalError, OSError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "reason": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "status": report["status"],
                "rehearsal_sha256": report["rehearsal_sha256"],
                "report": str(args.report),
                "production_migration_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
