type JsonRecord = Record<string, unknown>;

function asRecord(value: unknown): JsonRecord | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonRecord
    : undefined;
}

/**
 * Read the canonical backend ranking without reproducing ScoreV2/Watch Score
 * semantics in the browser. Invalid or missing packets simply remain unranked.
 */
export function canonicalRankBySymbol(ranking: unknown): ReadonlyMap<string, number> {
  const packet = asRecord(ranking);
  const rows = Array.isArray(packet?.all) ? packet.all : [];
  const result = new Map<string, number>();

  for (const row of rows) {
    const item = asRecord(row);
    const symbol = typeof item?.symbol === "string" ? item.symbol : undefined;
    const rank = typeof item?.rank === "number" && Number.isInteger(item.rank) && item.rank > 0
      ? item.rank
      : undefined;
    if (symbol !== undefined && rank !== undefined && !result.has(symbol)) {
      result.set(symbol, rank);
    }
  }

  return result;
}

export function compareByCanonicalRank(
  leftSymbol: string,
  rightSymbol: string,
  rankBySymbol: ReadonlyMap<string, number>,
): number {
  const leftRank = rankBySymbol.get(leftSymbol);
  const rightRank = rankBySymbol.get(rightSymbol);

  if (leftRank !== undefined && rightRank !== undefined && leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  if (leftRank !== undefined) return -1;
  if (rightRank !== undefined) return 1;
  return leftSymbol.localeCompare(rightSymbol);
}
