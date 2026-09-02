#!/bin/sh
set -eu

ROOT=$(git rev-parse --show-toplevel)
cd "$ROOT"

for HOOK in .githooks/pre-commit .githooks/pre-push; do
    if [ ! -f "$HOOK" ]; then
        echo "missing Council hook: $HOOK" >&2
        exit 2
    fi
    chmod +x "$HOOK"
done

git config --local core.hooksPath .githooks
printf '%s\n' "WaterfallHunter Council hooks enabled for $ROOT"
