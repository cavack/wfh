"use client";
import { useEffect, useState } from 'react';
import { Activity, Zap } from 'lucide-react';

export default function Dashboard() {
  const [data, setData] = useState({ total: 0, candidates: {} });
  const [status, setStatus] = useState("Connecting...");

  useEffect(() => {
    let sse: EventSource;
    const connectSSE = () => {
      sse = new EventSource('/api/stream');
      sse.onopen = () => setStatus("LIVE");
      sse.onmessage = (e) => setData(JSON.parse(e.data));
      sse.onerror = () => {
        setStatus("Reconnecting...");
        sse.close();
        setTimeout(connectSSE, 3000);
      };
    };
    connectSSE();
    return () => { if(sse) sse.close(); };
  }, []);

  const candidates = Object.values(data.candidates || {});
  
  return (
    <div className="p-8 max-w-7xl mx-auto font-sans">
      <div className="flex justify-between items-center mb-8 border-b border-slate-800 pb-4">
        <div>
          <h1 className="text-3xl font-bold text-white flex items-center gap-3">
            <Zap className="text-blue-500" /> Waterfall<span className="text-blue-500">Hunter</span>
          </h1>
          <p className="text-slate-400 text-sm mt-1">Institutional-Grade Next.js Terminal</p>
        </div>
        <div className="flex items-center gap-2">
          <span className={`font-semibold text-sm ${status === 'LIVE' ? 'text-green-400' : 'text-yellow-400'}`}>{status}</span>
        </div>
      </div>

      <div className="bg-slate-900 p-5 mb-8 rounded-lg border border-slate-800 shadow-lg w-64">
        <p className="text-slate-400 text-sm font-medium">Total Tracked</p>
        <p className="text-3xl font-bold text-white mt-2">{data.total}</p>
      </div>

      <div className="bg-slate-900 rounded-lg border border-slate-800 overflow-hidden shadow-2xl">
        <table className="w-full text-left">
          <thead className="bg-slate-950/50 text-slate-400 text-xs uppercase">
            <tr>
              <th className="px-6 py-4 font-medium">Symbol</th>
              <th className="px-6 py-4 font-medium">Price</th>
              <th className="px-6 py-4 font-medium">Score</th>
              <th className="px-6 py-4 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {candidates.map((c: any) => (
              <tr key={c.symbol} className="hover:bg-slate-800/50 transition-colors">
                <td className="px-6 py-4 font-bold text-white flex items-center gap-2">
                  {c.is_meme && <Activity size={16} className="text-purple-400"/>}
                  {c.symbol.split(':')[0]}
                </td>
                <td className="px-6 py-4 font-mono text-slate-300">${parseFloat(c.last_price || 0).toFixed(5)}</td>
                <td className={`px-6 py-4 font-mono font-bold ${c.score >= 85 ? 'text-red-500' : c.score >= 50 ? 'text-yellow-400' : 'text-blue-400'}`}>
                  {c.score}/100
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs font-bold ${c.status === 'TRIGGERED' ? 'bg-red-500/20 text-red-500' : c.status === 'ARMED' ? 'bg-yellow-500/20 text-yellow-500' : 'bg-slate-800 text-slate-400'}`}>
                    {c.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
