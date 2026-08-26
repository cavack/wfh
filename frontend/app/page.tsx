"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Activity, FlaskConical, GitBranch, LayoutDashboard, Radio, ShieldCheck, Wifi, WifiOff } from "lucide-react";
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
import type { DashboardSnapshot } from "@/generated/dashboard-contract";
import { dashboardSnapshot, dashboardStreamEvent } from "@/lib/dashboard-contract";

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
  const latestVersion = useRef(0);

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
      setGeneratedAt(Date.now());
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

  const groups = useMemo(() => ({
    strictConfirmed: rows.filter(([, candidate]) => candidate.signal_class === "STRICT" && candidate.status === "TRIGGERED"),
    strictSetup: rows.filter(([, candidate]) => candidate.signal_class === "STRICT" && ["FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status))),
    experimental: rows.filter(([, candidate]) => candidate.signal_class === "EXPERIMENTAL"),
    discovery: rows.filter(([, candidate]) => candidate.signal_class !== "EXPERIMENTAL" && !(candidate.signal_class === "STRICT" && ["TRIGGERED", "FUEL-RICH", "PRE-TRIGGER", "ARMED"].includes(String(candidate.status)))),
  }), [rows]);

  const renderGroup = (title: string, items: [string, Candidate][], tone: "slate" | "experimental" = "slate") => items.length > 0 && (
    <section className={`mx-auto mb-8 max-w-7xl scroll-mt-28 px-4 sm:px-6 lg:px-8 ${tone === "experimental" ? "" : ""}`}>
      <h2 className={`mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide ${tone === "experimental" ? "text-violet-300" : "text-slate-300"}`}>{title}</h2>
      <div className={`grid gap-4 xl:grid-cols-2 ${tone === "experimental" ? "rounded-2xl border border-violet-500/25 bg-violet-950/10 p-3 sm:p-4" : ""}`}>
        {items.map(([symbol, candidate]) => <CandidatePanel key={symbol} symbol={symbol} candidate={candidate} hasFreshSnapshot={data !== null} />)}
      </div>
    </section>
  );

  let emptyState: ReactNode = null;
  if (data === null) {
    emptyState = (
      <div className="panel mx-auto max-w-7xl px-6 py-16 text-center sm:mx-6 lg:mx-auto">
        <span className="live-dot mx-auto block" aria-hidden="true" />
        <p className="mt-4 text-lg font-medium">Initializing live state…</p>
        <p className="mt-2 text-sm text-slate-400">Waiting for a schema-valid stream snapshot or polling fallback.</p>
      </div>
    );
  } else if (rows.length === 0) {
    emptyState = (
      <div className="panel mx-auto max-w-7xl px-6 py-16 text-center sm:mx-6 lg:mx-auto">
        <p className="text-lg font-medium">No active candidates in the latest valid snapshot</p>
        <p className="mt-2 text-sm text-slate-400">This is a real READY snapshot, not an initializing placeholder.</p>
      </div>
    );
  }

  const kpis = [
    { label: "Tracked candidates", value: data?.total ?? undefined },
    { label: "STRICT confirmed", value: groups.strictConfirmed.length, tone: "text-emerald-300" as const },
    { label: "Armed / pre-trigger", value: groups.strictSetup.length, tone: "text-amber-300" as const },
    { label: "Experimental research", value: groups.experimental.length, tone: "text-violet-300" as const },
  ];

  return (
    <main className="min-h-dvh pb-14 text-slate-100">
      {/* ---------------------------------------------------------------- */}
      {/* Sticky header: brand + connection state always reachable         */}
      {/* ---------------------------------------------------------------- */}
      <header className="sticky top-0 z-40 border-b border-slate-800/80 bg-slate-950/85 backdrop-blur supports-[backdrop-filter]:bg-slate-950/70">
        <div className="mx-auto flex h-14 max-w-7xl items-center gap-3 px-4 sm:h-16 sm:px-6 lg:px-8">
          <Activity className="shrink-0 text-emerald-400" size={24} aria-hidden="true" />
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-base font-bold tracking-tight sm:text-lg">WaterfallHunter</h1>
            <p className="hidden text-xs text-slate-400 sm:block">Evidence-first paper research terminal · no live orders</p>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {generatedAt !== null && (
              <time dateTime={new Date(generatedAt).toISOString()} className="hidden font-mono text-xs text-slate-500 md:inline">
                updated {new Date(generatedAt).toLocaleTimeString()}
              </time>
            )}
            <StreamStatus mode={mode} />
          </div>
        </div>

        {/* Section navigation — horizontally scrollable on phones */}
        <nav aria-label="Dashboard sections" className="border-t border-slate-800/60">
          <div className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-3 py-1.5 sm:px-6 lg:px-8">
            <a href="#overview" className="section-nav-link"><LayoutDashboard size={14} />Overview</a>
            <a href="#evidence" className="section-nav-link"><ShieldCheck size={14} />Evidence</a>
            <a href="#lifecycle-shadow" className="section-nav-link"><GitBranch size={14} />Lifecycle shadow</a>
            <a href="#backtest-lab" className="section-nav-link"><FlaskConical size={14} />Backtest Lab</a>
            <a href="#live-candidates" className="section-nav-link"><Radio size={14} />Candidates</a>
            <span className="ml-auto hidden shrink-0 self-center pr-1 font-mono text-[11px] font-semibold tracking-wider text-emerald-300/90 md:inline" title="Project invariant: this system never places orders">PAPER ONLY · LIVE TRADING OFF</span>
          </div>
        </nav>
      </header>

      <div className="px-4 pt-5 sm:px-6 lg:px-8">
        {/* -------------------------------------------------------------- */}
        {/* Overview KPIs                                                  */}
        {/* -------------------------------------------------------------- */}
        <section id="overview" className="mx-auto mb-7 max-w-7xl scroll-mt-32">
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {kpis.map((kpi) => (
              <div key={kpi.label} className="panel px-4 py-3.5">
                <dt className="text-xs font-medium text-slate-400">{kpi.label}</dt>
                <dd className={`mt-1 text-2xl font-semibold tabular-nums sm:text-3xl ${kpi.tone ?? "text-slate-50"}`}>
                  {kpi.value === undefined ? "—" : kpi.value.toLocaleString()}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 flex items-start gap-2 rounded-xl border border-slate-800/80 bg-slate-900/40 px-3.5 py-2.5 text-xs leading-5 text-slate-400">
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-emerald-400/80" />
            Only current exchange evidence is shown. Missing analysis stays unavailable — it is never converted into a score, and nothing here places orders.
          </p>
        </section>

        {/* -------------------------------------------------------------- */}
        {/* Evidence & research sections                                   */}
        {/* -------------------------------------------------------------- */}
        <div id="evidence" className="scroll-mt-32"><OutcomeEvidence /></div>

        <HistoricalOutcomes />

        <ProductionEvidence />

        <FeatureReplay />

        <LifecycleShadow />

        <BacktestLab />

        <SignalFunnel funnel={data?.signal_funnel as SignalFunnelData | undefined} />

        <FinalRanking ranking={data?.final_ranking} />

        <section id="live-candidates" className="mx-auto mb-5 max-w-7xl scroll-mt-32">
          {rows.length > 0 && <p className="mb-3 text-xs text-slate-500">All candidates remain ordered by the existing Score V2/watch score view. The Top 3 panel is a separate observational ranking and does not alter state or eligibility.</p>}
          {emptyState}
        </section>

        {renderGroup("Confirmed STRICT signals", groups.strictConfirmed)}
        {renderGroup("STRICT armed and pre-trigger setups", groups.strictSetup)}
        {renderGroup("Experimental research — never mixed with STRICT", groups.experimental, "experimental")}
        {renderGroup("Watch and discovery", groups.discovery)}
      </div>
    </main>
  );
}
