"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Search,
  ShieldAlert,
  Target,
  TrendingDown,
} from "lucide-react";
import type { Candidate } from "@/components/score-card";
import {
  advisoryPresentation,
  blockedOrOtherBreakdown,
  blockedOrOtherCount,
  candidateFreshness,
  canonicalLeverageAdvisory,
  pipelineHealthDegraded,
  tradePlanAvailable,
  decisionPlanPresentation,
} from "@/lib/decision-terminal-ui";

type Rec = Record<string, unknown>;

function record(value: unknown): Rec {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Rec
    : {};
}

function finite(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function price(value: unknown): string {
  const number = finite(value);
  if (number === undefined) return "—";
  if (number >= 1000) return number.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (number >= 1) return number.toLocaleString("en-US", { maximumFractionDigits: 5 });
  return number.toPrecision(5).replace(/0+$/, "").replace(/\.$/, "");
}

function number(value: unknown, digits = 2): string {
  const parsed = finite(value);
  return parsed === undefined ? "—" : parsed.toFixed(digits);
}

function pct(value: unknown, digits = 2): string {
  const parsed = finite(value);
  return parsed === undefined ? "—" : `${parsed.toFixed(digits)}%`;
}

function decisionTone(decision: string): string {
  if (decision === "ENTRY_READY") return "border-emerald-400/40 bg-emerald-500/15 text-emerald-100";
  if (decision === "FORMING") return "border-amber-400/35 bg-amber-500/10 text-amber-100";
  if (decision === "ACTIVE") return "border-sky-400/35 bg-sky-500/10 text-sky-100";
  if (decision === "LATE") return "border-orange-400/35 bg-orange-500/10 text-orange-100";
  if (decision === "INVALIDATED") return "border-rose-400/35 bg-rose-500/10 text-rose-100";
  return "border-slate-700 bg-slate-900 text-slate-300";
}

function evidencePacket(candidate: Candidate) {
  const metrics = record(candidate.metrics);
  const decision = record(metrics.entry_decision);
  const planPresentation = decisionPlanPresentation(metrics, decision);
  return {
    metrics,
    decision,
    plan: planPresentation.plan,
    planKind: planPresentation.kind,
    evidence: record(decision.evidence_summary),
    advisory: record(metrics.ai_advisory),
    leverageAdvisory: canonicalLeverageAdvisory(metrics, decision),
  };
}

function SignalLevels({ plan }: Readonly<{ plan: Rec }>) {
  const hasTp3 = finite(plan.take_profit_3) !== undefined;
  return (
    <dl className={`mt-4 grid grid-cols-2 gap-2 ${hasTp3 ? "sm:grid-cols-5" : "sm:grid-cols-4"}`}>
      <div className="metric-card"><dt>Entry</dt><dd className="mt-1 font-mono">${price(plan.entry_price)}</dd></div>
      <div className="metric-card"><dt>Stop</dt><dd className="mt-1 font-mono text-rose-200">${price(plan.stop_loss)}</dd></div>
      <div className="metric-card"><dt>TP1</dt><dd className="mt-1 font-mono text-emerald-200">${price(plan.take_profit_1)}</dd></div>
      <div className="metric-card"><dt>TP2</dt><dd className="mt-1 font-mono text-emerald-200">${price(plan.take_profit_2)}</dd></div>
      {hasTp3 ? <div className="metric-card"><dt>TP3</dt><dd className="mt-1 font-mono text-emerald-200">${price(plan.take_profit_3)}</dd></div> : null}
    </dl>
  );
}

function EvidenceGrid({ evidence }: Readonly<{ evidence: Rec }>) {
  const derivatives = record(evidence.derivatives);
  const flow = record(evidence.order_flow);
  const execution = record(evidence.execution);
  const cascade = record(evidence.cascade);
  const cross = evidence.cross_exchange_confirmed;
  const antiChase = finite(evidence.anti_chase_extension_atr);
  return (
    <dl className="mt-4 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-8">
      <div className="metric-card"><dt>OI 1h</dt><dd>{pct(derivatives.oi_change_1h_pct, 3)}</dd></div>
      <div className="metric-card"><dt>Funding</dt><dd>{pct(derivatives.funding_rate_pct, 4)}</dd></div>
      <div className="metric-card"><dt>Taker B/S</dt><dd>{number(flow.taker_buy_sell_ratio, 3)}</dd></div>
      <div className="metric-card"><dt>Sell share</dt><dd>{pct(flow.sell_share_pct, 1)}</dd></div>
      <div className="metric-card"><dt>Cascade</dt><dd>{String(cascade.status ?? "—")} · {number(cascade.readiness_points, 1)}/10</dd></div>
      <div className="metric-card"><dt>Cross-exchange</dt><dd>{cross === true ? "Confirmed" : cross === false ? "No" : "—"}</dd></div>
      <div className="metric-card"><dt>Spread</dt><dd>{pct(execution.spread_pct, 4)}</dd></div>
      <div className="metric-card"><dt>Anti-chase</dt><dd>{antiChase === undefined ? "—" : `${antiChase.toFixed(2)} ATR`}</dd></div>
    </dl>
  );
}

function DecisionCard({ symbol, candidate }: Readonly<{ symbol: string; candidate: Candidate }>) {
  const { decision, plan, planKind, evidence, advisory, leverageAdvisory } = evidencePacket(candidate);
  const state = String(decision.decision ?? "UNAVAILABLE");
  const readiness = finite(decision.entry_readiness);
  const coverage = finite(decision.evidence_coverage_pct);
  const hasPlan = tradePlanAvailable(plan);
  let planNotice: string | null = null;
  if (planKind === "reference") {
    planNotice = "Reference plan · technical shadow · not an entry command";
  } else if (state !== "ENTRY_READY") {
    planNotice = "Reference plan · not an entry command";
  }
  const advisoryView = advisoryPresentation(advisory);
  const leverageStatus = String(leverageAdvisory.status ?? "");
  const leverageValue = finite(leverageAdvisory.leverage ?? plan.leverage);
  const leverageText = leverageStatus === "AVAILABLE" && leverageValue !== undefined
    ? `${number(leverageValue, 0)}×`
    : leverageStatus === "UNAVAILABLE" || leverageStatus === "NOT_RECOMMENDED"
      ? leverageStatus.replaceAll("_", " ")
      : leverageValue !== undefined ? `${number(leverageValue, 0)}×` : "UNAVAILABLE";
  const blocks = Array.isArray(decision.block_reasons)
    ? decision.block_reasons.filter((value): value is string => typeof value === "string")
    : [];
  const reasons = Array.isArray(decision.reason_codes)
    ? decision.reason_codes.filter((value): value is string => typeof value === "string").slice(0, 8)
    : [];
  return (
    <article className={`panel overflow-hidden border ${state === "ENTRY_READY" ? "border-emerald-500/35" : "border-slate-800"}`}>
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><p className="font-mono text-lg font-semibold text-sky-200">{symbol}</p><p className="mt-1 text-2xl font-semibold">${price(candidate.last_price)}</p></div>
          <span className={`status-pill border ${decisionTone(state)}`}>{state.replaceAll("_", " ")}</span>
        </div>
        <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
          <div><p className="text-xs uppercase tracking-wider text-slate-500">Entry readiness</p><p className="text-4xl font-semibold tabular-nums">{readiness === undefined ? "—" : readiness.toFixed(1)}<span className="text-base text-slate-500">/100</span></p></div>
          <div className="text-right text-xs text-slate-400"><p>Evidence {coverage === undefined ? "—" : `${coverage.toFixed(0)}%`}</p><p>Leverage {leverageText}</p></div>
        </div>
        {hasPlan ? (
          <>
            {planNotice ? (
              <p className="mt-4 text-xs font-medium text-amber-200/90">{planNotice}</p>
            ) : null}
            <SignalLevels plan={plan} />
          </>
        ) : (
          <div className="mt-4 rounded-lg border border-slate-700 bg-slate-950/45 px-3 py-2 text-xs text-slate-400">
            No canonical trade plan for this state. Entry, stop and take-profit levels are intentionally unavailable.
          </div>
        )}
        <EvidenceGrid evidence={evidence} />
        {blocks.length > 0 ? (
          <div className="mt-4 flex gap-2 rounded-lg border border-rose-500/25 bg-rose-500/10 px-3 py-2 text-xs text-rose-100">
            <ShieldAlert size={15} className="shrink-0" />
            <span>{blocks.join(" · ").replaceAll("_", " ")}</span>
          </div>
        ) : null}
        {reasons.length > 0 ? <p className="mt-3 text-xs leading-5 text-slate-400">{reasons.join(" · ").replaceAll("_", " ")}</p> : null}
        <div className="mt-4 border-t border-slate-800 pt-3 text-xs text-slate-400">
          <p className="flex items-start gap-2"><BrainCircuit size={14} className="mt-0.5 shrink-0" /><span><b className="text-slate-300">AI advisory:</b> {advisoryView.status}{advisoryView.confidence === undefined ? "" : ` · ${number(advisoryView.confidence, 0)}%`} · {advisoryView.reasoning}</span></p>
        </div>
      </div>
    </article>
  );
}

function EmptyReady({ pipelineDegraded }: Readonly<{ pipelineDegraded: boolean }>) {
  if (pipelineDegraded) {
    return (
      <div className="panel border border-rose-500/30 bg-rose-500/5 px-5 py-8 text-center">
        <ShieldAlert className="mx-auto text-rose-300" size={28} />
        <p className="mt-3 text-base font-semibold text-rose-100">ENTRY READY cannot be evaluated reliably</p>
        <p className="mt-1 text-sm text-slate-400">Required decision evidence is systemically unavailable. Treat zero ENTRY READY as unavailable, not as a market no-signal conclusion.</p>
      </div>
    );
  }
  return (
    <div className="panel border border-slate-800 px-5 py-8 text-center">
      <Target className="mx-auto text-slate-500" size={28} />
      <p className="mt-3 text-base font-semibold">No ENTRY READY signal now</p>
      <p className="mt-1 text-sm text-slate-400">Do not enter only because a symbol is ranked or pre-trigger. Wait for a canonical ENTRY READY event.</p>
    </div>
  );
}

function ZeroEntryDiagnostics({ diagnostics }: Readonly<{ diagnostics: Rec }>) {
  const rows = Array.isArray(diagnostics.top_reasons)
    ? diagnostics.top_reasons.map(record).filter((row) => typeof row.reason === "string")
    : [];
  const systemic = Array.isArray(diagnostics.systemic_unavailable_reasons)
    ? diagnostics.systemic_unavailable_reasons.map(record).filter((row) => typeof row.reason === "string")
    : [];
  const degraded = pipelineHealthDegraded(diagnostics);
  if (!degraded && (diagnostics.entry_ready_zero !== true || rows.length === 0)) return null;
  return (
    <section className={`mt-4 rounded-xl border p-4 ${degraded ? "border-rose-500/30 bg-rose-500/5" : "border-amber-500/20 bg-amber-500/5"}`}>
      <div className={`flex items-center gap-2 text-sm font-semibold ${degraded ? "text-rose-100" : "text-amber-100"}`}>
        <AlertTriangle size={16} /> {degraded ? "Decision pipeline degraded" : "Why ENTRY READY is zero"}
      </div>
      <p className="mt-1 text-xs text-slate-400">
        {degraded
          ? `Required evidence is unavailable across all ${number(diagnostics.evaluated_candidates, 0)} evaluated candidates. This is a system/data availability failure, not a market gate conclusion.`
          : `Dominant canonical gate failures across ${number(diagnostics.evaluated_candidates, 0)} evaluated candidates.`}
      </p>
      {degraded ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {systemic.map((row) => (
            <span key={`systemic-${String(row.reason)}`} className="rounded-full border border-rose-500/25 bg-rose-950/30 px-2.5 py-1 text-xs text-rose-100">
              {String(row.reason).replaceAll("_", " ")} · systemic
            </span>
          ))}
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {rows.map((row) => (
          <span key={String(row.reason)} className={`rounded-full border px-2.5 py-1 text-xs ${degraded ? "border-slate-700 bg-slate-950/50 text-slate-300" : "border-amber-500/20 bg-slate-950/50 text-slate-300"}`}>
            {String(row.reason).replaceAll("_", " ")} · {number(row.count, 0)} ({pct(row.share_pct, 1)})
          </span>
        ))}
      </div>
    </section>
  );
}

function TerminalKpis({ counts }: Readonly<{ counts: Rec }>) {
  const blocked = blockedOrOtherCount(counts);
  const blockedDetail = blockedOrOtherBreakdown(counts);
  const cards = [
    { label: "ENTRY READY", value: counts.ENTRY_READY, tone: "text-emerald-300" },
    { label: "FORMING", value: counts.FORMING, tone: "text-amber-300" },
    { label: "ACTIVE", value: counts.ACTIVE, tone: "text-sky-300" },
    { label: "BLOCKED / OTHER", value: blocked, tone: "text-orange-300", detail: blockedDetail },
  ] as const;
  return (
    <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {cards.map(({ label, value, tone, ...rest }) => (
        <div key={label} className="panel px-4 py-3.5">
          <dt className="text-xs font-medium text-slate-400">{label}</dt>
          <dd className={`mt-1 text-2xl font-semibold tabular-nums sm:text-3xl ${tone}`}>
            {finite(value) === undefined ? "—" : number(value, 0)}
          </dd>
          {"detail" in rest && rest.detail ? <p className="mt-1 text-[11px] text-slate-500">{rest.detail}</p> : null}
        </div>
      ))}
    </dl>
  );
}

function symbols(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function CandidateTable({ candidates, nowSeconds }: Readonly<{ candidates: Record<string, Candidate>; nowSeconds?: number }>) {
  const [query, setQuery] = useState("");
  const [decisionFilter, setDecisionFilter] = useState("ALL");
  const [page, setPage] = useState(0);
  const pageSize = 25;
  const rows = useMemo(() => {
    const normalized = query.trim().toUpperCase();
    return Object.entries(candidates)
      .map(([symbol, candidate]) => {
        const packet = evidencePacket(candidate).decision;
        return { symbol, candidate, decision: String(packet.decision ?? "UNAVAILABLE"), readiness: finite(packet.entry_readiness) ?? -1 };
      })
      .filter((row) => (!normalized || row.symbol.toUpperCase().includes(normalized))
        && (decisionFilter === "ALL" || row.decision === decisionFilter))
      .sort((left, right) => right.readiness - left.readiness || left.symbol.localeCompare(right.symbol));
  }, [candidates, query, decisionFilter]);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const safePage = Math.min(page, pages - 1);
  useEffect(() => {
    setPage((current) => Math.min(current, pages - 1));
  }, [pages]);
  const visible = rows.slice(safePage * pageSize, safePage * pageSize + pageSize);
  return (
    <section id="all-candidates" className="panel mt-6 overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 p-4">
        <div className="relative min-w-[220px] flex-1"><Search size={15} className="absolute left-3 top-2.5 text-slate-500" /><input value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} placeholder="Search symbol" className="w-full rounded-lg border border-slate-700 bg-slate-950 py-2 pl-9 pr-3 text-sm outline-none focus:border-sky-500" /></div>
        <select value={decisionFilter} onChange={(event) => { setDecisionFilter(event.target.value); setPage(0); }} className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm">
          {["ALL", "ENTRY_READY", "FORMING", "ACTIVE", "LATE", "INVALIDATED", "EXPIRED", "NO_TRADE", "UNAVAILABLE"].map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
        <span className="text-xs text-slate-500">{rows.length} candidates</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-500"><tr><th className="px-4 py-3">Symbol</th><th>Decision</th><th>Readiness</th><th>Price</th><th>OI 1h</th><th>Taker B/S</th><th>Cascade</th><th>Freshness</th></tr></thead>
          <tbody className="divide-y divide-slate-800">
            {visible.map(({ symbol, candidate, decision, readiness }) => {
              const { evidence } = evidencePacket(candidate);
              const derivatives = record(evidence.derivatives);
              const flow = record(evidence.order_flow);
              const cascade = record(evidence.cascade);
              const freshness = candidateFreshness(candidate, nowSeconds);
              let freshnessText = "—";
              if (freshness.ageSeconds !== undefined) {
                freshnessText = `${number(freshness.ageSeconds, 0)}s`;
                if (freshness.state === "stale") freshnessText += " · stale";
              }
              const cascadeStatus = typeof cascade.status === "string" ? cascade.status : "—";
              return <tr key={symbol} className="hover:bg-slate-900/60"><td className="px-4 py-3 font-mono text-sky-200">{symbol}</td><td><span className={`status-pill border ${decisionTone(decision)}`}>{decision.replaceAll("_", " ")}</span></td><td className="font-mono">{readiness < 0 ? "—" : readiness.toFixed(1)}</td><td className="font-mono">${price(candidate.last_price)}</td><td>{pct(derivatives.oi_change_1h_pct, 2)}</td><td>{number(flow.taker_buy_sell_ratio, 3)}</td><td>{cascadeStatus}</td><td className={freshness.state === "stale" ? "font-medium text-rose-300" : "text-slate-300"} title={freshness.thresholdSeconds === undefined ? undefined : `Policy freshness limit ${number(freshness.thresholdSeconds, 0)}s`}>{freshnessText}</td></tr>;
            })}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-slate-800 px-4 py-3 text-xs text-slate-400">
        <button
          type="button"
          disabled={safePage <= 0}
          onClick={() => setPage((value) => Math.max(0, value - 1))}
          className="rounded-md border border-slate-700 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Previous
        </button>
        <span>Page {safePage + 1} / {pages}</span>
        <button
          type="button"
          disabled={safePage >= pages - 1}
          onClick={() => setPage((value) => Math.min(pages - 1, value + 1))}
          className="rounded-md border border-slate-700 px-3 py-1.5 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </section>
  );
}
function DecisionSection({ title, icon, symbols: items, candidates }: Readonly<{
  title: string;
  icon: React.ReactNode;
  symbols: string[];
  candidates: Record<string, Candidate>;
}>) {
  const visible = items.filter((symbol) => candidates[symbol] !== undefined);
  if (visible.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        {icon}{title}
      </h2>
      <div className="grid gap-4 xl:grid-cols-2">
        {visible.map((symbol) => (
          <DecisionCard key={symbol} symbol={symbol} candidate={candidates[symbol]} />
        ))}
      </div>
    </section>
  );
}
function timeText(value: unknown): string {
  const timestamp = finite(value);
  if (timestamp === undefined) return "—";
  return new Date(timestamp * 1000).toLocaleString("en-US", {
    month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}

function RecentDecisionChanges({ value }: Readonly<{ value: unknown }>) {
  const rows = Array.isArray(value)
    ? value.map(record).filter((row) => Object.keys(row).length > 0).slice(0, 10)
    : [];
  if (rows.length === 0) return null;
  return (
    <section className="panel mt-6 p-4 sm:p-5" aria-label="Recent canonical decision changes">
      <h2 className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-slate-300">
        <Activity size={16} className="text-cyan-300" />Recent decision changes
      </h2>
      <div className="table-scroll mt-3">
        <table className="data-table min-w-[760px]">
          <thead><tr><th>Changed</th><th>Symbol</th><th>Previous</th><th>Decision</th><th>Reason</th></tr></thead>
          <tbody>{rows.map((row, index) => {
            const blocks = Array.isArray(row.block_reasons) ? row.block_reasons.filter((item) => typeof item === "string") : [];
            const reasons = Array.isArray(row.reason_codes) ? row.reason_codes.filter((item) => typeof item === "string") : [];
            const reason = String(row.transition_reason ?? blocks[0] ?? reasons[0] ?? "—");
            return <tr key={String(row.event_id ?? `${row.symbol ?? "unknown"}-${row.event_at ?? index}`)}>
              <td className="whitespace-nowrap text-slate-400">{timeText(row.event_at ?? row.evaluated_at)}</td>
              <td className="font-mono text-sky-300">{String(row.symbol ?? "—")}</td>
              <td>{String(row.previous_decision ?? "—")}</td>
              <td className="font-medium text-cyan-100">{String(row.decision ?? "UNAVAILABLE")}</td>
              <td className="max-w-[340px] truncate" title={reason}>{reason}</td>
            </tr>;
          })}</tbody>
        </table>
      </div>
    </section>
  );
}

export function DecisionTerminal({ terminal, candidates, nowSeconds }: Readonly<{
  terminal: unknown;
  candidates: Record<string, Candidate>;
  nowSeconds?: number;
}>) {
  const packet = record(terminal);
  const counts = record(packet.counts);
  const diagnostics = record(packet.zero_entry_ready_diagnostics);
  const pipelineDegraded = pipelineHealthDegraded(diagnostics);
  const ready = symbols(packet.entry_ready);
  const forming = symbols(packet.forming);
  const active = symbols(packet.active);
  const late = symbols(packet.late);

  return (
    <section id="decision-terminal" className="mx-auto mb-8 max-w-7xl scroll-mt-28">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-300">Canonical decision terminal</p>
          <h2 className="mt-1 text-2xl font-semibold">One decision path. ENTRY READY is the only actionable state.</h2>
        </div>
        <span className="status-pill border border-slate-700 bg-slate-900 text-slate-300">SIGNAL ONLY</span>
      </div>
      <TerminalKpis counts={counts} />
      <div className="mt-4">{ready.length === 0 ? <EmptyReady pipelineDegraded={pipelineDegraded} /> : null}</div>
      <ZeroEntryDiagnostics diagnostics={diagnostics} />
      <DecisionSection
        title="ENTRY READY"
        icon={<CheckCircle2 size={16} className="text-emerald-400" />}
        symbols={ready}
        candidates={candidates}
      />
      <DecisionSection
        title="Closest setups · do not enter yet"
        icon={<Clock3 size={16} className="text-amber-400" />}
        symbols={forming}
        candidates={candidates}
      />
      <DecisionSection
        title="Active cascade · evaluate chase risk"
        icon={<TrendingDown size={16} className="text-sky-400" />}
        symbols={active}
        candidates={candidates}
      />
      <DecisionSection
        title="Late · do not chase"
        icon={<AlertTriangle size={16} className="text-orange-400" />}
        symbols={late}
        candidates={candidates}
      />
      <RecentDecisionChanges value={packet.recent_changes} />
      <CandidateTable candidates={candidates} nowSeconds={nowSeconds} />
    </section>
  );
}
