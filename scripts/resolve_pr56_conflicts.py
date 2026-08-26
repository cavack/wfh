#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from pathlib import Path

BASE = "d6a23c1f69794aac31b1dce5e5a07ea69b614585"
MERGE_HEAD = "ff462dfa186964a2180aa57611a4c6a2c0641bb3"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, check=check, capture_output=True)


def git(*args: str, check: bool = True) -> str:
    return run("git", *args, check=check).stdout.strip()


def fail(message: str) -> None:
    raise SystemExit(message)


if git("rev-parse", "HEAD") != BASE:
    fail("ABORT_WRONG_HEAD")

if git("rev-parse", "MERGE_HEAD") != MERGE_HEAD:
    fail("ABORT_WRONG_MERGE_HEAD")

notifier = Path("backend/src/waterfallhunter/core/notifier.py")
main = Path("backend/src/waterfallhunter/main.py")

if not notifier.is_file() or not main.is_file():
    fail("ABORT_REQUIRED_FILES_MISSING")

# Resolve notifier.py by replacing the whole polling method with a semantic
# combination of PR56 durable delivery + PR59 long-lived polling/backoff.
text = notifier.read_text(encoding="utf-8")
start_token = "    async def start_interactive_bot(self):"
end_token = "    async def _process_command"
start = text.find(start_token)
end = text.find(end_token, start)
if start < 0 or end < 0:
    fail("NOTIFIER_METHOD_BOUNDARY_NOT_FOUND")

replacement = '''    async def start_interactive_bot(self):
        if not self.enabled:
            return

        delivery_task = (
            asyncio.create_task(self._delivery_loop())
            if self.signal_delivery_enabled
            else None
        )

        url = f"https://api.telegram.org/bot{self.token}/getUpdates"
        logger.info("📡 Interactive Telegram Command Center Online.")

        if self.signal_delivery_enabled:
            logger.info(
                "Durable STRICT Telegram signal delivery enabled "
                "from cutover_at=%s.",
                self.signal_delivery_cutover_at,
            )
        else:
            logger.info("Durable STRICT Telegram signal delivery disabled.")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                try:
                    resp = await client.get(
                        url,
                        params={"offset": -1, "timeout": 5},
                    )
                    if resp.status_code == 200:
                        updates = resp.json().get("result", [])
                        if updates:
                            self.offset = updates[-1]["update_id"] + 1
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "Telegram getUpdates bootstrap failed (%s): %.200s",
                        type(exc).__name__,
                        str(exc),
                    )

                while True:
                    try:
                        resp = await client.get(
                            url,
                            params={"offset": self.offset, "timeout": 20},
                        )

                        if resp.status_code == 429:
                            retry_after = float(
                                resp.headers.get("Retry-After", "30")
                            )
                            logger.warning(
                                "Telegram poll rate-limited; backing off %ss.",
                                retry_after,
                            )
                            await asyncio.sleep(retry_after)
                            continue

                        if resp.status_code == 200:
                            updates = resp.json().get("result", [])
                            for update in updates:
                                self.offset = update["update_id"] + 1
                                message = update.get("message", {})
                                chat = message.get("chat", {})
                                command_text = message.get("text", "")
                                if (
                                    str(chat.get("id")) == self.chat_id
                                    and command_text.startswith("/")
                                ):
                                    await self._process_command(command_text)
                        elif resp.status_code in (401, 403):
                            logger.error(
                                "Telegram polling rejected (HTTP %s): check "
                                "TELEGRAM_TOKEN/CHAT_ID.",
                                resp.status_code,
                            )
                            await asyncio.sleep(60)

                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.warning(
                            "Telegram getUpdates poll failed (%s): %.200s",
                            type(exc).__name__,
                            str(exc),
                        )

                    await asyncio.sleep(1)
        finally:
            if delivery_task is not None:
                delivery_task.cancel()
                await asyncio.gather(
                    delivery_task,
                    return_exceptions=True,
                )

'''

