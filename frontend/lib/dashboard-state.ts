export type SnapshotIdentity = Readonly<{
  snapshot_version: number;
  generated_at: number;
}>;

type CandidateLike = Record<string, unknown>;
type CandidateEntry = [string, CandidateLike];

type CandidateRank = Readonly<{
  source: "primary" | "watch";
  score: number;
  coverage: number | undefined;
  effectiveScore: number | undefined;
}>;

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

/**
 * Decide whether an incoming READY snapshot is newer than the currently
 * accepted snapshot.
 *
 * Polling can legitimately preview version 1 without advancing the SSE
 * buffer. The first retained SSE snapshot can therefore also be version 1.
 * generated_at is the deterministic tie-breaker for that equal-version
 * bootstrap race.
 *
 * The backend snapshot sequence is intentionally process-local. A backend
 * restart can therefore reset the sequence from a large value to 1 while an
 * already-open browser still remembers the old value. A lower version is only
 * accepted when the caller has observed a transport reconnect and the new
 * payload was generated strictly later than the currently accepted payload.
 * This prevents an ordinary stale replay from masquerading as a new process
 * generation without relying on an arbitrary timeout.
 */
export function shouldAcceptDashboardSnapshot(
  current: SnapshotIdentity | null,
  incoming: SnapshotIdentity,
  options: Readonly<{ allowVersionReset?: boolean }> = {},
): boolean {
  if (current === null) {
    return true;
  }

  if (incoming.snapshot_version > current.snapshot_version) {
    return true;
  }

  if (incoming.snapshot_version === current.snapshot_version) {
    return incoming.generated_at > current.generated_at;
  }

  return options.allowVersionReset === true
    && incoming.generated_at > current.generated_at;
}

function candidateRank(candidate: CandidateLike): CandidateRank | undefined {
  const metrics = asRecord(candidate.metrics);
  const primaryScore = finiteNumber(candidate.score);

  if (
    primaryScore !== undefined
    && metrics?.score_version === "score_v2"
    && metrics.trade_eligible === true
  ) {
    return {
      source: "primary",
      score: primaryScore,
      coverage: undefined,
      effectiveScore: primaryScore,
    };
  }

  const watch = asRecord(metrics?.watch_score);
  const watchScore = finiteNumber(watch?.score);

  if (watchScore === undefined) {
    return undefined;
  }

  const coverage = finiteNumber(watch?.coverage_pct);

  return {
    source: "watch",
    score: watchScore,
    coverage,
    effectiveScore: coverage === undefined
      ? undefined
      : watchScore * coverage / 100,
  };
}

function comparePresence<T>(left: T | undefined, right: T | undefined): number {
  if (left !== undefined && right === undefined) {
    return -1;
  }
  if (left === undefined && right !== undefined) {
    return 1;
  }
  return 0;
}

function compareFiniteDescending(
  left: number | undefined,
  right: number | undefined,
): number {
  const presenceOrder = comparePresence(left, right);
  if (presenceOrder !== 0 || left === undefined || right === undefined) {
    return presenceOrder;
  }
  return right - left;
}

function compareRanks(
  left: CandidateRank | undefined,
  right: CandidateRank | undefined,
): number {
  const rankPresence = comparePresence(left, right);
  if (rankPresence !== 0 || left === undefined || right === undefined) {
    return rankPresence;
  }

  const effectiveOrder = compareFiniteDescending(
    left.effectiveScore,
    right.effectiveScore,
  );
  if (effectiveOrder !== 0) {
    return effectiveOrder;
  }

  const scoreOrder = right.score - left.score;
  if (scoreOrder !== 0) {
    return scoreOrder;
  }

  return compareFiniteDescending(left.coverage, right.coverage);
}

/**
 * Complete Score V2 keeps its existing score. A partial Watch Score is ranked
 * by normalized score multiplied by evidence coverage so redistributed
 * missing evidence cannot make a sparse observation look stronger than it is.
 * Missing coverage stays unavailable rather than being treated as zero or 100%.
 */
export function compareCandidateEntries(
  leftEntry: CandidateEntry,
  rightEntry: CandidateEntry,
): number {
  const [leftSymbol, left] = leftEntry;
  const [rightSymbol, right] = rightEntry;
  const rankOrder = compareRanks(candidateRank(left), candidateRank(right));

  return rankOrder !== 0
    ? rankOrder
    : leftSymbol.localeCompare(rightSymbol);
}
