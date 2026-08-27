#!/usr/bin/env bash
set -Eeuo pipefail

WFH_DEPLOY_ROOT="${WFH_DEPLOY_ROOT:-/srv/waterfallhunter/app}"
WFH_DEPLOY_SHA="${WFH_DEPLOY_SHA:-}"
ENV_FILE="${WFH_DEPLOY_ROOT}/.env"
DEPLOY_STATE_DIR="${WFH_DEPLOY_ROOT}/.deploy"
BACKUP_DIR="${DEPLOY_STATE_DIR}/backups"
STATE_DIR="${DEPLOY_STATE_DIR}/state"
LOCK_FILE="${WFH_DEPLOY_LOCK_FILE:-${STATE_DIR}/deploy.lock}"
WFH_DEPLOY_BACKUP_RETENTION_COUNT="${WFH_DEPLOY_BACKUP_RETENTION_COUNT:-10}"
DB_PATH="/app/data/waterfall_registry.db"
DEPLOY_EPOCH="$(date -u +%s)"
TELEGRAM_CUTOVER_EPOCH=""
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PREVIOUS_SHA=""
ENV_BACKUP=""
DB_BACKUP=""
DB_BACKUP_SHA256=""
MIGRATION_MAY_HAVE_MUTATED=0
RUNTIME_REPLACED=0
ROLLBACK_ACTIVE=0
CLEANUP_ACTIVE=0

log() {
  printf '[waterfallhunter-deploy] %s\n' "$*"
}

fail() {
  log "ERROR: $*"
  terminate_with_cleanup 1
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

wait_for_container_healthy() {
  local container="$1"
  local attempts="${2:-30}"
  local sleep_seconds="${3:-3}"
  local state i
  for ((i = 1; i <= attempts; i++)); do
    state="$(docker inspect -f '{{if .State.Running}}{{if .State.Health}}{{.State.Health.Status}}{{else}}missing-healthcheck{{end}}{{else}}stopped{{end}}' "$container" 2>/dev/null || true)"
    if [[ "$state" == "healthy" ]]; then
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

resolve_previous_revision() {
  local candidate certificate
  candidate="$(docker inspect -f '{{ index .Config.Labels "org.opencontainers.image.revision" }}' waterfall-backend 2>/dev/null || true)"
  if [[ "$candidate" =~ ^[0-9a-f]{40}$ ]] && git cat-file -e "${candidate}^{commit}" 2>/dev/null; then
    printf '%s\n' "$candidate"
    return 0
  fi

  certificate="${STATE_DIR}/last-successful-deploy.txt"
  if [[ -f "$certificate" ]]; then
    candidate="$(awk -F= '$1 == "revision" {print $2; exit}' "$certificate")"
    if [[ "$candidate" =~ ^[0-9a-f]{40}$ ]] && git cat-file -e "${candidate}^{commit}" 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  candidate="$(git rev-parse HEAD 2>/dev/null || true)"
  [[ "$candidate" =~ ^[0-9a-f]{40}$ ]] || return 1
  git cat-file -e "${candidate}^{commit}" 2>/dev/null || return 1
  printf '%s\n' "$candidate"
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

prune_database_backups() {
  local keep="$WFH_DEPLOY_BACKUP_RETENTION_COUNT"
  local line path index=0
  [[ "$keep" =~ ^[1-9][0-9]*$ ]] || return 1
  [[ -d "$BACKUP_DIR" ]] || return 0
  while IFS= read -r line; do
    index=$((index + 1))
    (( index > keep )) || continue
    path="${line#* }"
    [[ "$path" == "${BACKUP_DIR}/"* ]] || continue
    rm -f -- "$path" "${path}.sha256"
  done < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'waterfall_registry.*.db' -printf '%T@ %p\n' | sort -nr)
}

activate_telegram_for_release() {
  grep -Eq '^TELEGRAM_TOKEN=.+$' "$ENV_FILE" || fail "TELEGRAM_TOKEN is required for automatic signal delivery"
  grep -Eq '^TELEGRAM_CHAT_ID=.+$' "$ENV_FILE" || fail "TELEGRAM_CHAT_ID is required for automatic signal delivery"
  TELEGRAM_CUTOVER_EPOCH="$(date -u +%s)"
  ENV_BACKUP="${STATE_DIR}/env.${PREVIOUS_SHA:-unknown}.${TELEGRAM_CUTOVER_EPOCH}.bak"
  install -d -m 0750 "$STATE_DIR"
  cp -p "$ENV_FILE" "$ENV_BACKUP"
  set_env_value TELEGRAM_SIGNAL_DELIVERY_ENABLED true
  set_env_value TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT "$TELEGRAM_CUTOVER_EPOCH"
}

restore_previous_env() {
  if [[ -n "$ENV_BACKUP" && -f "$ENV_BACKUP" ]]; then
    cp -p "$ENV_BACKUP" "$ENV_FILE"
  fi
}

restore_previous_workspace() {
  [[ -n "$PREVIOUS_SHA" ]] || return 0
  git checkout --detach "$PREVIOUS_SHA" >/dev/null 2>&1 || return 1
  build_revision "$PREVIOUS_SHA" >/dev/null 2>&1 || return 1
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

  if [[ "$MIGRATION_MAY_HAVE_MUTATED" -eq 1 ]]; then
    if ! previous_revision_accepts_current_schema; then
      log "rollback stopped: previous revision is not certified against the current schema"
      git checkout --detach "$WFH_DEPLOY_SHA" >/dev/null 2>&1 || true
      return 1
    fi
  else
    restore_previous_workspace || return 1
  fi

  docker compose up -d --remove-orphans || return 1
  wait_for_backend_endpoint /api/livez 20 3 || return 1
  wait_for_backend_endpoint /api/readyz 30 4 || return 1
  wait_for_container_healthy waterfall-backend 30 3 || return 1
  wait_for_container_healthy waterfall-frontend 30 3 || return 1
  wait_for_container_healthy waterfall-watchdog 30 3 || return 1
  verify_running_revision "$PREVIOUS_SHA" || return 1
  verify_running_signal_only || return 1
  log "rollback certified at ${PREVIOUS_SHA}"
  return 0
}

terminate_with_cleanup() {
  local status="$1"
  [[ "$CLEANUP_ACTIVE" -eq 0 ]] || exit "$status"
  CLEANUP_ACTIVE=1
  trap - ERR TERM HUP INT
  set +e
  if [[ "$RUNTIME_REPLACED" -eq 1 || "$MIGRATION_MAY_HAVE_MUTATED" -eq 1 ]]; then
    log "deployment failed after mutable Production step; attempting bounded rollback"
    rollback_previous_revision \
      || log "automatic rollback could not be certified; backup retained at ${DB_BACKUP:-unavailable}"
  else
    restore_previous_env || true
    restore_previous_workspace \
      || log "pre-mutation workspace restoration could not be certified"
  fi
  exit "$status"
}

on_error() {
  local status=$?
  terminate_with_cleanup "$status"
}

on_signal() {
  local signal="$1"
  local status=1
  case "$signal" in
    HUP) status=129 ;;
    INT) status=130 ;;
    TERM) status=143 ;;
  esac
  log "received ${signal}; initiating bounded cleanup"
  terminate_with_cleanup "$status"
}

