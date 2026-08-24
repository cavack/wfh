import assert from "node:assert/strict";
import test from "node:test";

import {
  compareCandidateEntries,
  shouldAcceptDashboardSnapshot,
} from "./dashboard-state.ts";

test("accepts a newer payload generated at the same snapshot version", () => {
  const current = { snapshot_version: 1, generated_at: 100 };
  const incoming = { snapshot_version: 1, generated_at: 101 };

  assert.equal(shouldAcceptDashboardSnapshot(current, incoming), true);
});

test("rejects an older payload at the same snapshot version", () => {
  const current = { snapshot_version: 1, generated_at: 101 };
  const incoming = { snapshot_version: 1, generated_at: 100 };

  assert.equal(shouldAcceptDashboardSnapshot(current, incoming), false);
});

test("a higher snapshot version wins even if its generated_at is lower", () => {
  const current = { snapshot_version: 1, generated_at: 200 };
  const incoming = { snapshot_version: 2, generated_at: 150 };

  assert.equal(shouldAcceptDashboardSnapshot(current, incoming), true);
});

test("watch-score ordering uses normalized score multiplied by evidence coverage", () => {
  const lowerEffectiveScore = {
    metrics: {
      watch_score: {
        score: 100,
        coverage_pct: 30,
      },
    },
  };
  const higherEffectiveScore = {
    metrics: {
      watch_score: {
        score: 70,
        coverage_pct: 95,
      },
    },
  };

  assert.ok(
    compareCandidateEntries(
      ["LOW_EFFECTIVE", lowerEffectiveScore],
      ["HIGH_EFFECTIVE", higherEffectiveScore],
    ) > 0,
  );
});

test("partial candidate.score cannot bypass watch evidence coverage", () => {
  const sparseObservation = {
    score: 100,
    metrics: {
      score_version: "score_v2",
      trade_eligible: false,
      watch_score: {
        score: 100,
        coverage_pct: 30,
      },
    },
  };
  const betterObserved = {
    score: 70,
    metrics: {
      score_version: "score_v2",
      trade_eligible: false,
      watch_score: {
        score: 70,
        coverage_pct: 95,
      },
    },
  };

  assert.ok(
    compareCandidateEntries(
      ["SPARSE", sparseObservation],
      ["BETTER_OBSERVED", betterObserved],
    ) > 0,
  );
});

test("effective watch score may outrank fuller coverage when signal evidence is much stronger", () => {
  const strongAtNinetyPercent = {
    metrics: {
      watch_score: {
        score: 100,
        coverage_pct: 90,
      },
    },
  };
  const weakerAtFullCoverage = {
    metrics: {
      watch_score: {
        score: 70,
        coverage_pct: 100,
      },
    },
  };

  assert.ok(
    compareCandidateEntries(
      ["STRONG", strongAtNinetyPercent],
      ["FULL", weakerAtFullCoverage],
    ) < 0,
  );
});

test("watch-score ordering uses raw score when evidence coverage is equal", () => {
  const lowerScore = {
    metrics: {
      watch_score: {
        score: 60,
        coverage_pct: 85,
      },
    },
  };
  const higherScore = {
    metrics: {
      watch_score: {
        score: 75,
        coverage_pct: 85,
      },
    },
  };

  assert.ok(
    compareCandidateEntries(
      ["LOW", lowerScore],
      ["HIGH", higherScore],
    ) > 0,
  );
});

test("known watch coverage sorts ahead of unknown coverage", () => {
  const unknownCoverage = {
    metrics: {
      watch_score: {
        score: 99,
      },
    },
  };
  const knownCoverage = {
    metrics: {
      watch_score: {
        score: 50,
        coverage_pct: 40,
      },
    },
  };

  assert.ok(
    compareCandidateEntries(
      ["UNKNOWN", unknownCoverage],
      ["KNOWN", knownCoverage],
    ) > 0,
  );
});
