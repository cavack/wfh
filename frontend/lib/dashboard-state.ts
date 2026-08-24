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
 * bootstrap race; a lower version can never replace a higher one.
 */
export function shouldAcceptDashboardSnapshot(
  current: SnapshotIdentity | null,
  incoming: SnapshotIdentity,
): boolean {
  if (current === null) {
    return true;
  }

  if (incoming.snapshot_version !== current.snapshot_version) {
    return incoming.snapshot_version > current.snapshot_version;
  }

  return incoming.generated_at > current.generated_at;
}

function candidateRank(candidate: CandidateLike): CandidateRank | undefined {
  const metrics = asRecord(candidate.metrics);
  const primaryScore = finiteNumber(candidate.score);

  if (primaryScore !== undefined && metrics?.score_version === "score_v2") {
    return {
      source: "primary",
      score: primaryScore,
      coverage: undefined,
    };
  }

  const watch = asRecord(metrics?.watch_score);
  const watchScore = finiteNumber(watch?.score);

  if (watchScore === undefined) {
    return undefined;
  }

  return {
    source: "watch",
    score: watchScore,
    coverage: finiteNumber(watch?.coverage_pct),
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

function compareWatchCoverage(left: CandidateRank, right: CandidateRank): number {
  if (left.source !== "watch" || right.source !== "watch") {
    return 0;
  }

  const presenceOrder = comparePresence(left.coverage, right.coverage);
  if (presenceOrder !== 0) {
    return presenceOrder;
  }

  if (left.coverage === undefined || right.coverage === undefined) {
    return 0;
  }

  return right.coverage - left.coverage;
}

function compareRanks(
  left: CandidateRank | undefined,
  right: CandidateRank | undefined,
): number {
  const presenceOrder = comparePresence(left, right);
  if (presenceOrder !== 0 || left === undefined || right === undefined) {
    return presenceOrder;
  }

  const coverageOrder = compareWatchCoverage(left, right);
  if (coverageOrder !== 0) {
    return coverageOrder;
  }

  return right.score - left.score;
}

/**
 * Preserve the existing Score V2 / Watch Score ordering while preventing a
 * low-coverage Watch Score from outranking a better-observed Watch Score only
 * because missing evidence was redistributed by score_v2_watch_v1.
 *
 * Coverage is an ordering dimension, not a replacement score: unknown or
 * missing evidence is never converted to zero points.
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
