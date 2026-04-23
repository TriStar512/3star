/**
 * JARBIS Crypto — Live Artifact Dashboard
 * ----------------------------------------
 * Single-file React component designed to run as a Claude Live Artifact or
 * inside any React app. Pairs with the JARBIS Python bot running on your PC
 * (Flask server on http://127.0.0.1:5000 by default).
 *
 *  - On/Off toggle for the bot (POST /bot/start, /bot/stop)
 *  - All relevant trade info (mode, venue, balance, heat, positions, trades)
 *  - Live Hyperliquid market table for the top-10 perpetuals
 *  - Active-trade confidence gauge (gradient red -> yellow -> green)
 *  - @DeItaone breaking-news embed
 *
 * Scaled for a half-screen 1280x1440 viewport on a 32" 1440p monitor, but
 * gracefully collapses to narrower widths.
 *
 * Persistence: window.storage (Claude Artifacts) with localStorage and
 * in-memory fallbacks. Keys are prefixed "jarbis.".
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

// ---------- Config ----------

const TOP_COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "MATIC"];
const HL_INFO_URL = "https://api.hyperliquid.xyz/info";
const DEFAULTS = {
  botUrl: "http://127.0.0.1:5000",
  secret: "",
  refreshSec: 5,
};
const K = {
  botUrl: "jarbis.botUrl",
  secret: "jarbis.secret",
  refresh: "jarbis.refresh",
  selected: "jarbis.selectedCoin",
  manualConfidence: "jarbis.manualConfidence",
};

// ---------- Storage shim ----------

const memStore = {};
const storage = {
  get(key, fallback) {
    try {
      if (typeof window !== "undefined" && window.storage?.getItem) {
        const raw = window.storage.getItem(key);
        if (raw != null) return JSON.parse(raw);
      } else if (typeof window !== "undefined" && window.localStorage) {
        const raw = window.localStorage.getItem(key);
        if (raw != null) return JSON.parse(raw);
      } else if (key in memStore) {
        return memStore[key];
      }
    } catch (_) {}
    return fallback;
  },
  set(key, value) {
    try {
      const str = JSON.stringify(value);
      if (typeof window !== "undefined" && window.storage?.setItem) {
        window.storage.setItem(key, str);
      } else if (typeof window !== "undefined" && window.localStorage) {
        window.localStorage.setItem(key, str);
      } else {
        memStore[key] = value;
      }
    } catch (_) {
      memStore[key] = value;
    }
  },
};

// ---------- Fetch helpers ----------

async function postJson(url, body, timeoutMs = 10_000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function getJson(url, timeoutMs = 8_000, headers = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal, headers });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function fetchHyperliquid() {
  const data = await postJson(HL_INFO_URL, { type: "metaAndAssetCtxs" });
  const universe = data[0]?.universe || [];
  const ctxs = data[1] || [];
  const byName = new Map();
  universe.forEach((u, i) => byName.set((u.name || "").toUpperCase(), { meta: u, ctx: ctxs[i] || {} }));
  const rows = [];
  for (const coin of TOP_COINS) {
    const rec = byName.get(coin);
    if (!rec) continue;
    const { meta, ctx } = rec;
    const price = Number(ctx.markPx || ctx.midPx || ctx.oraclePx || 0);
    const open = Number(ctx.prevDayPx || price);
    const change24h = open ? ((price - open) / open) * 100 : 0;
    rows.push({
      coin,
      price,
      change24h,
      funding: Number(ctx.funding || 0),
      openInterest: Number(ctx.openInterest || 0),
      dayVolume: Number(ctx.dayNtlVlm || 0),
      maxLeverage: Number(meta.maxLeverage || 0),
    });
  }
  return rows;
}

// ---------- Formatters ----------

const fmt = {
  price(v) {
    if (!v) return "—";
    if (v >= 1000) return `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    if (v >= 1) return `$${v.toFixed(2)}`;
    return `$${v.toFixed(4)}`;
  },
  vol(v) {
    if (!v) return "—";
    if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    if (v >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
    return `$${v.toFixed(0)}`;
  },
  pct(v, d = 2) {
    if (v == null || Number.isNaN(v)) return "—";
    return `${v >= 0 ? "+" : ""}${v.toFixed(d)}%`;
  },
  lev(v) {
    return v ? `${Math.round(v)}x` : "—";
  },
  time(iso) {
    if (!iso) return "—";
    try { return new Date(iso).toLocaleTimeString(); } catch { return "—"; }
  },
};

// ---------- Confidence Gauge ----------

function ConfidenceGauge({ value, coin, auto, onManual }) {
  const v = Math.max(0, Math.min(100, value ?? 0));
  const angle = Math.PI * (1 - v / 100); // 0=left (red), 100=right (green)
  const r = 78;
  const cx = 100;
  const cy = 100;
  const needleX = cx + r * Math.cos(angle);
  const needleY = cy - r * Math.sin(angle);
  const label =
    v < 33 ? { text: "LOW", color: "#ef4444" } :
    v < 66 ? { text: "MEDIUM", color: "#eab308" } :
             { text: "HIGH", color: "#22c55e" };

  return (
    <div className="flex flex-col items-center gap-1 text-slate-200">
      <div className="flex items-baseline justify-between w-full">
        <span className="text-[11px] uppercase tracking-wider text-slate-400">Active Trade</span>
        <span className="text-sm font-bold text-cyan-300">{coin || "—"}</span>
      </div>
      <svg viewBox="0 0 200 130" className="w-full h-auto">
        <defs>
          <linearGradient id="confGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#ef4444" />
            <stop offset="50%" stopColor="#eab308" />
            <stop offset="100%" stopColor="#22c55e" />
          </linearGradient>
        </defs>
        {/* arc background */}
        <path
          d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
          stroke="url(#confGradient)"
          strokeWidth="16"
          strokeLinecap="round"
          fill="none"
        />
        {/* tick marks */}
        {[0, 25, 50, 75, 100].map((t) => {
          const a = Math.PI * (1 - t / 100);
          const x1 = cx + (r - 10) * Math.cos(a);
          const y1 = cy - (r - 10) * Math.sin(a);
          const x2 = cx + (r + 10) * Math.cos(a);
          const y2 = cy - (r + 10) * Math.sin(a);
          return <line key={t} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#475569" strokeWidth="1" />;
        })}
        {/* needle */}
        <line x1={cx} y1={cy} x2={needleX} y2={needleY} stroke="#f1f5f9" strokeWidth="3" strokeLinecap="round" />
        <circle cx={cx} cy={cy} r="6" fill="#f1f5f9" />
        <text x={cx} y={cy + 25} textAnchor="middle" fill="#e2e8f0" fontSize="22" fontWeight="bold">
          {v.toFixed(0)}
        </text>
        <text x={cx} y={cy + 42} textAnchor="middle" fill={label.color} fontSize="12" fontWeight="bold">
          {label.text} CONFIDENCE
        </text>
      </svg>
      <div className="flex items-center gap-2 text-xs text-slate-400 w-full">
        <span>{auto ? "Live" : "Manual"}</span>
        <input
          type="range"
          min={0}
          max={100}
          value={v}
          onChange={(e) => onManual(Number(e.target.value))}
          className="flex-1 accent-cyan-500"
          title="Override gauge (visual only)"
        />
        <button
          onClick={() => onManual(null)}
          className="text-cyan-400 hover:text-cyan-300 underline text-xs"
        >
          auto
        </button>
      </div>
    </div>
  );
}

