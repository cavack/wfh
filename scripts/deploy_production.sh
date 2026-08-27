#!/usr/bin/env bash
set -Eeuo pipefail

WFH_DEPLOY_ROOT="${WFH_DEPLOY_ROOT:-/srv/waterfallhunter/app}"
WFH_DEPLOY_SHA="${WFH_DEPLOY_SHA:-}"
LOCK_FILE="${WFH_DEPLOY_LOCK_FILE:-/var/lock/waterfallhunter-deploy.lock}"
ENV_FILE="${WFH_DEPLOY_ROOT}/.env"
DEPLOY_STATE_DIR="${WFH_DEPLOY_ROOT}/.deploy"
BACKUP_DIR="${DEPLOY_STATE_DIR}/backups"
STATE_DIR="${DEPLOY_STATE_DIR}/state"
DB_PATH="/app/data/waterfall_registry.db"
DEPLOY_EPOCH="$(date -u +%s)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PREVIOUS_SHA=""
ENV_BACKUP=""
DB_BACKUP=""
DB_BACKUP_SHA256=""
MIGRATION_APPLIED=0
RUNTIME_REPLACED=0
ROLLBACK_ACTIVE=0

log() {
  printf '[waterfallhunter-deploy] %s\n' "$*"
}

fail() {
  log "ERROR: $*"
  exit 1
}

require_command() {
  local command_name="$1"
  command -v "$command_name" >/dev/null 2>&1 \
    || fail "required command missing: $command_name"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local tmp
  tmp="$(mktemp "${WFH_DEPLOY_ROOT}/.env.deploy.XXXXXX")"
  awk -v key="$key" 'index($0, key "=") != 1 { print }' "$ENV_FILE" > "$tmp"
  printf '%s=%s\n' "$key" "$value" >> "$tmp"
  chmod --reference="$ENV_FILE" "$tmp" 2>/dev/null || chmod 600 "$tmp"
  mv "$tmp" "$ENV_FILE"
}

assert_signal_only_runtime_boundary() {
  grep -Eq '^LIVE_TRADING_ENABLED=(false|False|FALSE|0)$' "$ENV_FILE" \
    || fail "LIVE_TRADING_ENABLED must remain false for SIGNAL_ONLY Production"
}

wait_for_backend_endpoint() {
  local endpoint="$1"
  local attempts="${2:-30}"
  local sleep_seconds="${3:-4}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if docker compose exec -T waterfall-backend /opt/venv/bin/python -c \
      "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000${endpoint}', timeout=3).read()" \
      >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done
  return 1
}

verify_running_revision() {
  local container expected actual
  expected="$1"
  for container in waterfall-backend waterfall-frontend waterfall-watchdog; do
    actual="$(docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$container" 2>/dev/null || true)"
    [[ "$actual" == "$expected" ]] || return 1
  done
}

verify_running_signal_only() {
  docker compose exec -T waterfall-backend /opt/venv/bin/python -c \
    'from waterfallhunter.config import settings; assert settings.live_trading_enabled is False' \
    >/dev/null 2>&1
}

build_revision() {
  local revision="$1"
  local build_date
  build_date="$(git show -s --format=%cI "$revision" 2>/dev/null || printf '%s' "$BUILD_DATE")"
  VCS_REF="$revision" BUILD_DATE="$build_date" VERSION="$revision" \
    docker compose build \
      --build-arg VCS_REF="$revision" \
      --build-arg BUILD_DATE="$build_date" \
      --build-arg VERSION="$revision" \
      waterfall-backend frontend watchdog
}

