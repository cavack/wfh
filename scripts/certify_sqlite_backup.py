#!/usr/bin/env python3
"""Create an approved SQLite online backup and isolated-restore certificate."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from waterfallhunter.core.sqlite_backup_certification import (
    BackupCertificationError,
    create_certified_backup,
)


def _canonical_absolute_path(value: str) -> Path:
    candidate = Path(value)
    if "\x00" in value or not candidate.is_absolute() or candidate.is_symlink():
        raise argparse.ArgumentTypeError("path must be canonical, absolute, and non-symlinked")
    resolved = candidate.resolve(strict=False)
    if resolved != candidate:
        raise argparse.ArgumentTypeError("path aliases and traversal are not allowed")
    return candidate


def _write_report_atomic(destination: Path, report: dict) -> None:
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise BackupCertificationError("REPORT_TARGET_INVALID")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".partial",
        dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=_canonical_absolute_path)
    parser.add_argument("--backup", required=True, type=_canonical_absolute_path)
    parser.add_argument("--restore-target", required=True, type=_canonical_absolute_path)
    parser.add_argument("--report", required=True, type=_canonical_absolute_path)
    parser.add_argument("--source-failure-domain", required=True)
    parser.add_argument("--destination-failure-domain", required=True)
    args = parser.parse_args()
    if args.report.parent != args.backup.parent:
        parser.error("report must be stored beside the independent backup")
    try:
        report = create_certified_backup(
            source=args.source,
            backup=args.backup,
            restore_target=args.restore_target,
            source_failure_domain=args.source_failure_domain,
            destination_failure_domain=args.destination_failure_domain,
            enforce_distinct_device=True,
        )
        _write_report_atomic(args.report, report)
    except (BackupCertificationError, OSError) as error:
        print(json.dumps({"ok": False, "reason": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                "ok": True,
                "status": report["status"],
                "certification_sha256": report["certification_sha256"],
                "report": str(args.report),
                "production_migration_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
