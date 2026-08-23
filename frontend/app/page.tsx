"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, Wifi, WifiOff } from "lucide-react";
import { MarketContext } from "@/components/market-context";
import { OutcomeEvidence } from "@/components/outcome-evidence";
import { Candidate, ScoreCard } from "@/components/score-card";
import { FinalRanking } from "@/components/final-ranking";
import { SignalFunnel, SignalFunnelData } from "@/components/signal-funnel";
import { HistoricalOutcomes } from "@/components/historical-outcomes";
import { ProductionEvidence } from "@/components/production-evidence";
import { FeatureReplay } from "@/components/feature-replay";
import type { DashboardSnapshot } from "@/generated/dashboard-contract";
import { dashboardSnapshot, dashboardStreamEvent } from "@/lib/dashboard-contract";

type ConnectionMode = "stream" | "polling" | "reconnecting";

function StreamStatus({ mode }: { mode: ConnectionMode }) {
  const connected = mode === "stream";
  return (
    <div className="ml-auto flex items-center gap-2 text-sm text-slate-300">
      {connected ? <Wifi size={16} className="text-emerald-400" /> : <WifiOff size={16} className="text-amber-400" />}
      {mode === "stream" ? "Live stream" : mode === "polling" ? "Polling fallback" : "Reconnecting…"}
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
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [mode, setMode] = useState<ConnectionMode>("reconnecting");
  const latestVersion = useRef(0);

  useEffect(() => {
    let active = true;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let pollAttempt = 0;
    const stream = new EventSource("/dashboard/api/stream");

    const acceptSnapshot = (snapshot: DashboardSnapshot) => {
      if (!active || snapshot.snapshot_version <= latestVersion.current) return;
      latestVersion.current = snapshot.snapshot_version;
      setData(snapshot);
    };

    const schedulePoll = (delay: number) => {
      if (!active || pollTimer !== undefined) return;
      const jitter = Math.floor(Math.random() * Math.max(250, delay * 0.2));
      pollTimer = setTimeout(async () => {
        pollTimer = undefined;
        try {
          const response = await fetch("/dashboard/api/candidates", { cache: "no-store" });
          const snapshot = response.ok ? dashboardSnapshot(await response.json()) : undefined;
          if (!snapshot) throw new Error("invalid dashboard snapshot");
          acceptSnapshot(snapshot);
          pollAttempt = 0;
          setMode("polling");
          schedulePoll(5_000);
        } catch {
          pollAttempt += 1;
          setMode("reconnecting");
          schedulePoll(Math.min(30_000, 1_000 * (2 ** Math.min(pollAttempt, 5))));
        }
      }, delay + jitter);
    };

    stream.onopen = () => {
      if (pollTimer !== undefined) clearTimeout(pollTimer);
      pollTimer = undefined;
      pollAttempt = 0;
      setMode("stream");
    };
    stream.onerror = () => {
      setMode("reconnecting");
      schedulePoll(1_000);
    };
    stream.onmessage = (event) => {
      try {
        const packet = dashboardStreamEvent(JSON.parse(event.data));
        if (!packet) throw new Error("invalid dashboard stream event");
        if (packet.payload) acceptSnapshot(packet.payload);
        setMode("stream");
      } catch {
        setMode("reconnecting");
        schedulePoll(1_000);
      }
    };
    return () => {
      active = false;
      stream.close();
      if (pollTimer !== undefined) clearTimeout(pollTimer);
    };
  }, []);

  const rows = useMemo(
    () => Object.entries(data?.candidates ?? {}).sort(([leftSymbol, left], [rightSymbol, right]) => {
      const leftRank = candidateRank(left);
      const rightRank = candidateRank(right);
      if (leftRank !== undefined && rightRank !== undefined && leftRank !== rightRank) return rightRank - leftRank;
      if (leftRank !== undefined) return -1;
      if (rightRank !== undefined) return 1;
      return leftSymbol.localeCompare(rightSymbol);
    }),
    [data],
  );

  const groups = useMemo(() => ({
    strictConfirmed: rows.filter(([, candidate]) => candidate.signal_class === "STRICT" && candidate.status === "TRIGGERED"),
    strictSetup: rows.filter(([, candidate]) => candidate.signal_class === "STRICT" && ["FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status))),
    experimental: rows.filter(([, candidate]) => candidate.signal_class === "EXPERIMENTAL"),
    discovery: rows.filter(([, candidate]) => candidate.signal_class !== "EXPERIMENTAL" && !(candidate.signal_class === "STRICT" && ["TRIGGERED", "FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status)))),
  }), [rows]);

  const renderGroup = (title: string, items: [string, Candidate][], tone = "slate") => items.length > 0 && (
    <section className="mx-auto mb-8 max-w-7xl">
      <h2 className={`mb-3 text-sm font-semibold uppercase tracking-wide ${tone === "experimental" ? "text-violet-300" : "text-slate-300"}`}>{title}</h2>
      <div className={`grid gap-5 xl:grid-cols-2 ${tone === "experimental" ? "rounded-2xl border border-violet-500/25 bg-violet-950/10 p-4" : ""}`}>
        {items.map(([symbol, candidate]) => <CandidatePanel key={symbol} symbol={symbol} candidate={candidate} hasFreshSnapshot={data !== null} />)}
      </div>
    </section>
  );

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100 sm:px-6 lg:px-10">
      <header className="mx-auto mb-8 flex max-w-7xl items-center gap-3 border-b border-slate-800 pb-5">
        <Activity className="text-emerald-400" size={30} />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">WaterfallHunter</h1>
          <p className="text-sm text-slate-400">USDT perpetual futures monitoring terminal</p>
        </div>
        <StreamStatus mode={mode} />
      </header>

      <section className="mx-auto mb-7 grid max-w-7xl gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Tracked candidates</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{data?.total ?? "—"}</p>
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

      <SignalFunnel funnel={data?.signal_funnel as SignalFunnelData | undefined} />

      <FinalRanking ranking={data?.final_ranking} />

      <section className="mx-auto mb-5 max-w-7xl">
        {rows.length > 0 && <p className="mb-3 text-xs text-slate-500">All candidates remain ordered by the existing Score V2/watch score view. The Top 3 panel is a separate observational ranking and does not alter state or eligibility.</p>}
        {data === null ? (
          <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 py-24 text-center">
            <p className="text-lg font-medium">Initializing live state…</p>
            <p className="mt-2 text-sm text-slate-400">Waiting for a schema-valid stream snapshot or polling fallback.</p>
          </div>
        ) : rows.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 py-24 text-center">
            <p className="text-lg font-medium">No active candidates in the latest valid snapshot</p>
            <p className="mt-2 text-sm text-slate-400">This is a real READY snapshot, not an initializing placeholder.</p>
          </div>
        ) : null}
      </section>

      {renderGroup("Confirmed STRICT signals", groups.strictConfirmed)}
      {renderGroup("STRICT armed and pre-trigger setups", groups.strictSetup)}
      {renderGroup("Experimental research — never mixed with STRICT", groups.experimental, "experimental")}
      {renderGroup("Watch and discovery", groups.discovery)}
    </main>
  );
}
