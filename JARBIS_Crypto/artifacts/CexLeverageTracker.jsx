/**
 * CEX Leverage Tracker — Live Artifact
 *
 * Persistent dashboard that ranks the top-10 most liquid perpetuals by
 * funding / spread / max leverage on the CEX offering the highest leverage
 * (Bybit or OKX, 100x+). Public REST only — no auth required.
 *
 * Paste into a Claude Live Artifact (React) or mount in any React app:
 *   <CexLeverageTracker />
 *
 * Persistence: prefers window.storage (Claude Artifacts), falls back to
 *   window.localStorage. Keys: "cex", "refresh", "lastUpdate", "sort".
 *
 * Refresh: every N seconds (default 30); full state refresh, no page reload.
 *
 * Columns (all sortable): Coin, Price, 24h %, 24h Vol, Max Lev, Funding,
 *   Spread, Bid, Ask.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";

// -------- Config --------

const TOP_COINS = ["BTC", "ETH", "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "MATIC"];
const DEFAULT_CEX = "bybit";
const DEFAULT_REFRESH_SEC = 30;
const STORAGE_KEYS = {
  cex: "cex_leverage_tracker.cex",
  refresh: "cex_leverage_tracker.refresh",
  lastUpdate: "cex_leverage_tracker.lastUpdate",
  sort: "cex_leverage_tracker.sort",
};

// -------- Storage shim (window.storage → localStorage → memory) --------

const memoryStore = {};
const storage = {
  get(key, fallback) {
    try {
      if (typeof window !== "undefined" && window.storage?.getItem) {
        const raw = window.storage.getItem(key);
        if (raw != null) return JSON.parse(raw);
      } else if (typeof window !== "undefined" && window.localStorage) {
        const raw = window.localStorage.getItem(key);
        if (raw != null) return JSON.parse(raw);
      } else if (key in memoryStore) {
        return memoryStore[key];
      }
    } catch (e) {
      /* swallow quota/JSON errors */
    }
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
        memoryStore[key] = value;
      }
    } catch (e) {
      /* quota full — fall back to memory */
      memoryStore[key] = value;
    }
  },
};

// -------- Fetchers --------

async function getJSON(url, timeoutMs = 10000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

async function fetchBybit() {
  const [tickers, instruments] = await Promise.all([
    getJSON("https://api.bybit.com/v5/market/tickers?category=linear"),
    getJSON("https://api.bybit.com/v5/market/instruments-info?category=linear"),
  ]);
  if (tickers.retCode !== 0) throw new Error(tickers.retMsg || "bybit tickers error");
  if (instruments.retCode !== 0) throw new Error(instruments.retMsg || "bybit instruments error");

  const levMap = {};
  for (const it of instruments.result?.list || []) {
    levMap[it.symbol] = Number(it.leverageFilter?.maxLeverage || 0);
  }

  const bySymbol = new Map((tickers.result?.list || []).map((t) => [t.symbol, t]));
  const rows = [];
  for (const coin of TOP_COINS) {
    const sym = `${coin}USDT`;
    const t = bySymbol.get(sym);
    if (!t) continue;
    const bid = Number(t.bid1Price || 0);
    const ask = Number(t.ask1Price || 0);
    const mid = bid && ask ? (ask + bid) / 2 : 0;
    const spreadPct = mid ? ((ask - bid) / mid) * 100 : 0;
    rows.push({
      coin,
      symbol: sym,
      price: Number(t.lastPrice || 0),
      change24h: Number(t.price24hPcnt || 0) * 100,
      volume24h: Number(t.turnover24h || 0),
      maxLeverage: levMap[sym] || 0,
      fundingRate: Number(t.fundingRate || 0),
      spread: spreadPct,
      bid,
      ask,
    });
  }
  return rows;
}

async function fetchOKX() {
  const [tickers, instruments] = await Promise.all([
    getJSON("https://www.okx.com/api/v5/market/tickers?instType=SWAP"),
    getJSON("https://www.okx.com/api/v5/public/instruments?instType=SWAP"),
  ]);

  const levMap = {};
  for (const it of instruments.data || []) {
    levMap[it.instId] = Number(it.lever || 0);
  }

  const byId = new Map((tickers.data || []).map((t) => [t.instId, t]));

  const fundingPromises = TOP_COINS.map((coin) =>
    getJSON(`https://www.okx.com/api/v5/public/funding-rate?instId=${coin}-USDT-SWAP`).catch(
      () => ({ data: [] }),
    ),
  );
  const fundingResults = await Promise.all(fundingPromises);
  const fundingMap = {};
  fundingResults.forEach((res, i) => {
    const fr = res.data?.[0];
    if (fr) fundingMap[`${TOP_COINS[i]}-USDT-SWAP`] = Number(fr.fundingRate || 0);
  });

  const rows = [];
  for (const coin of TOP_COINS) {
    const instId = `${coin}-USDT-SWAP`;
    const t = byId.get(instId);
    if (!t) continue;
    const bid = Number(t.bidPx || 0);
    const ask = Number(t.askPx || 0);
    const mid = bid && ask ? (ask + bid) / 2 : 0;
    const spreadPct = mid ? ((ask - bid) / mid) * 100 : 0;
    const last = Number(t.last || 0);
    const open = Number(t.open24h || last);
    const change24h = open ? ((last - open) / open) * 100 : 0;
    rows.push({
      coin,
      symbol: instId,
      price: last,
      change24h,
      volume24h: Number(t.volCcy24h || 0),
      maxLeverage: levMap[instId] || 0,
      fundingRate: fundingMap[instId] || 0,
      spread: spreadPct,
      bid,
      ask,
    });
  }
  return rows;
}

const FETCHERS = { bybit: fetchBybit, okx: fetchOKX };
const CEX_LABEL = { bybit: "Bybit", okx: "OKX" };

// -------- Formatters --------

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
  pct(v, decimals = 2) {
    if (v == null || Number.isNaN(v)) return "—";
    const sign = v >= 0 ? "+" : "";
    return `${sign}${v.toFixed(decimals)}%`;
  },
  lev(v) {
    return v ? `${Math.round(v)}x` : "—";
  },
  time(iso) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleTimeString();
    } catch {
      return "—";
    }
  },
};