text = text[:start] + replacement + text[end:]

# Resolve the /armed merge hunk in favor of the explicit None check from main.
import re
text, count = re.subn(
    r"<<<<<<< HEAD\n\s*if self\.db is None:\n=======\n\s*if not self\.db:\n>>>>>>> [0-9a-f]+\n",
    "            if self.db is None:\n",
    text,
    count=1,
)
if count != 1:
    # If start_interactive replacement consumed all markers and the block is
    # already resolved, accept it only when the desired line is present.
    if "            if self.db is None:\n" not in text:
        fail("NOTIFIER_ARMED_CONFLICT_NOT_RESOLVED")

notifier.write_text(text, encoding="utf-8")

# Resolve main.py: preserve PR59's bound _semaphore while taking PR56's rule
# that periodic DB flush occurs only after semaphore release.
text = main.read_text(encoding="utf-8")
conflict_starts = [m.start() for m in re.finditer(r"(?m)^<<<<<<< HEAD$", text)]
if len(conflict_starts) != 1:
    fail(f"EXPECTED_ONE_MAIN_CONFLICT_GOT_{len(conflict_starts)}")
start = conflict_starts[0]
end_match = re.search(r"(?m)^>>>>>>> [0-9a-f]+$", text[start:])
if end_match is None:
    fail("MAIN_CONFLICT_END_NOT_FOUND")
end = start + end_match.end()

main_replacement = '''                    should_flush = False
                    try:
                        async with _semaphore:
                            try:
                                if _hunter_running:
                                    await evaluate_candidate(
                                        symbol,
                                        data,
                                    )
                                    _hunter_last_progress_at = (
                                        time.time()
                                    )
                            finally:
                                evaluations_since_flush += 1
'''

text = text[:start] + main_replacement + text[end:]
main.write_text(text, encoding="utf-8")

for path in (notifier, main):
    body = path.read_text(encoding="utf-8")
    if any(marker in body for marker in ("<<<<<<<", "=======", ">>>>>>>")):
        fail(f"CONFLICT_MARKERS_REMAIN:{path}")

# Safety invariants from #60 and Telegram hardening must still be present.
main_text = main.read_text(encoding="utf-8")
for needle in (
    "lifecycle_v2_decision_clock_at = time.time()",
    "decision_clock_at=lifecycle_v2_decision_clock_at",
    "async with _semaphore",
    "should_flush = False",
):
    if needle not in main_text:
        fail(f"MISSING_MAIN_INVARIANT:{needle}")

notifier_text = notifier.read_text(encoding="utf-8")
for needle in (
    "signal_delivery_enabled",
    "signal_delivery_cutover_at",
    "SIGNAL_DELIVERY_DISABLED",
    "Suppressing pre-cutover STRICT",
    "resp.status_code == 429",
    "resp.status_code in (401, 403)",
):
    if needle not in notifier_text:
        fail(f"MISSING_NOTIFIER_INVARIANT:{needle}")

# Stage the two resolved files so Git considers the merge conflicts resolved.
run("git", "add", str(notifier), str(main))

unmerged = git("diff", "--name-only", "--diff-filter=U")
if unmerged:
    fail("UNMERGED_FILES_REMAIN:\n" + unmerged)

# Syntax-check the critical Python files. This does not commit or push.
run(
    "python3",
    "-m",
    "py_compile",
    "backend/src/waterfallhunter/core/notifier.py",
    "backend/src/waterfallhunter/core/ai_veto.py",
    "backend/src/waterfallhunter/core/candle_analyzer.py",
    "backend/src/waterfallhunter/main.py",
)

run("git", "diff", "--cached", "--check")

print("RESOLVER_STATUS=PASS")
print("CONFLICT_MARKERS=0")
print("UNMERGED_FILES=0")
print("COMPILE_RC=0")
print("DIFF_CHECK_RC=0")
print("DO_NOT_COMMIT_YET=YES")
print("NO_PUSH=YES")
print("NO_PRODUCTION_CHANGE=YES")
