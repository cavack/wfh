"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, Clock3, FlaskConical, LayoutDashboard, Radio, ShieldCheck, Wifi, WifiOff } from "lucide-react";
import { MarketContext } from "@/components/market-context";
import { OutcomeEvidence } from "@/components/outcome-evidence";
import { Candidate, ScoreCard } from "@/components/score-card";
import { FinalRanking } from "@/components/final-ranking";
import { SignalFunnel, SignalFunnelData } from "@/components/signal-funnel";
import { HistoricalOutcomes } from "@/components/historical-outcomes";
import { ProductionEvidence } from "@/components/production-evidence";
import { FeatureReplay } from "@/components/feature-replay";
import { BacktestLab } from "@/components/backtest-lab";
import { LifecycleShadow } from "@/components/lifecycle-shadow";

import { DecisionTerminal } from "@/components/decision-terminal";
import { RecentSignals } from "@/components/recent-signals";

import type { DashboardSnapshot } from "@/generated/dashboard-contract";
import { dashboardSnapshot, dashboardStreamEvent } from "@/lib/dashboard-contract";
import { summarizeCandidateFreshness } from "@/lib/decision-terminal-ui";

type ConnectionMode = "stream" | "polling" | "reconnecting";

function connectionLabel(mode: ConnectionMode): string {
  if (mode === "stream") return "Live stream";
  if (mode === "polling") return "Polling fallback";
  return "Reconnecting…";
}

function boundedJitter(maximum: number): number {
  const sample = new Uint32Array(1);
  globalThis.crypto.getRandomValues(sample);
  return Math.floor((sample[0] / 0xffffffff) * maximum);
}

function StreamStatus({ mode }: Readonly<{ mode: ConnectionMode }>) {
  const connected = mode === "stream";
  const polling = mode === "polling";
  return (
    <span
      className={`status-pill border ${connected
        ? "border-emerald-400/25 bg-emerald-500/10 text-emerald-200"
        : polling
          ? "border-sky-400/25 bg-sky-500/10 text-sky-200"
          : "border-amber-400/25 bg-amber-500/10 text-amber-200"}`}
      role="status"
      aria-live="polite"
    >
      {connected ? <Wifi size={13} /> : <WifiOff size={13} />}
      {connectionLabel(mode)}
    </span>
  );
}

function DataFreshnessStatus({ summary }: Readonly<{ summary: ReturnType<typeof summarizeCandidateFreshness> }>) {
  let tone = "border-slate-700 bg-slate-900 text-slate-400";
  if (summary.state === "fresh") {
    tone = "border-emerald-400/25 bg-emerald-500/10 text-emerald-200";
  } else if (summary.state === "stale") {
    tone = "border-rose-400/30 bg-rose-500/10 text-rose-200";
  } else if (summary.state === "mixed") {
    tone = "border-amber-400/25 bg-amber-500/10 text-amber-200";
  }
  let label = "Freshness unknown";
  if (summary.state === "fresh") label = `Data fresh · ${summary.fresh}/${summary.total}`;
  else if (summary.state === "stale") label = `Candidate data stale · ${summary.stale}`;
  else if (summary.state === "mixed") {
    label = summary.stale > 0
      ? `${summary.stale} stale · ${summary.fresh} fresh`
      : `${summary.unknown} unknown · ${summary.fresh} fresh`;
  }
  return (
    <span
      className={`status-pill border ${tone}`}
      role="status"
      aria-live="polite"
      aria-label={label}
      title={label}
    >
      <Clock3 size={13} aria-hidden="true" />
      <span className="hidden sm:inline">{label}</span>
    </span>
  );
}

