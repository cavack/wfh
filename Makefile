SHELL := /bin/bash
PYTHON ?= python3
DB_PATH ?= /srv/waterfallhunter/data/waterfall_registry.db

.PHONY: help setup test typecheck build validate clean-install-check status logs backup-check migration-rehearsal

help:
	@printf '%s
' 'setup test typecheck build validate clean-install-check status logs backup-check migration-rehearsal'

setup:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --only-binary=:all: --require-hashes -r backend/requirements.lock
	npm --prefix frontend ci

test:
	PYTHONPATH=backend/src:. $(PYTHON) -m pytest -q backend/tests

typecheck:
	npm --prefix frontend run typecheck

build:
	npm --prefix frontend run build

validate:
	$(PYTHON) scripts/verify_repository_hygiene.py --root .
	$(PYTHON) scripts/validate_wfh_skills.py
	PYTHONPATH=backend/src:. $(PYTHON) scripts/verify_runtime_parity.py
	$(MAKE) test
	$(MAKE) typecheck
	$(MAKE) build

clean-install-check:
	./scripts/validate_clean_install.sh

status:
	docker compose ps

logs:
	docker compose logs --tail=200

backup-check:
	DB_PATH='$(DB_PATH)' $(PYTHON) -c "import os,sqlite3; p=os.environ['DB_PATH']; c=sqlite3.connect('file:'+p+'?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchone()[0])"

migration-rehearsal:
	$(PYTHON) scripts/rehearse_sqlite_migration.py --help
