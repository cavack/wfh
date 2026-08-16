"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Wifi, WifiOff } from "lucide-react";
import { MarketContext } from "@/components/market-context";
import { OutcomeEvidence } from "@/components/outcome-evidence";
import { Candidate, ScoreCard } from "@/components/score-card";
import { FinalRanking } from "@/components/final-ranking";
import { SignalFunnel, SignalFunnelData } from "@/components/signal-funnel";
import { HistoricalOutcomes } from "@/components/historical-outcomes";
import { ProductionEvidence } from "@/components/production-evidence";
import { FeatureReplay } from "@/components/feature-replay";

type DashboardData = {
  total: number;
  candidates: Record<string, Candidate>;
  final_ranking?: {
    version?: string;
    observational_only?: boolean;
    top?: unknown[];
  };
  signal_funnel?: SignalFunnelData;
};

const initialData: DashboardData = { total: 0, candidates: {} };

function StreamStatus({ connected }: { connected: boolean }) {
  return (
    <div className="ml-auto flex items-center gap-2 text-sm text-slate-300">
      {connected ? <Wifi size={16} className="text-emerald-400" /> : <WifiOff size={16} className="text-amber-400" />}
      {connected ? "Live stream" : "Reconnecting…"}
    </div>
  );
}

function CandidatePanel({ symbol, candidate, hasFreshSnapshot }: { symbol: string; candidate: Candidate; hasFreshSnapshot: boolean }) {
  return (
    <article className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 shadow-lg shadow-slate-950/30">
      <ScoreCard symbol={symbol} candidate={candidate} hasFreshSnapshot={hasFreshSnapshot} />
      <MarketContext candidate={candidate} hasFreshSnapshot={hasFreshSnapshot} />
    </article>
  );
}

function candidateRank(candidate: Candidate): number | undefined {
  const metrics = candidate.metrics;
  const primary = typeof candidate.score === "number" && Number.isFinite(candidate.score)
    && metrics !== null && typeof metrics === "object" && !Array.isArray(metrics)
    && (metrics as Record<string, unknown>).score_version === "score_v2"
    ? candidate.score
    : undefined;
  if (primary !== undefined) return primary;
  if (metrics !== null && typeof metrics === "object" && !Array.isArray(metrics)) {
    const watch = (metrics as Record<string, unknown>).watch_score;
    if (watch !== null && typeof watch === "object" && !Array.isArray(watch)) {
      const score = (watch as Record<string, unknown>).score;
      if (typeof score === "number" && Number.isFinite(score)) return score;
    }
  }
  return undefined;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData>(initialData);
  const [connected, setConnected] = useState(false);
  const [hasFreshSnapshot, setHasFreshSnapshot] = useState(false);

  useEffect(() => {
    const stream = new EventSource("/dashboard/api/stream");
    stream.onopen = () => setConnected(true);
    stream.onerror = () => {
      setConnected(false);
      setHasFreshSnapshot(false);
      setData(initialData);
    };
    stream.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as DashboardData;
        if (typeof payload.total === "number" && payload.candidates && typeof payload.candidates === "object") {
          setData(payload);
          setConnected(true);
          setHasFreshSnapshot(true);
        }
      } catch {
        setConnected(false);
        setHasFreshSnapshot(false);
        setData(initialData);
      }
    };
    return () => stream.close();
  }, []);

  const rows = useMemo(
    () => Object.entries(data.candidates).sort(([leftSymbol, left], [rightSymbol, right]) => {
      const leftRank = candidateRank(left);
      const rightRank = candidateRank(right);
      if (leftRank !== undefined && rightRank !== undefined && leftRank !== rightRank) return rightRank - leftRank;
      if (leftRank !== undefined) return -1;
      if (rightRank !== undefined) return 1;
      return leftSymbol.localeCompare(rightSymbol);
    }),
    [data.candidates],
  );

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100 sm:px-6 lg:px-10">
      <header className="mx-auto mb-8 flex max-w-7xl items-center gap-3 border-b border-slate-800 pb-5">
        <Activity className="text-emerald-400" size={30} />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">WaterfallHunter</h1>
          <p className="text-sm text-slate-400">USDT perpetual futures monitoring terminal</p>
        </div>
        <StreamStatus connected={connected} />
      </header>

      <section className="mx-auto mb-7 grid max-w-7xl gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Tracked candidates</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{data.total}</p>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 md:col-span-2">
          <p className="text-sm text-slate-400">Live-data policy</p>
          <p className="mt-1 text-sm text-slate-200">Only current exchange evidence is shown. Missing analysis remains unavailable; it is never converted into a score.</p>
        </div>
      </section>

      <OutcomeEvidence />

      <HistoricalOutcomes />

      <ProductionEvidence />

      <FeatureReplay />

      <SignalFunnel funnel={data.signal_funnel} />

      <FinalRanking ranking={data.final_ranking} />

      <section className="mx-auto max-w-7xl">
        {rows.length > 0 && <p className="mb-3 text-xs text-slate-500">All candidates remain ordered by the existing Score V2/watch score view. The Top 3 panel is a separate observational ranking and does not alter state or eligibility.</p>}
        {rows.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 py-24 text-center">
            <p className="text-lg font-medium">No active candidates yet</p>
            <p className="mt-2 text-sm text-slate-400">The dashboard will populate after the live catalog and analysis pipeline return eligible data.</p>
          </div>
        ) : (
          <div className="grid gap-5 xl:grid-cols-2">
            {rows.map(([symbol, candidate]) => <CandidatePanel key={symbol} symbol={symbol} candidate={candidate} hasFreshSnapshot={hasFreshSnapshot} />)}
          </div>
        )}
      </section>
    </main>
  );
}
