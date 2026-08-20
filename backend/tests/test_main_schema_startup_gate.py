from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from waterfallhunter.core.schema_contract import SchemaContractError


def test_import_main_does_not_create_or_require_registry_database(tmp_path: Path):
    db_path = tmp_path / "missing-registry.db"
    env = os.environ.copy()
    env["REGISTRY_DB_PATH"] = str(db_path)
    env["LIVE_TRADING_ENABLED"] = "false"
    code = (
        "from pathlib import Path; "
        "import waterfallhunter.main; "
        f"assert not Path({str(db_path)!r}).exists()"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert db_path.exists() is False


def test_startup_rejects_missing_schema_before_starting_background_work(
    tmp_path: Path,
    monkeypatch,
):
    import waterfallhunter.main as main

    missing_db = tmp_path / "missing-startup.db"
    started = []

    def record_background(coro):
        started.append(coro)
        close = getattr(coro, "close", None)
        if callable(close):
            close()
        return None

    monkeypatch.setattr(main.db, "db_path", str(missing_db))
    monkeypatch.setattr(main, "_start_background_task", record_background)

    with pytest.raises(SchemaContractError):
        asyncio.run(main.startup_event())

    assert started == []
    assert missing_db.exists() is False