backup_database() {
  # backup: this marker is intentionally kept stable for deployment-contract tests.
  local backup_name
  backup_name="waterfall_registry.${WFH_DEPLOY_SHA}.${DEPLOY_EPOCH}.db"
  DB_BACKUP="${BACKUP_DIR}/${backup_name}"
  install -d -m 0750 "$BACKUP_DIR"

  docker compose run --rm --no-deps --user 0:0 \
    -v "${BACKUP_DIR}:/backup" \
    waterfall-backend \
    /opt/venv/bin/python -c \
    'import hashlib, pathlib, sqlite3, sys
src=pathlib.Path("/app/data/waterfall_registry.db")
dst=pathlib.Path("/backup") / sys.argv[1]
if not src.is_file(): raise SystemExit("source database missing")
with sqlite3.connect(src) as source, sqlite3.connect(dst) as target:
    source.backup(target)
with sqlite3.connect(dst) as check:
    row=check.execute("PRAGMA integrity_check").fetchone()
    if not row or str(row[0]).lower() != "ok": raise SystemExit("backup integrity check failed")
h=hashlib.sha256()
with dst.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1024*1024), b""): h.update(chunk)
print(h.hexdigest())' \
    "$backup_name" > "${DB_BACKUP}.sha256.tmp"

  DB_BACKUP_SHA256="$(tail -n 1 "${DB_BACKUP}.sha256.tmp" | tr -d '[:space:]')"
  rm -f "${DB_BACKUP}.sha256.tmp"
  [[ "$DB_BACKUP_SHA256" =~ ^[0-9a-f]{64}$ ]] || fail "database backup checksum invalid"
  [[ -s "$DB_BACKUP" ]] || fail "database backup missing after backup step"
  printf '%s  %s\n' "$DB_BACKUP_SHA256" "$(basename "$DB_BACKUP")" > "${DB_BACKUP}.sha256"
  log "database backup certified: ${DB_BACKUP} sha256=${DB_BACKUP_SHA256}"
}

run_migrations() {
  docker compose run --rm --no-deps waterfall-backend \
    /opt/venv/bin/python -m waterfallhunter.migrate_database \
    --db-path "$DB_PATH" --preflight

  docker compose run --rm --no-deps waterfall-backend \
    /opt/venv/bin/python -m waterfallhunter.migrate_database \
    --db-path "$DB_PATH" --apply --source-revision "$WFH_DEPLOY_SHA"
  MIGRATION_APPLIED=1
}

activate_telegram_for_release() {
  grep -Eq '^TELEGRAM_TOKEN=.+$' "$ENV_FILE" || fail "TELEGRAM_TOKEN is required for automatic signal delivery"
  grep -Eq '^TELEGRAM_CHAT_ID=.+$' "$ENV_FILE" || fail "TELEGRAM_CHAT_ID is required for automatic signal delivery"
  ENV_BACKUP="${STATE_DIR}/env.${PREVIOUS_SHA:-unknown}.${DEPLOY_EPOCH}.bak"
  install -d -m 0750 "$STATE_DIR"
  cp -p "$ENV_FILE" "$ENV_BACKUP"
  set_env_value TELEGRAM_SIGNAL_DELIVERY_ENABLED true
  set_env_value TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT "$DEPLOY_EPOCH"
}

restore_previous_env() {
  if [[ -n "$ENV_BACKUP" && -f "$ENV_BACKUP" ]]; then
    cp -p "$ENV_BACKUP" "$ENV_FILE"
  fi
}

previous_revision_accepts_current_schema() {
  [[ -n "$PREVIOUS_SHA" ]] || return 1
  git checkout --detach "$PREVIOUS_SHA" >/dev/null 2>&1 || return 1
  build_revision "$PREVIOUS_SHA" >/dev/null 2>&1 || return 1
  docker compose run --rm --no-deps waterfall-backend \
    /opt/venv/bin/python -m waterfallhunter.migrate_database \
    --db-path "$DB_PATH" --preflight >/dev/null 2>&1
}

rollback_previous_revision() {
  [[ "$ROLLBACK_ACTIVE" -eq 0 ]] || return 1
  ROLLBACK_ACTIVE=1
  restore_previous_env
  [[ -n "$PREVIOUS_SHA" ]] || return 1

  if [[ "$MIGRATION_APPLIED" -eq 1 ]]; then
    if ! previous_revision_accepts_current_schema; then
      log "rollback stopped: previous revision is not certified against the migrated schema"
      git checkout --detach "$WFH_DEPLOY_SHA" >/dev/null 2>&1 || true
      return 1
    fi
  else
    git checkout --detach "$PREVIOUS_SHA" >/dev/null 2>&1 || return 1
    build_revision "$PREVIOUS_SHA" || return 1
  fi

  docker compose up -d --remove-orphans || return 1
  wait_for_backend_endpoint /api/livez 20 3 || return 1
  wait_for_backend_endpoint /api/readyz 30 4 || return 1
  verify_running_revision "$PREVIOUS_SHA" || return 1
  verify_running_signal_only || return 1
  log "rollback certified at ${PREVIOUS_SHA}"
  return 0
}