function CandidatePanel({ symbol, candidate, hasFreshSnapshot }: Readonly<{ symbol: string; candidate: Candidate; hasFreshSnapshot: boolean }>) {
  return (
    <article className="panel overflow-hidden">
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
  const [generatedAt, setGeneratedAt] = useState<number | null>(null);
  const [freshnessNow, setFreshnessNow] = useState<number | undefined>(undefined);
  const [researchOpen, setResearchOpen] = useState(false);
  const latestVersion = useRef(0);

  useEffect(() => {
    const refreshClock = () => setFreshnessNow(Date.now() / 1000);
    refreshClock();
    const timer = setInterval(refreshClock, 5_000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let active = true;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let pollAttempt = 0;
    let streaming = false;
    let hasSnapshot = false;
    const stream = new EventSource("/dashboard/api/stream");

    const acceptSnapshot = (snapshot: DashboardSnapshot) => {
      if (!active || snapshot.snapshot_version <= latestVersion.current) return;
      latestVersion.current = snapshot.snapshot_version;
      hasSnapshot = true;
      setData(snapshot);
      // The backend timestamp is authoritative for replays and delayed polls.
      setGeneratedAt(snapshot.generated_at * 1000);
    };

    const schedulePoll = (delay: number) => {
      if (!active || pollTimer !== undefined) return;
      const jitter = delay > 0 ? boundedJitter(Math.min(1_500, delay)) : 0;
      pollTimer = setTimeout(() => {
        pollTimer = undefined;
        if (!active) return;
        void (async () => {
          try {
            const response = await fetch("/dashboard/api/candidates", { cache: "no-store" });
            const snapshot = response.ok ? dashboardSnapshot(await response.json()) : undefined;
            if (!snapshot) throw new Error("invalid dashboard snapshot");
            acceptSnapshot(snapshot);
            pollAttempt = 0;
            if (streaming) return;
            setMode("polling");
            schedulePoll(5_000);
          } catch {
            pollAttempt += 1;
            if (!streaming) setMode("reconnecting");
            if (!streaming || !hasSnapshot) {
              schedulePoll(Math.min(30_000, 1_000 * (2 ** Math.min(pollAttempt, 5))));
            }
          }
        })();
      }, delay + jitter);
    };

    const handleStreamMessage = (event: MessageEvent<string>) => {
      try {
        const packet = dashboardStreamEvent(JSON.parse(event.data));
        if (!packet) throw new Error("invalid dashboard stream event");
        if (packet.payload) {
          acceptSnapshot(packet.payload);
          if (hasSnapshot && pollTimer !== undefined) {
            clearTimeout(pollTimer);
            pollTimer = undefined;
          }
        }
        streaming = true;
        setMode("stream");
      } catch {
        streaming = false;
        setMode("reconnecting");
        schedulePoll(1_000);
      }
    };

    const handleNamedStreamEvent = (event: Event) => {
      if (event instanceof MessageEvent) {
        handleStreamMessage(event as MessageEvent<string>);
      }
    };

    stream.onopen = () => {
      streaming = true;
      if (hasSnapshot && pollTimer !== undefined) {
        clearTimeout(pollTimer);
        pollTimer = undefined;
      }
      pollAttempt = 0;
      setMode("stream");
    };
    stream.onerror = () => {
      streaming = false;
      setMode("reconnecting");
      schedulePoll(1_000);
    };
    stream.onmessage = handleStreamMessage;
    stream.addEventListener("snapshot", handleNamedStreamEvent);
    stream.addEventListener("heartbeat", handleNamedStreamEvent);

    // Bootstrap from the schema-validated polling endpoint even when the SSE
    // socket opens first. This prevents an open heartbeat-only stream from
    // suppressing the initial READY snapshot forever.
    schedulePoll(0);

    return () => {
      active = false;
      stream.removeEventListener("snapshot", handleNamedStreamEvent);
      stream.removeEventListener("heartbeat", handleNamedStreamEvent);
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

  const freshnessSummary = useMemo(
    () => summarizeCandidateFreshness((data?.candidates ?? {}) as Record<string, unknown>, freshnessNow),
    [data, freshnessNow],
  );

  const groups = useMemo(() => {
    const strictConfirmed = rows.filter(([, candidate]) => candidate.signal_class === "STRICT" && candidate.status === "TRIGGERED");
    const experimental = rows.filter(([, candidate]) => candidate.signal_class === "EXPERIMENTAL");
    const setupPipeline = rows.filter(([, candidate]) => candidate.signal_class !== "EXPERIMENTAL" && ["FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status)));
    const discovery = rows.filter(([, candidate]) => candidate.signal_class !== "EXPERIMENTAL" && candidate.status !== "TRIGGERED" && !["FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status)));
    return { strictConfirmed, experimental, setupPipeline, discovery };
  }, [rows]);

  const renderGroup = (title: string, items: [string, Candidate][], tone: "slate" | "experimental" = "slate") => items.length > 0 && (
    <section className="mb-6">
      <h3 className={`mb-3 text-sm font-semibold uppercase tracking-wide ${tone === "experimental" ? "text-violet-300" : "text-slate-300"}`}>{title}</h3>
      <div className={`grid gap-4 xl:grid-cols-2 ${tone === "experimental" ? "rounded-2xl border border-violet-500/25 bg-violet-950/10 p-3 sm:p-4" : ""}`}>
        {items.map(([symbol, candidate]) => <CandidatePanel key={symbol} symbol={symbol} candidate={candidate} hasFreshSnapshot={data !== null} />)}
      </div>
    </section>
  );

  let emptyState: ReactNode = null;
  if (data === null) {
    emptyState = (
      <div className="panel mx-auto max-w-7xl px-6 py-16 text-center">
        <span className="live-dot mx-auto block" aria-hidden="true" />
        <p className="mt-4 text-lg font-medium">Initializing live state…</p>
        <p className="mt-2 text-sm text-slate-400">Waiting for a schema-valid stream snapshot or polling fallback.</p>
      </div>
    );
  } else if (rows.length === 0) {
    emptyState = (
      <div className="panel mx-auto max-w-7xl px-6 py-16 text-center">
        <p className="text-lg font-medium">No active candidates in the latest valid snapshot</p>
        <p className="mt-2 text-sm text-slate-400">The decision terminal is live; there is simply nothing to evaluate yet.</p>
      </div>
    );
  }



  return (
    <main className="min-h-dvh pb-14 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/85 backdrop-blur supports-[backdrop-filter]:bg-slate-950/70">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:h-16 sm:px-6 lg:px-8">
          <Activity className="shrink-0 text-emerald-400" size={24} aria-hidden="true" />
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-base font-bold tracking-tight sm:text-lg">WaterfallHunter</h1>

            <p className="hidden text-xs text-slate-400 sm:block">Canonical waterfall decision terminal · signal only</p>

          </div>
          <div className="ml-auto flex items-center gap-2">
            {generatedAt !== null && (
              <time dateTime={new Date(generatedAt).toISOString()} className="hidden font-mono text-xs text-slate-500 md:inline">
                updated {new Date(generatedAt).toLocaleTimeString()}
              </time>
            )}
            <DataFreshnessStatus summary={freshnessSummary} />
            <StreamStatus mode={mode} />
          </div>
        </div>
        <nav aria-label="Dashboard sections" className="border-t border-slate-800/60">
          <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 py-1.5 sm:px-6 lg:px-8">

            <a href="#decision-terminal" className="section-nav-link"><LayoutDashboard size={14} />Decision terminal</a>
            <a href="#all-candidates" className="section-nav-link"><Radio size={14} />All candidates</a>
            <a href="#research" className="section-nav-link"><FlaskConical size={14} />Research</a>
            <span className="ml-auto hidden shrink-0 self-center pr-1 font-mono text-[11px] font-semibold tracking-wider text-emerald-300/90 md:inline">SIGNAL_ONLY · LIVE TRADING OFF · NO ORDER EXECUTION</span>

          </div>
        </nav>
      </header>

      <div className="px-4 pt-5 sm:px-6 lg:px-8">
        {emptyState}
        {data !== null ? (
          <DecisionTerminal terminal={data.decision_terminal} candidates={data.candidates as Record<string, Candidate>} nowSeconds={freshnessNow} />
        ) : null}

        <details id="research" onToggle={(event) => setResearchOpen(event.currentTarget.open)} className="panel mx-auto mt-8 max-w-7xl scroll-mt-32 overflow-hidden">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-4 text-sm font-semibold text-slate-200">
            <span className="flex items-center gap-2"><ShieldCheck size={16} className="text-slate-400" />Research, validation & raw diagnostics</span>
            <span className="text-xs font-normal text-slate-500">Secondary · never an entry command</span>
          </summary>
          {researchOpen ? (
            <div className="border-t border-slate-800 px-4 py-5 sm:px-5">
              <OutcomeEvidence />
              <RecentSignals />
              <HistoricalOutcomes />
              <ProductionEvidence />
              <FeatureReplay />
              <LifecycleShadow />
              <BacktestLab />
              <SignalFunnel funnel={data?.signal_funnel as SignalFunnelData | undefined} />
              <FinalRanking ranking={data?.final_ranking} />
              <details className="mt-6 rounded-xl border border-slate-800 bg-slate-950/30 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-300">Raw candidate cards</summary>
                <div className="mt-5">
                  {renderGroup("Confirmed STRICT diagnostics", groups.strictConfirmed)}
                  {renderGroup("STRICT setup diagnostics", groups.setupPipeline)}
                  {renderGroup("Experimental research", groups.experimental, "experimental")}
                  {renderGroup("Watch and discovery", groups.discovery)}
                </div>
              </details>
            </div>
          ) : null}
        </details>

      </div>
    </main>
  );
}