// ---------- DeItaone X embed ----------

function DeItaoneFeed() {
  const containerRef = useRef(null);
  const [status, setStatus] = useState("loading"); // loading | loaded | blocked

  useEffect(() => {
    let cancelled = false;
    const handle = "DeItaone";

    const inject = () => {
      if (cancelled || !containerRef.current) return;
      const anchor = document.createElement("a");
      anchor.className = "twitter-timeline";
      anchor.setAttribute("data-theme", "dark");
      anchor.setAttribute("data-chrome", "noheader nofooter transparent");
      anchor.setAttribute("data-tweet-limit", "10");
      anchor.href = `https://twitter.com/${handle}`;
      anchor.textContent = `Tweets by @${handle}`;
      containerRef.current.innerHTML = "";
      containerRef.current.appendChild(anchor);
      if (window.twttr?.widgets?.load) {
        window.twttr.widgets.load(containerRef.current);
        setStatus("loaded");
      }
    };

    if (window.twttr?.widgets) {
      inject();
      return;
    }
    const existing = document.getElementById("twttr-wjs");
    if (!existing) {
      const s = document.createElement("script");
      s.id = "twttr-wjs";
      s.async = true;
      s.src = "https://platform.twitter.com/widgets.js";
      s.onload = inject;
      s.onerror = () => !cancelled && setStatus("blocked");
      document.body.appendChild(s);
    } else {
      existing.addEventListener("load", inject);
    }
    const t = setTimeout(() => {
      if (!cancelled && !window.twttr?.widgets) setStatus("blocked");
    }, 8000);
    return () => { cancelled = true; clearTimeout(t); };
  }, []);

  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-3 h-full flex flex-col">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
          <span className="text-sm font-bold text-slate-100">Breaking · @DeItaone</span>
        </div>
        <a
          href="https://twitter.com/DeItaone"
          target="_blank"
          rel="noreferrer"
          className="text-xs text-cyan-400 hover:text-cyan-300 underline"
        >
          open in X ↗
        </a>
      </div>
      <div ref={containerRef} className="flex-1 overflow-hidden rounded">
        {status !== "loaded" && (
          <div className="h-full flex items-center justify-center text-xs text-slate-500">
            {status === "blocked"
              ? "X embed blocked in this sandbox — tap 'open in X' above."
              : "Loading @DeItaone feed…"}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------- Main component ----------

export default function JarbisDashboard() {
  const [botUrl, setBotUrl] = useState(() => storage.get(K.botUrl, DEFAULTS.botUrl));
  const [secret, setSecret] = useState(() => storage.get(K.secret, DEFAULTS.secret));
  const [refreshSec, setRefreshSec] = useState(() =>
    Number(storage.get(K.refresh, DEFAULTS.refreshSec)),
  );
  const [selectedCoin, setSelectedCoin] = useState(() => storage.get(K.selected, "BTC"));
  const [manualConf, setManualConf] = useState(() => storage.get(K.manualConfidence, null));

  const [market, setMarket] = useState([]);
  const [marketError, setMarketError] = useState(null);
  const [state, setState] = useState(null);
  const [stateError, setStateError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [toast, setToast] = useState(null);

  useEffect(() => storage.set(K.botUrl, botUrl), [botUrl]);
  useEffect(() => storage.set(K.secret, secret), [secret]);
  useEffect(() => storage.set(K.refresh, refreshSec), [refreshSec]);
  useEffect(() => storage.set(K.selected, selectedCoin), [selectedCoin]);
  useEffect(() => storage.set(K.manualConfidence, manualConf), [manualConf]);

  // ---- data pumps ----

  const loadMarket = useCallback(async () => {
    try {
      const rows = await fetchHyperliquid();
      setMarket(rows);
      setMarketError(null);
    } catch (e) {
      setMarketError(e?.message || String(e));
    }
  }, []);

  const loadState = useCallback(async () => {
    try {
      const r = await getJson(`${botUrl}/state`);
      if (!r.ok) throw new Error(r.error || "state error");
      setState(r.state);
      setStateError(null);
    } catch (e) {
      setStateError(e?.message || String(e));
    }
  }, [botUrl]);

  useEffect(() => {
    loadMarket();
    loadState();
    setLastUpdate(new Date().toISOString());
    const ms = Math.max(2, refreshSec) * 1000;
    const id = setInterval(() => {
      loadMarket();
      loadState();
      setLastUpdate(new Date().toISOString());
    }, ms);
    return () => clearInterval(id);
  }, [loadMarket, loadState, refreshSec]);

  // ---- bot controls ----

  const postControl = async (path) => {
    setBusy(true);
    try {
      const r = await fetch(`${botUrl}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-JARBIS-Secret": secret },
        body: JSON.stringify({ confirm: true }),
      });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || !j.ok) throw new Error(j.error || `HTTP ${r.status}`);
      setToast({ kind: "ok", text: `→ ${path}` });
      await loadState();
    } catch (e) {
      setToast({ kind: "err", text: `${path}: ${e?.message || e}` });
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 4000);
    }
  };

  const toggleBot = () => postControl(state?.bot_active ? "/bot/stop" : "/bot/start");
  const emergency = () => {
    if (!window.confirm("Emergency flatten all positions?")) return;
    postControl("/emergency");
  };

  // ---- derived ----

  const marketBy = useMemo(() => {
    const m = new Map();
    for (const r of market) m.set(r.coin, r);
    return m;
  }, [market]);

  const activeCoin = state?.active_trade?.coin || state?.active_trade?.ticker || selectedCoin;
  const autoConfidence =
    state?.confidence?.[activeCoin] ??
    (state?.active_trade?.confidence) ??
    50;
  const confidence = manualConf != null ? manualConf : autoConfidence;
  const confidenceAuto = manualConf == null;

  const trading = state?.trading_pairs || TOP_COINS;
  const botActive = !!state?.bot_active;
  const mode = state?.mode || "PAPER";
  const venue = state?.venue || "hyperliquid";

  // ---- render ----

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-mono p-3 lg:p-4">
      <div className="max-w-[1280px] mx-auto space-y-3">
        {/* ---------- Header ---------- */}
        <header className="flex flex-wrap items-center justify-between gap-3 border border-slate-800 rounded-lg bg-gradient-to-r from-slate-900 to-slate-950 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="text-2xl font-extrabold tracking-tight text-cyan-400">
              JARBIS<span className="text-slate-500"> · crypto</span>
            </div>
            <span className={`px-2 py-0.5 rounded text-xs font-bold ${
              mode === "LIVE" ? "bg-red-600 text-white" : "bg-yellow-500 text-slate-900"
            }`}>{mode}</span>
            <span className="text-xs text-slate-400">venue:</span>
            <span className="text-xs font-bold text-cyan-300">{venue.toUpperCase()}</span>
            <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
              botActive ? "bg-green-600 text-white" : "bg-slate-700 text-slate-300"
            }`}>{botActive ? "BOT ACTIVE" : "BOT IDLE"}</span>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={toggleBot}
              disabled={busy || !state}
              className={`px-4 py-2 rounded font-bold text-white transition ${
                botActive
                  ? "bg-rose-600 hover:bg-rose-500"
                  : "bg-emerald-600 hover:bg-emerald-500"
              } disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              {busy ? "…" : botActive ? "STOP BOT" : "START BOT"}
            </button>
            <button
              onClick={emergency}
              disabled={busy}
              className="px-3 py-2 rounded bg-slate-800 hover:bg-red-700 border border-red-800 text-red-300 hover:text-white text-sm"
              title="Close every open position immediately"
            >
              ⛔ Emergency
            </button>
          </div>
        </header>

        {/* ---------- Connection / prefs strip ---------- */}
        <div className="flex flex-wrap items-center gap-2 text-xs bg-slate-900/40 border border-slate-800 rounded-lg px-3 py-2">
          <label className="flex items-center gap-2">
            <span className="text-slate-400">Bot URL</span>
            <input
              value={botUrl}
              onChange={(e) => setBotUrl(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 w-52 focus:border-cyan-500 outline-none"
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-slate-400">Secret</span>
            <input
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              type="password"
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1 w-40 focus:border-cyan-500 outline-none"
            />
          </label>
          <label className="flex items-center gap-2">
            <span className="text-slate-400">Refresh</span>
            <select
              value={refreshSec}
              onChange={(e) => setRefreshSec(Number(e.target.value))}
              className="bg-slate-800 border border-slate-700 rounded px-2 py-1"
            >
              <option value={2}>2s</option>
              <option value={5}>5s</option>
              <option value={15}>15s</option>
              <option value={30}>30s</option>
            </select>
          </label>
          <span className="ml-auto text-slate-500">
            last poll <span className="text-slate-300">{fmt.time(lastUpdate)}</span>
          </span>
          {marketError && (
            <span className="text-amber-400">market err: {marketError}</span>
          )}
          {stateError && (
            <span className="text-red-400">bot err: {stateError}</span>
          )}
          {toast && (
            <span className={toast.kind === "ok" ? "text-green-400" : "text-red-400"}>
              {toast.text}
            </span>
          )}
        </div>

        {/* ---------- Stat tiles ---------- */}
        <section className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <StatTile label="Balance" value={fmt.price(state?.balance)} />
          <StatTile label="Unrealized P&L" value={fmt.price(state?.unrealized_pnl)} tone={(state?.unrealized_pnl ?? 0) >= 0 ? "pos" : "neg"} />
          <StatTile label="Portfolio heat" value={state ? `${(state.portfolio_heat * 100).toFixed(1)}%` : "—"} tone={(state?.portfolio_heat ?? 0) > 0.7 ? "warn" : ""} />
          <StatTile label="Available margin" value={fmt.price(state?.available_margin)} />
        </section>

        {/* ---------- Row: positions | confidence | news ---------- */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {/* Positions */}
          <div className="lg:col-span-2 bg-slate-900/40 border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-bold text-slate-200">Open positions</div>
              <div className="text-xs text-slate-500">
                {state?.positions?.length || 0} open · max concurrent 4
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-400 uppercase text-[10px]">
                  <tr>
                    <th className="text-left py-1">Coin</th>
                    <th className="text-left">Dir</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Entry</th>
                    <th className="text-right">Now</th>
                    <th className="text-right">Lev</th>
                    <th className="text-right">SL</th>
                    <th className="text-right">TP1</th>
                    <th className="text-right">TP2</th>
                    <th className="text-right">P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {(!state || state.positions.length === 0) && (
                    <tr><td colSpan={10} className="text-center text-slate-500 py-4">
                      {state ? "No open positions." : "Waiting for bot…"}
                    </td></tr>
                  )}
                  {state?.positions?.map((p) => (
                    <tr
                      key={p.ticker}
                      className={`border-t border-slate-800 cursor-pointer hover:bg-slate-800/50 ${
                        p.ticker === activeCoin ? "bg-slate-800/70" : ""
                      }`}
                      onClick={() => setSelectedCoin(p.ticker)}
                    >
                      <td className="py-1 font-bold text-cyan-300">{p.ticker}</td>
                      <td className={p.direction === "long" ? "text-green-400" : "text-red-400"}>
                        {p.direction.toUpperCase()}
                      </td>
                      <td className="text-right">{p.quantity.toFixed(4)}</td>
                      <td className="text-right">{fmt.price(p.entry)}</td>
                      <td className="text-right">{fmt.price(p.current)}</td>
                      <td className="text-right text-yellow-300">{p.leverage.toFixed(2)}x</td>
                      <td className="text-right text-slate-400">{fmt.price(p.stop_loss)}</td>
                      <td className={`text-right ${p.tp1_hit ? "text-green-500 line-through" : "text-slate-300"}`}>
                        {fmt.price(p.tp1)}
                      </td>
                      <td className="text-right text-slate-300">{fmt.price(p.tp2)}</td>
                      <td className={`text-right ${p.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {fmt.price(p.pnl)} ({fmt.pct((p.pnl_pct || 0) * 100)})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Confidence */}
          <div className="bg-slate-900/40 border border-slate-800 rounded-lg p-3">
            <ConfidenceGauge
              value={confidence}
              coin={activeCoin}
              auto={confidenceAuto}
              onManual={(v) => setManualConf(v)}
            />
            <div className="mt-2 grid grid-cols-2 gap-1 text-[11px]">
              {TOP_COINS.map((c) => {
                const conf = state?.confidence?.[c];
                const active = c === activeCoin;
                return (
                  <button
                    key={c}
                    onClick={() => setSelectedCoin(c)}
                    className={`flex items-center justify-between px-2 py-1 rounded border transition ${
                      active ? "border-cyan-500 bg-slate-800" : "border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    <span className="font-bold text-slate-200">{c}</span>
                    <span className={conf == null ? "text-slate-600" : conf < 33 ? "text-red-400" : conf < 66 ? "text-yellow-400" : "text-green-400"}>
                      {conf == null ? "—" : Math.round(conf)}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

        {/* ---------- Row: markets | sentiment/leverage ---------- */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div className="lg:col-span-2 bg-slate-900/40 border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-bold text-slate-200">
                Hyperliquid · top 10 perpetuals
              </div>
              <div className="text-xs text-slate-500">
                trading universe: {trading.length}/10
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-400 uppercase text-[10px]">
                  <tr>
                    <th className="text-left py-1">Coin</th>
                    <th className="text-right">Price</th>
                    <th className="text-right">24h %</th>
                    <th className="text-right">Max Lev</th>
                    <th className="text-right">Funding</th>
                    <th className="text-right">Dyn Lev</th>
                    <th className="text-right">Sentiment</th>
                    <th className="text-right">Day Vol</th>
                  </tr>
                </thead>
                <tbody>
                  {TOP_COINS.map((coin) => {
                    const m = marketBy.get(coin);
                    const dyn = state?.leverage?.[coin];
                    const sent = state?.sentiment?.[coin];
                    const inUniverse = trading.includes(coin);
                    return (
                      <tr
                        key={coin}
                        className={`border-t border-slate-800 ${inUniverse ? "" : "opacity-40"} ${
                          coin === activeCoin ? "bg-slate-800/50" : ""
                        } cursor-pointer hover:bg-slate-800/40`}
                        onClick={() => setSelectedCoin(coin)}
                      >
                        <td className="py-1 font-bold text-cyan-300">{coin}</td>
                        <td className="text-right">{fmt.price(m?.price)}</td>
                        <td className={`text-right ${((m?.change24h ?? 0) >= 0) ? "text-green-400" : "text-red-400"}`}>
                          {fmt.pct(m?.change24h)}
                        </td>
                        <td className="text-right text-yellow-300">{fmt.lev(m?.maxLeverage)}</td>
                        <td className={`text-right ${((m?.funding ?? 0) >= 0) ? "text-green-400" : "text-red-400"}`}>
                          {fmt.pct((m?.funding ?? 0) * 100, 4)}
                        </td>
                        <td className="text-right text-cyan-200">{dyn ? `${dyn.toFixed(2)}x` : "—"}</td>
                        <td className={`text-right ${
                          !sent ? "text-slate-500" :
                          sent.score >= 0.15 ? "text-green-400" :
                          sent.score <= -0.15 ? "text-red-400" : "text-slate-300"
                        }`}>
                          {sent ? `${sent.score.toFixed(2)} (${sent.label})` : "—"}
                        </td>
                        <td className="text-right text-slate-400">{fmt.vol(m?.dayVolume)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* DeItaone */}
          <DeItaoneFeed />
        </section>

        {/* ---------- Recent trades + stats ---------- */}
        <section className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          <div className="lg:col-span-2 bg-slate-900/40 border border-slate-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-bold text-slate-200">Recent trades</div>
              <div className="text-xs text-slate-500">last 10</div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-400 uppercase text-[10px]">
                  <tr>
                    <th className="text-left py-1">Time</th>
                    <th className="text-left">Coin</th>
                    <th className="text-left">Dir</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Entry</th>
                    <th className="text-right">Exit</th>
                    <th className="text-right">Lev</th>
                    <th className="text-right">P&amp;L</th>
                    <th className="text-left">Exit why</th>
                  </tr>
                </thead>
                <tbody>
                  {(!state || state.recent_trades.length === 0) && (
                    <tr><td colSpan={9} className="text-center text-slate-500 py-4">
                      No trades yet.
                    </td></tr>
                  )}
                  {state?.recent_trades?.map((t, i) => (
                    <tr key={i} className="border-t border-slate-800">
                      <td className="py-1 text-slate-500">{fmt.time(t.entry_time)}</td>
                      <td className="text-cyan-300 font-bold">{t.ticker}</td>
                      <td className={t.direction === "long" ? "text-green-400" : "text-red-400"}>
                        {t.direction}
                      </td>
                      <td className="text-right">{t.quantity?.toFixed(4)}</td>
                      <td className="text-right">{fmt.price(t.entry)}</td>
                      <td className="text-right">{t.exit ? fmt.price(t.exit) : "—"}</td>
                      <td className="text-right text-yellow-300">{t.leverage?.toFixed(2)}x</td>
                      <td className={`text-right ${(t.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                        {t.pnl == null ? "—" : fmt.price(t.pnl)}
                      </td>
                      <td className="text-slate-400">{t.exit_reason || "open"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="bg-slate-900/40 border border-slate-800 rounded-lg p-3">
            <div className="text-sm font-bold text-slate-200 mb-2">Stats (last 50)</div>
            <dl className="text-xs space-y-1">
              <Stat k="Total trades" v={state?.stats?.total_trades ?? 0} />
              <Stat k="Win rate" v={state ? `${(state.stats.win_rate * 100).toFixed(1)}%` : "—"}
                    tone={state?.stats?.win_rate >= 0.55 ? "pos" : state?.stats?.win_rate < 0.4 ? "neg" : ""} />
              <Stat k="Total P&L" v={fmt.price(state?.stats?.total_pnl)}
                    tone={(state?.stats?.total_pnl ?? 0) >= 0 ? "pos" : "neg"} />
              <Stat k="Best trade" v={fmt.price(state?.stats?.best)} tone="pos" />
              <Stat k="Worst trade" v={fmt.price(state?.stats?.worst)} tone="neg" />
              <Stat k="Max loss / trade" v={state ? `${(state.max_loss_pct * 100).toFixed(2)}%` : "—"} />
              <Stat k="Leverage cap" v={state ? `${state.max_leverage.toFixed(1)}x` : "—"} />
              <Stat k="Base leverage" v={state ? `${state.base_leverage.toFixed(1)}x` : "—"} />
            </dl>
          </div>
        </section>

        {/* ---------- Footer ---------- */}
        <footer className="text-[11px] text-slate-600 flex items-center justify-between pb-2">
          <span>JARBIS Crypto · Hyperliquid · Metamask self-custody · no KYC</span>
          <span>Prefs persist via <code>window.storage</code></span>
        </footer>
      </div>
    </div>
  );
}

// ---------- Small presentational helpers ----------

function StatTile({ label, value, tone }) {
  const color =
    tone === "pos" ? "text-green-400" :
    tone === "neg" ? "text-red-400" :
    tone === "warn" ? "text-amber-400" : "text-slate-100";
  return (
    <div className="bg-slate-900/40 border border-slate-800 rounded-lg px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value ?? "—"}</div>
    </div>
  );
}

function Stat({ k, v, tone }) {
  const color =
    tone === "pos" ? "text-green-400" :
    tone === "neg" ? "text-red-400" : "text-slate-100";
  return (
    <div className="flex justify-between">
      <dt className="text-slate-400">{k}</dt>
      <dd className={`font-bold ${color}`}>{v ?? "—"}</dd>
    </div>
  );
}