on_error() {
  local status=$?
  trap - ERR
  if [[ "$RUNTIME_REPLACED" -eq 1 || "$MIGRATION_APPLIED" -eq 1 ]]; then
    log "deployment failed after mutable Production step; attempting bounded rollback"
    rollback_previous_revision || log "automatic rollback could not be certified; backup retained at ${DB_BACKUP:-unavailable}"
  else
    restore_previous_env || true
  fi
  exit "$status"
}
trap on_error ERR

require_command git
require_command docker
require_command flock
require_command awk
require_command sha256sum

[[ "$WFH_DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "WFH_DEPLOY_SHA must be an exact 40-character Git SHA"
[[ -d "$WFH_DEPLOY_ROOT/.git" ]] || fail "deployment root is not a Git checkout: $WFH_DEPLOY_ROOT"
[[ -f "$ENV_FILE" ]] || fail "Production .env is missing"

cd "$WFH_DEPLOY_ROOT"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another WaterfallHunter deployment is already running"

# git merge-base --is-ancestor is the exact-revision ancestry gate.
git fetch --prune origin main
git cat-file -e "${WFH_DEPLOY_SHA}^{commit}" || fail "target revision is not available after fetch"
git merge-base --is-ancestor "$WFH_DEPLOY_SHA" origin/main \
  || fail "target revision is not contained in origin/main"

PREVIOUS_SHA="$(git rev-parse HEAD)"
assert_signal_only_runtime_boundary

git checkout --detach "$WFH_DEPLOY_SHA"
docker compose config --quiet
assert_signal_only_runtime_boundary

docker compose build \
  --build-arg VCS_REF="$WFH_DEPLOY_SHA" \
  --build-arg BUILD_DATE="$BUILD_DATE" \
  --build-arg VERSION="$WFH_DEPLOY_SHA" \
  waterfall-backend frontend watchdog

backup_database

docker compose run --rm --no-deps waterfall-backend \
  /opt/venv/bin/python -m waterfallhunter.migrate_database \
  --db-path "$DB_PATH" --preflight

docker compose run --rm --no-deps waterfall-backend \
  /opt/venv/bin/python -m waterfallhunter.migrate_database \
  --db-path "$DB_PATH" --apply --source-revision "$WFH_DEPLOY_SHA"
MIGRATION_APPLIED=1

activate_telegram_for_release
# TELEGRAM_SIGNAL_DELIVERY_ENABLED and TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT are release-scoped signal-delivery gates.

docker compose up -d --remove-orphans
RUNTIME_REPLACED=1

wait_for_backend_endpoint /api/livez 20 3 || fail "backend /api/livez did not become healthy"
wait_for_backend_endpoint /api/readyz 30 4 || fail "backend /api/readyz did not become ready"
verify_running_revision "$WFH_DEPLOY_SHA" || fail "running OCI org.opencontainers.image.revision does not match target SHA"
verify_running_signal_only || fail "running backend violated the SIGNAL_ONLY live-trading boundary"

install -d -m 0750 "$STATE_DIR"
cat > "${STATE_DIR}/last-successful-deploy.txt" <<EOF
revision=${WFH_DEPLOY_SHA}
previous_revision=${PREVIOUS_SHA}
deployed_at=${DEPLOY_EPOCH}
backup=${DB_BACKUP}
backup_sha256=${DB_BACKUP_SHA256}
telegram_cutover_at=${DEPLOY_EPOCH}
live_trading_enabled=false
product_mode=SIGNAL_ONLY
EOF

trap - ERR
log "deployment certified: revision=${WFH_DEPLOY_SHA} previous=${PREVIOUS_SHA} SIGNAL_ONLY=true"
