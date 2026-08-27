import assert from "node:assert/strict";
import test from "node:test";

import { canonicalRankBySymbol, compareByCanonicalRank } from "./candidate-order.ts";

test("candidate ordering follows the canonical backend rank packet", () => {
  const rankBySymbol = canonicalRankBySymbol({
    all: [
      { symbol: "B_USDT", rank: 1, score: 45.0 },
      { symbol: "A_USDT", rank: 2, score: 90.0 },
    ],
  });

  const symbols = ["A_USDT", "B_USDT"].sort((left, right) =>
    compareByCanonicalRank(left, right, rankBySymbol),
  );

  assert.deepEqual(symbols, ["B_USDT", "A_USDT"]);
});

test("malformed ranking rows are unavailable rather than re-derived in frontend", () => {
  const rankBySymbol = canonicalRankBySymbol({
    all: [
      { symbol: "A_USDT", score: 99 },
      { symbol: "B_USDT", rank: 0 },
      { symbol: 123, rank: 1 },
    ],
  });

  assert.equal(rankBySymbol.size, 0);
  assert.equal(compareByCanonicalRank("B_USDT", "A_USDT", rankBySymbol), 1);
});