// -------- Component --------

export default function CexLeverageTracker() {
  const [cex, setCex] = useState(() => storage.get(STORAGE_KEYS.cex, DEFAULT_CEX));
  const [refreshSec, setRefreshSec] = useState(() =>
    Number(storage.get(STORAGE_KEYS.refresh, DEFAULT_REFRESH_SEC)),
  );
  const [rows, setRows] = useState([]);
  const [lastUpdate, setLastUpdate] = useState(() => storage.get(STORAGE_KEYS.lastUpdate, null));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const initialSort = storage.get(STORAGE_KEYS.sort, { key: "volume24h", dir: "desc" });
  const [sortKey, setSortKey] = useState(initialSort.key);
  const [sortDir, setSortDir] = useState(initialSort.dir);

  useEffect(() => storage.set(STORAGE_KEYS.cex, cex), [cex]);
  useEffect(() => storage.set(STORAGE_KEYS.refresh, refreshSec), [refreshSec]);
  useEffect(() => storage.set(STORAGE_KEYS.lastUpdate, lastUpdate), [lastUpdate]);
  useEffect(
    () => storage.set(STORAGE_KEYS.sort, { key: sortKey, dir: sortDir }),
    [sortKey, sortDir],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fetcher = FETCHERS[cex] || fetchBybit;
      const data = await fetcher();
      setRows(data);
      setLastUpdate(new Date().toISOString());
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [cex]);

  useEffect(() => {
    load();
    const ms = Math.max(5, refreshSec) * 1000;
    const id = setInterval(load, ms);
    return () => clearInterval(id);
  }, [load, refreshSec]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      let cmp;
      if (typeof av === "string" && typeof bv === "string") {
        cmp = av.localeCompare(bv);
      } else {
        cmp = (av ?? 0) - (bv ?? 0);
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  };

  const columns = [
    { key: "coin", label: "Coin", align: "left" },
    { key: "price", label: "Price", align: "right" },
    { key: "change24h", label: "24h %", align: "right" },
    { key: "volume24h", label: "24h Vol", align: "right" },
    { key: "maxLeverage", label: "Max Lev", align: "right" },
    { key: "fundingRate", label: "Funding (8h)", align: "right" },
    { key: "spread", label: "Spread", align: "right" },
    { key: "bid", label: "Bid", align: "right" },
    { key: "ask", label: "Ask", align: "right" },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 font-mono p-4 sm:p-6">
      <div className="max-w-[1280px] mx-auto">
        {/* Header */}
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 mb-4">
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-cyan-400">CEX Leverage Tracker</h1>
            <p className="text-xs text-slate-400">
              Top 10 perpetuals · highest-leverage venues · public REST
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <label className="flex items-center gap-2">
              <span className="text-slate-400">CEX</span>
              <select
                value={cex}
                onChange={(e) => setCex(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 focus:outline-none focus:border-cyan-500"
              >
                <option value="bybit">Bybit</option>
                <option value="okx">OKX</option>
              </select>
            </label>
            <label className="flex items-center gap-2">
              <span className="text-slate-400">Refresh</span>
              <select
                value={refreshSec}
                onChange={(e) => setRefreshSec(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 rounded px-2 py-1 focus:outline-none focus:border-cyan-500"
              >
                <option value={10}>10s</option>
                <option value={30}>30s</option>
                <option value={60}>60s</option>
                <option value={300}>5m</option>
              </select>
            </label>
            <button
              onClick={load}
              disabled={loading}
              className="px-3 py-1 bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:cursor-not-allowed rounded text-white transition"
            >
              {loading ? "Loading…" : "Refresh now"}
            </button>
          </div>
        </header>

        {/* Status strip */}
        <div className="flex flex-wrap items-center gap-4 text-xs text-slate-400 mb-3">
          <span>
            Last update:{" "}
            <span className="text-slate-200">{fmt.time(lastUpdate)}</span>
          </span>
          <span>
            Exchange: <span className="text-cyan-400">{CEX_LABEL[cex] || cex}</span>
          </span>
          <span>
            Rows: <span className="text-slate-200">{sorted.length}</span>
          </span>
          <span>
            Sort:{" "}
            <span className="text-slate-200">
              {sortKey} {sortDir}
            </span>
          </span>
          {error && (
            <span className="text-red-400">
              ⚠ {error}
              <button
                onClick={load}
                className="ml-2 underline hover:text-red-300"
              >
                retry
              </button>
            </span>
          )}
        </div>

        {/* Table */}
        <div className="overflow-x-auto border border-slate-800 rounded-lg bg-slate-950/60">
          <table className="w-full text-sm">
            <thead className="bg-slate-900 text-slate-300 text-xs uppercase tracking-wider">
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.key}
                    onClick={() => toggleSort(c.key)}
                    className={`px-3 py-2 cursor-pointer select-none hover:text-cyan-400 ${
                      c.align === "right" ? "text-right" : "text-left"
                    }`}
                  >
                    {c.label}
                    {sortKey === c.key && (
                      <span className="ml-1 text-cyan-400">
                        {sortDir === "asc" ? "▲" : "▼"}
                      </span>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && rows.length === 0 && (
                <tr>
                  <td colSpan={columns.length} className="text-center py-12 text-slate-500">
                    Loading top-10 perpetuals from {CEX_LABEL[cex]}…
                  </td>
                </tr>
              )}
              {!loading && rows.length === 0 && error && (
                <tr>
                  <td colSpan={columns.length} className="text-center py-12 text-red-400">
                    Could not fetch data. Check network / CORS and try again.
                  </td>
                </tr>
              )}
              {!loading && rows.length === 0 && !error && (
                <tr>
                  <td colSpan={columns.length} className="text-center py-12 text-slate-500">
                    No rows.
                  </td>
                </tr>
              )}
              {sorted.map((r) => (
                <tr
                  key={r.coin}
                  className="border-t border-slate-800 hover:bg-slate-900/60 transition"
                >
                  <td className="px-3 py-2 font-bold text-cyan-300">{r.coin}</td>
                  <td className="px-3 py-2 text-right text-slate-100">{fmt.price(r.price)}</td>
                  <td
                    className={`px-3 py-2 text-right ${
                      r.change24h >= 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {fmt.pct(r.change24h)}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300">{fmt.vol(r.volume24h)}</td>
                  <td className="px-3 py-2 text-right font-bold text-yellow-400">
                    {fmt.lev(r.maxLeverage)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right ${
                      r.fundingRate >= 0 ? "text-green-400" : "text-red-400"
                    }`}
                  >
                    {fmt.pct(r.fundingRate * 100, 4)}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-300">
                    {fmt.pct(r.spread, 3)}
                  </td>
                  <td className="px-3 py-2 text-right text-slate-400">{fmt.price(r.bid)}</td>
                  <td className="px-3 py-2 text-right text-slate-400">{fmt.price(r.ask)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <footer className="text-xs text-slate-600 mt-4 flex items-center justify-between">
          <span>
            Click any column header to sort · prefs persist via{" "}
            <code className="text-slate-400">window.storage</code>
          </span>
          <span>Auto-refresh every {refreshSec}s</span>
        </footer>
      </div>
    </div>
  );
}
