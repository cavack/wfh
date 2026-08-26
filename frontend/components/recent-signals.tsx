"use client";

import { useEffect, useState } from "react";
import { History, ShieldCheck } from "lucide-react";

type SignalRow = {
  signal_id?: number;
  symbol?: string;
  triggered_at?: number;
  state_before?: string;
  score?: number;
  applied_leverage?: number;
  signal_class?: string;
  strategy_profile?: string;
  entry_price?: number | null;
  stop_loss?: number | null;
  take_profit_1?: number | null;
  take_profit_2?: number | null;
  execution_status?: string;
  outcome_status?: string | null;
};

type RecentSignalReport = {
  contract_version?: string;
  operational?: boolean;
  observational_only?: boolean;
  hard_gating_allowed?: boolean;
  count?: number;
  signals?: SignalRow[];
};

function n(value: unknown, digits = 4): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("en-US", { maximumFractionDigits: digits })
    : "—";
}

function timeText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? new Date(value * 1000).toLocaleString()
    : "—";
}

export function RecentSignals() {
  const [report, setReport] = useState<RecentSignalReport>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch("/dashboard/api/recent-signals?limit=30", { cache: "no-store" });
        const payload = await response.json() as RecentSignalReport;
        if (!response.ok || payload.operational !== true || payload.observational_only !== true || payload.hard_gating_allowed !== false) {
          throw new Error("unsafe recent signal contract");
        }
        if (active) { setReport(payload); setFailed(false); }
      } catch {
        if (active) setFailed(true);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const rows = Array.isArray(report?.signals) ? report.signals : [];
  return (
    <section className="panel mx-auto mb-7 max-w-7xl p-5 sm:p-6" aria-label="Recent immutable signal history">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="flex items-center gap-2 text-sm font-semibold"><History size={17} className="text-cyan-300" />Recent signals</h2>
          <p className="mt-1 text-sm text-slate-400">Immutable trigger history from the production signal ledger; current candidate state does not erase these rows.</p>
        </div>
        <span className="status-pill border border-cyan-400/25 bg-cyan-500/10 text-cyan-200">LEDGER HISTORY</span>
      </div>
      {failed ? <p className="mt-4 rounded-xl border border-amber-400/25 bg-amber-500/10 p-3 text-xs text-amber-100">Refresh unavailable. The last verified rows remain displayed.</p> : null}
      {!report ? <p className="mt-5 text-sm text-slate-500">Loading immutable signal history…</p> : rows.length === 0 ? <p className="mt-5 text-sm text-slate-500">No persisted signals are available.</p> : (
        <div className="table-scroll mt-5">
          <table className="data-table min-w-[980px]">
            <thead><tr><th>Triggered</th><th>Symbol</th><th>Class</th><th>Score</th><th>Leverage</th><th>Entry</th><th>SL</th><th>TP1</th><th>TP2</th><th>Execution</th><th>Outcome</th></tr></thead>
            <tbody>{rows.map((row) => <tr key={row.signal_id ?? `${row.symbol}-${row.triggered_at}`}>
              <td className="whitespace-nowrap text-slate-400">{timeText(row.triggered_at)}</td>
              <td className="font-mono text-sky-300">{row.symbol ?? "—"}</td>
              <td>{row.signal_class ?? "—"}</td>
              <td className="font-mono">{n(row.score, 2)}</td>
              <td className="font-mono text-amber-200">{typeof row.applied_leverage === "number" ? `${n(row.applied_leverage, 0)}×` : "—"}</td>
              <td className="font-mono">{n(row.entry_price, 8)}</td>
              <td className="font-mono">{n(row.stop_loss, 8)}</td>
              <td className="font-mono">{n(row.take_profit_1, 8)}</td>
              <td className="font-mono">{n(row.take_profit_2, 8)}</td>
              <td>{row.execution_status ?? "—"}</td>
              <td>{row.outcome_status ?? "PENDING"}</td>
            </tr>)}</tbody>
          </table>
        </div>
      )}
      <p className="mt-4 flex items-start gap-2 border-t border-slate-800 pt-3 text-xs text-slate-500"><ShieldCheck size={14} className="mt-0.5 shrink-0" />Read-only historical evidence. It does not alter scores, states, alerts, or eligibility.</p>
    </section>
  );
}
