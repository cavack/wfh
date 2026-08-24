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
  const leftRank = candidateRank(left);
  const rightRank = candidateRank(right);

  if (leftRank !== undefined && rightRank !== undefined) {
    if (leftRank.source === "watch" && rightRank.source === "watch") {
      const leftCoverage = leftRank.coverage;
      const rightCoverage = rightRank.coverage;

      if (leftCoverage !== undefined && rightCoverage === undefined) {
        return -1;
      }

      if (leftCoverage === undefined && rightCoverage !== undefined) {
        return 1;
      }

      if (
        leftCoverage !== undefined
        && rightCoverage !== undefined
        && leftCoverage !== rightCoverage
      ) {
        return rightCoverage - leftCoverage;
      }
    }

    if (leftRank.score !== rightRank.score) {
      return rightRank.score - leftRank.score;
    }
  }

  if (leftRank !== undefined && rightRank === undefined) {
    return -1;
  }

  if (leftRank === undefined && rightRank !== undefined) {
    return 1;
  }

  return leftSymbol.localeCompare(rightSymbol);
}
