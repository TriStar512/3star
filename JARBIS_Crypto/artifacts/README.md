# Live Artifacts

Single-file React components that run as Claude Live Artifacts or drop
into any React app. No build step, no external deps beyond React.
Prefs persist via `window.storage` → `localStorage` → in-memory.

## `JarbisDashboard.jsx`

The live dashboard that pairs with the running JARBIS Python bot on your
PC. Sized for a half-screen 1280×1440 viewport on a 32" 1440p monitor;
collapses gracefully to narrower widths.

**Panels**
- Header: mode (PAPER/LIVE), venue (HYPERLIQUID), bot status chip,
  **START / STOP bot** button, **Emergency** flatten button.
- Connection strip: bot URL, webhook secret, refresh cadence.
- Stat tiles: balance, unrealized P&L, portfolio heat, available margin.
- Open positions table (click a row to focus the confidence gauge).
- **Active-trade confidence gauge**: gradient arc red (0) → yellow (50)
  → green (100), with per-coin confidence chips and a manual override
  slider (visual only).
- Hyperliquid top-10 markets: price, 24h %, max leverage, funding,
  dynamic-leverage estimate, sentiment, day volume.
- **@DeItaone** breaking-news embed (official X/Twitter widget; graceful
  fallback + "open in X" link if embeds are blocked).
- Recent trades table (last 10) + stats panel (win rate, best/worst, etc.).

**Backend it talks to**
- `GET  /state`       → bot snapshot (public; CORS `*`)
- `POST /bot/start`   → resume new entries (auth: `X-JARBIS-Secret`)
- `POST /bot/stop`    → pause new entries (auth: `X-JARBIS-Secret`)
- `POST /emergency`   → panic flatten (auth: `X-JARBIS-Secret`)
- Public Hyperliquid `POST https://api.hyperliquid.xyz/info` for market data

**Persistence keys** (`window.storage`):
- `jarbis.botUrl`, `jarbis.secret`, `jarbis.refresh`
- `jarbis.selectedCoin`, `jarbis.manualConfidence`

**Usage**
- **Claude Live Artifact**: paste the file contents into a React artifact.
  Default export: `JarbisDashboard`, no props.
- **Standalone React**: `import JarbisDashboard from './JarbisDashboard'`.

Run the bot with `python -m JARBIS_Crypto.main --paper`; the dashboard
polls `http://127.0.0.1:5000/state` by default.