trap on_error ERR
trap 'on_signal TERM' TERM
trap 'on_signal HUP' HUP
trap 'on_signal INT' INT

require_command git
require_command docker
require_command flock
require_command awk
require_command find
require_command sort

[[ "$WFH_DEPLOY_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "WFH_DEPLOY_SHA must be an exact 40-character Git SHA"
[[ -d "$WFH_DEPLOY_ROOT/.git" ]] || fail "deployment root is not a Git checkout: $WFH_DEPLOY_ROOT"
[[ -f "$ENV_FILE" ]] || fail "Production .env is missing"
[[ "$WFH_DEPLOY_BACKUP_RETENTION_COUNT" =~ ^[1-9][0-9]*$ ]] || fail "WFH_DEPLOY_BACKUP_RETENTION_COUNT must be a positive integer"

cd "$WFH_DEPLOY_ROOT"
install -d -m 0750 "$STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || fail "another WaterfallHunter deployment is already running"

git fetch --prune origin main
git cat-file -e "${WFH_DEPLOY_SHA}^{commit}" || fail "target revision is not available after fetch"
test "$(git rev-parse origin/main)" = "$WFH_DEPLOY_SHA" \
  || fail "target revision is stale; only the current origin/main tip may deploy"

PREVIOUS_SHA="$(resolve_previous_revision)" || fail "unable to resolve the certified previous Production revision"
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

# From this point onward the migration command may have changed the database
# even when a later verification inside that command exits non-zero.
MIGRATION_MAY_HAVE_MUTATED=1
docker compose run --rm --no-deps waterfall-backend \
  /opt/venv/bin/python -m waterfallhunter.migrate_database \
  --db-path "$DB_PATH" --apply --source-revision "$WFH_DEPLOY_SHA"

activate_telegram_for_release
# TELEGRAM_SIGNAL_DELIVERY_ENABLED and TELEGRAM_SIGNAL_DELIVERY_CUTOVER_AT are release-scoped signal-delivery gates.

docker compose up -d --remove-orphans
RUNTIME_REPLACED=1

wait_for_backend_endpoint /api/livez 20 3 || fail "backend /api/livez did not become healthy"
wait_for_backend_endpoint /api/readyz 30 4 || fail "backend /api/readyz did not become ready"
wait_for_container_healthy waterfall-backend 30 3 || fail "backend container did not become healthy"
wait_for_container_healthy waterfall-frontend 30 3 || fail "frontend container did not become healthy"
wait_for_container_healthy waterfall-watchdog 30 3 || fail "watchdog container did not become healthy"
verify_running_revision "$WFH_DEPLOY_SHA" || fail "running OCI org.opencontainers.image.revision does not match target SHA"
verify_running_signal_only || fail "running backend violated the SIGNAL_ONLY live-trading boundary"

install -d -m 0750 "$STATE_DIR"
cat > "${STATE_DIR}/last-successful-deploy.txt" <<EOF
revision=${WFH_DEPLOY_SHA}
previous_revision=${PREVIOUS_SHA}
deployed_at=${DEPLOY_EPOCH}
backup=${DB_BACKUP}
backup_sha256=${DB_BACKUP_SHA256}
telegram_cutover_at=${TELEGRAM_CUTOVER_EPOCH}
live_trading_enabled=false
product_mode=SIGNAL_ONLY
EOF

prune_database_backups || fail "database backup retention cleanup failed"

trap - ERR TERM HUP INT
log "deployment certified: revision=${WFH_DEPLOY_SHA} previous=${PREVIOUS_SHA} SIGNAL_ONLY=true"
