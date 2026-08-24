"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  FlaskConical,
  GitBranch,
  LayoutDashboard,
  Loader2,
  Radio,
  ShieldCheck,
  Wifi,
  WifiOff,
} from "lucide-react";
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
import {
  compareCandidateEntries,
  shouldAcceptDashboardSnapshot,
  type SnapshotIdentity,
} from "@/lib/dashboard-state";

type ConnectionMode = "stream" | "polling" | "reconnecting";

const STALE_AFTER_MS = 30_000;

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

function StreamStatus({
  mode,
  stale,
}: Readonly<{
  mode: ConnectionMode;
  stale: boolean;
}>) {
  const connected = mode === "stream" && !stale;
  return (
    <div
      role="status"
      aria-live="polite"
      className="ml-auto flex items-center gap-2 text-sm text-slate-300"
    >
      {connected ? (
        <Wifi size={16} className="text-emerald-400" />
      ) : (
        <WifiOff size={16} className="text-amber-400" />
      )}
      {connectionLabel(mode)}
      {stale ? (
        <span className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-200">
          data stale
        </span>
      ) : null}
    </div>
  );
}

function CandidatePanel({
  symbol,
  candidate,
  hasFreshSnapshot,
}: Readonly<{
  symbol: string;
  candidate: Candidate;
  hasFreshSnapshot: boolean;
}>) {
  return (
    <article className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 shadow-lg shadow-slate-950/30">
      <ScoreCard symbol={symbol} candidate={candidate} hasFreshSnapshot={hasFreshSnapshot} />
      <MarketContext candidate={candidate} hasFreshSnapshot={hasFreshSnapshot} />
    </article>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardSnapshot | null>(null);
  const [mode, setMode] = useState<ConnectionMode>("reconnecting");
  const [stale, setStale] = useState(false);
  const latestSnapshot = useRef<SnapshotIdentity | null>(null);
  const lastSnapshotReceivedAt = useRef<number | null>(null);

  useEffect(() => {
    let active = true;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    let staleTimer: ReturnType<typeof setInterval> | undefined;
    let pollAttempt = 0;
    let streaming = false;
    let hasSnapshot = false;
    let snapshotStale = false;
    let allowVersionReset = false;

    const clearPollTimer = () => {
      if (pollTimer !== undefined) {
        clearTimeout(pollTimer);
        pollTimer = undefined;
      }
    };

    const acceptSnapshot = (snapshot: DashboardSnapshot): boolean => {
      const identity: SnapshotIdentity = {
        snapshot_version: snapshot.snapshot_version,
        generated_at: snapshot.generated_at,
      };

      if (
        !active
        || !shouldAcceptDashboardSnapshot(
          latestSnapshot.current,
          identity,
          { allowVersionReset },
        )
      ) {
        return false;
      }

      latestSnapshot.current = identity;
      lastSnapshotReceivedAt.current = Date.now();
      allowVersionReset = false;
      hasSnapshot = true;
      snapshotStale = false;
      setStale(false);
      setData(snapshot);
      return true;
    };

    const schedulePoll = (
      delay: number,
      options: Readonly<{ replace?: boolean; force?: boolean }> = {},
    ) => {
      if (!active) return;
      if (options.replace) clearPollTimer();
      if (pollTimer !== undefined) return;

      const jitter = boundedJitter(Math.max(250, delay * 0.2));
      pollTimer = setTimeout(async () => {
        pollTimer = undefined;
        if (
          !active
          || (streaming && hasSnapshot && !snapshotStale && options.force !== true)
        ) {
          return;
        }

        try {
          const response = await fetch("/dashboard/api/candidates", {
            cache: "no-store",
          });
          const snapshot = response.ok
            ? dashboardSnapshot(await response.json())
            : undefined;
          if (!snapshot) throw new Error("invalid dashboard snapshot");

          acceptSnapshot(snapshot);
          if (!active) return;

          pollAttempt = 0;
          if (streaming && hasSnapshot && !snapshotStale) {
            setMode("stream");
            return;
          }

          setMode("polling");
          schedulePoll(5_000, { force: snapshotStale });
        } catch {
          if (!active) return;
          pollAttempt += 1;
          setMode("reconnecting");
          schedulePoll(
            Math.min(30_000, 1_000 * (2 ** Math.min(pollAttempt, 5))),
            { force: snapshotStale },
          );
        }
      }, delay + jitter);
    };

    const handleStreamMessage = (event: MessageEvent<string>) => {
      try {
        const packet = dashboardStreamEvent(JSON.parse(event.data));
        if (!packet) throw new Error("invalid dashboard stream event");

        streaming = true;

        if (packet.payload) {
          const accepted = acceptSnapshot(packet.payload);
          if (accepted && hasSnapshot) {
            clearPollTimer();
            setMode("stream");
          }
        } else if (!hasSnapshot) {
          // A heartbeat proves transport liveness, not snapshot readiness.
          setMode("reconnecting");
        }
      } catch {
        // A malformed event is not a transport failure. EventSource.onerror
        // owns connection state; polling remains available for bootstrap/stale
        // recovery without falsely declaring the socket disconnected.
        if (!hasSnapshot) {
          setMode("reconnecting");
        }
      }
    };

    const handleNamedStreamEvent = (event: Event) => {
      if (event instanceof MessageEvent) {
        handleStreamMessage(event as MessageEvent<string>);
      }
    };

    const stream = new EventSource("/dashboard/api/stream");

    stream.onopen = () => {
      streaming = true;
      pollAttempt = 0;
      if (hasSnapshot && !snapshotStale) {
        clearPollTimer();
        setMode("stream");
      } else {
        setMode("reconnecting");
      }
    };

    stream.onerror = () => {
      streaming = false;
      allowVersionReset = true;
      setMode("reconnecting");
      schedulePoll(1_000, { replace: true, force: true });
    };

    stream.onmessage = handleStreamMessage;
    stream.addEventListener("snapshot", handleNamedStreamEvent);
    stream.addEventListener("heartbeat", handleNamedStreamEvent);

    // Bootstrap from the schema-validated polling endpoint even when the SSE
    // socket opens first. This prevents an open heartbeat-only stream from
    // suppressing the initial READY snapshot forever.
    schedulePoll(0);

    staleTimer = setInterval(() => {
      if (!active || !hasSnapshot || lastSnapshotReceivedAt.current === null) {
        return;
      }

      const staleNow = Date.now() - lastSnapshotReceivedAt.current > STALE_AFTER_MS;
      if (staleNow && !snapshotStale) {
        snapshotStale = true;
        setStale(true);
        setMode("reconnecting");
        schedulePoll(0, { replace: true, force: true });
      }
    }, 5_000);

    return () => {
      active = false;
      stream.removeEventListener("snapshot", handleNamedStreamEvent);
      stream.removeEventListener("heartbeat", handleNamedStreamEvent);
      stream.close();
      clearPollTimer();
      if (staleTimer !== undefined) clearInterval(staleTimer);
    };
  }, []);

  const rows = useMemo(
    () => Object.entries(data?.candidates ?? {}).sort(compareCandidateEntries),
    [data],
  );

  const groups = useMemo(() => {
    const setupStates = new Set(["FUEL-RICH", "PRE-TRIGGER", "ARMED"]);
    const grouped = {
      strictConfirmed: [] as [string, Candidate][],
      strictSetup: [] as [string, Candidate][],
      experimental: [] as [string, Candidate][],
      discovery: [] as [string, Candidate][],
    };

    for (const entry of rows) {
      const [, candidate] = entry;
      if (candidate.signal_class === "STRICT" && candidate.status === "TRIGGERED") {
        grouped.strictConfirmed.push(entry);
      } else if (
        candidate.signal_class === "STRICT"
        && setupStates.has(String(candidate.status))
      ) {
        grouped.strictSetup.push(entry);
      } else if (candidate.signal_class === "EXPERIMENTAL") {
        grouped.experimental.push(entry);
      } else {
        grouped.discovery.push(entry);
      }
    }

    return grouped;
  }, [rows]);

  const renderGroup = (
    title: string,
    items: [string, Candidate][],
    tone = "slate",
  ) => items.length > 0 && (
    <section className="mx-auto mb-8 max-w-7xl">
      <h2 className={`mb-3 text-sm font-semibold uppercase tracking-wide ${tone === "experimental" ? "text-violet-300" : "text-slate-300"}`}>
        {title}
      </h2>
      <div className={`grid gap-5 xl:grid-cols-2 ${tone === "experimental" ? "rounded-2xl border border-violet-500/25 bg-violet-950/10 p-4" : ""}`}>
        {items.map(([symbol, candidate]) => (
          <CandidatePanel
            key={symbol}
            symbol={symbol}
            candidate={candidate}
            hasFreshSnapshot={data !== null && !stale}
          />
        ))}
      </div>
    </section>
  );

  let emptyState: ReactNode = null;
  if (data === null) {
    emptyState = (
      <div
        role="status"
        aria-live="polite"
        className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 py-24 text-center"
      >
        <Loader2 size={28} className="mx-auto mb-4 animate-spin text-emerald-400" />
        <p className="text-lg font-medium">Initializing live state…</p>
        <p className="mt-2 text-sm text-slate-400">
          Waiting for a schema-valid stream snapshot or polling fallback.
        </p>
      </div>
    );
  } else if (rows.length === 0) {
    emptyState = (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 py-24 text-center">
        <p className="text-lg font-medium">No active candidates in the latest valid snapshot</p>
        <p className="mt-2 text-sm text-slate-400">
          This is a real READY snapshot, not an initializing placeholder.
        </p>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100 sm:px-6 lg:px-10">
      <header className="mx-auto mb-5 flex max-w-7xl items-center gap-3 border-b border-slate-800 pb-5">
        <Activity className="text-emerald-400" size={30} />
        <div>
          <h1 className="text-2xl font-bold tracking-tight">WaterfallHunter</h1>
          <p className="text-sm text-slate-400">Evidence-first paper research terminal</p>
        </div>
        <StreamStatus mode={mode} stale={stale} />
      </header>

      <nav className="mx-auto mb-7 flex max-w-7xl gap-2 overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/85 p-2 text-xs text-slate-300 shadow-lg shadow-slate-950/20" aria-label="Dashboard sections">
        <a href="#overview" className="inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 hover:bg-slate-800 hover:text-white"><LayoutDashboard size={14} />Overview</a>
        <a href="#evidence" className="inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 hover:bg-slate-800 hover:text-white"><ShieldCheck size={14} />Evidence</a>
        <a href="#lifecycle-shadow" className="inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 hover:bg-slate-800 hover:text-white"><GitBranch size={14} />Lifecycle shadow</a>
        <a href="#backtest-lab" className="inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 hover:bg-slate-800 hover:text-white"><FlaskConical size={14} />Backtest Lab</a>
        <a href="#live-candidates" className="inline-flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 hover:bg-slate-800 hover:text-white"><Radio size={14} />Candidates</a>
        <span
          title="PAPER_ONLY runtime: this dashboard does not authorize or route real orders."
          className="ml-auto inline-flex shrink-0 items-center rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 font-semibold text-emerald-200"
        >
          LIVE TRADING OFF
        </span>
      </nav>

      <section id="overview" className="mx-auto mb-7 grid max-w-7xl scroll-mt-4 gap-4 md:grid-cols-4">
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">Tracked candidates</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums">{data?.total ?? "—"}</p>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <p className="text-sm text-slate-400">STRICT confirmed</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums text-emerald-200">{groups.strictConfirmed.length}</p>
        </div>
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-5 md:col-span-2">
          <p className="text-sm text-slate-400">Live-data policy</p>
          <p className="mt-1 text-sm text-slate-200">
            Only current exchange evidence is shown. Missing analysis remains unavailable; it is never converted into a score.
          </p>
        </div>
      </section>

      <div id="evidence" className="scroll-mt-4"><OutcomeEvidence /></div>

      <HistoricalOutcomes />

      <ProductionEvidence />

      <FeatureReplay />

      <LifecycleShadow />

      <BacktestLab />

      <SignalFunnel funnel={data?.signal_funnel as SignalFunnelData | undefined} />

      <FinalRanking ranking={data?.final_ranking} />

      <section id="live-candidates" className="mx-auto mb-5 max-w-7xl scroll-mt-4">
        {rows.length > 0 && (
          <p className="mb-3 text-xs text-slate-500">
            Complete Score V2 candidates keep their existing score. Partial Watch Score ordering uses normalized score × evidence coverage; missing coverage remains unavailable. The Top 3 panel is observational and does not alter state or eligibility.
          </p>
        )}
        {emptyState}
      </section>

      {renderGroup("Confirmed STRICT signals", groups.strictConfirmed)}
      {renderGroup("STRICT armed and pre-trigger setups", groups.strictSetup)}
      {renderGroup("Experimental research — never mixed with STRICT", groups.experimental, "experimental")}
      {renderGroup("Watch and discovery", groups.discovery)}
    </main>
  );
}
