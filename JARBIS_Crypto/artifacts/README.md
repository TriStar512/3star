# Live Artifacts

Standalone React components designed to run as Claude Live Artifacts
(or dropped into any React app). Each one is a single file with no
build step, no external deps beyond React, and uses `window.storage`
(with `localStorage` fallback) for cross-session persistence.

## `CexLeverageTracker.jsx`

Tracks the top-10 most liquid perpetuals on the CEX offering the
highest leverage (Bybit / OKX). Public REST only — no auth required.

**Columns (all sortable):** Coin · Price · 24h % · 24h Vol ·
Max Leverage · Funding (8h) · Spread · Bid · Ask.

**Controls:** exchange dropdown (Bybit / OKX), refresh interval
(10s / 30s / 60s / 5m), manual refresh button.

**Persistence keys** (`window.storage`):
- `cex_leverage_tracker.cex`
- `cex_leverage_tracker.refresh`
- `cex_leverage_tracker.lastUpdate`
- `cex_leverage_tracker.sort`

**Assets tracked:** BTC, ETH, BNB, SOL, XRP, ADA, DOGE, AVAX, LINK, MATIC
(USDT-quoted perpetuals).

**Usage in a Live Artifact:** paste the file contents into a React
artifact; it exports `CexLeverageTracker` as the default component.

**Endpoints used:**
- Bybit: `v5/market/tickers` + `v5/market/instruments-info`
- OKX: `v5/market/tickers` + `v5/public/instruments` + `v5/public/funding-rate` (per coin)
