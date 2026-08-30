type Rec = Record<string, unknown>;

type DecisionCounts = {
  LATE?: unknown;
  INVALIDATED?: unknown;
  EXPIRED?: unknown;
  NO_TRADE?: unknown;
  UNAVAILABLE?: unknown;
};

type FreshnessState = "fresh" | "stale" | "unknown";
type FreshnessSummaryState = "fresh" | "mixed" | "stale" | "unknown";

function record(value: unknown): Rec {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Rec
    : {};
}

function finite(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function count(value: unknown): number {
  const parsed = finite(value);
  return parsed !== undefined && parsed >= 0 ? Math.trunc(parsed) : 0;
}

export function blockedOrOtherCount(counts: DecisionCounts): number {
  return count(counts.LATE)
    + count(counts.INVALIDATED)
    + count(counts.EXPIRED)
    + count(counts.NO_TRADE)
    + count(counts.UNAVAILABLE);
}

export function blockedOrOtherBreakdown(counts: DecisionCounts): string {
  const rows: Array<[string, number]> = [
    ["late", count(counts.LATE)],
    ["invalidated", count(counts.INVALIDATED)],
    ["expired", count(counts.EXPIRED)],
    ["no trade", count(counts.NO_TRADE)],
    ["unavailable", count(counts.UNAVAILABLE)],
  ];
  return rows.filter(([, value]) => value > 0).map(([label, value]) => `${value} ${label}`).join(" · ");
}

export function tradePlanAvailable(value: unknown): boolean {
  const plan = record(value);
  return ["entry_price", "stop_loss", "take_profit_1", "take_profit_2"]
    .every((key) => finite(plan[key]) !== undefined);
}

export function advisoryPresentation(value: unknown): {
  status: string;
  confidence?: number;
  reasoning: string;
} {
  const advisory = record(value);
  const status = typeof advisory.ai_advice === "string" && advisory.ai_advice
    ? advisory.ai_advice
    : "UNAVAILABLE";
  const reasoning = typeof advisory.ai_reasoning === "string" && advisory.ai_reasoning
    ? advisory.ai_reasoning
    : "No advisory available";
  const confidence = finite(advisory.ai_confidence);
  if (["PENDING", "UNAVAILABLE"].includes(status.toUpperCase()) || confidence === undefined) {
    return { status, reasoning };
  }
  return { status, confidence, reasoning };
}

export function candidateFreshness(value: unknown): {
  ageSeconds?: number;
  thresholdSeconds?: number;
  state: FreshnessState;
} {
  const candidate = record(value);
  const metrics = record(candidate.metrics);
  const decision = record(metrics.entry_decision);
  const policy = record(decision.policy);
  const ageSeconds = finite(candidate.analysis_age_seconds);
  const thresholdSeconds = finite(policy.max_analysis_age_seconds);
  if (ageSeconds === undefined || thresholdSeconds === undefined || thresholdSeconds <= 0) {
    return { ageSeconds, thresholdSeconds, state: "unknown" };
  }
  return {
    ageSeconds,
    thresholdSeconds,
    state: ageSeconds <= thresholdSeconds ? "fresh" : "stale",
  };
}

export function summarizeCandidateFreshness(candidates: Record<string, unknown>): {
  total: number;
  fresh: number;
  stale: number;
  unknown: number;
  state: FreshnessSummaryState;
} {
  let fresh = 0;
  let stale = 0;
  let unknown = 0;
  for (const candidate of Object.values(candidates)) {
    const state = candidateFreshness(candidate).state;
    if (state === "fresh") fresh += 1;
    else if (state === "stale") stale += 1;
    else unknown += 1;
  }
  const total = fresh + stale + unknown;
  let state: FreshnessSummaryState = "unknown";
  if (total > 0 && stale === 0 && unknown === 0) state = "fresh";
  else if (total > 0 && stale === total) state = "stale";
  else if (total > 0 && (fresh > 0 || stale > 0)) state = "mixed";
  return { total, fresh, stale, unknown, state };
}
