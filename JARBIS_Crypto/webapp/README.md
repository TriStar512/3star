# JARBIS Crypto — iPad PWA (work in progress)

Installable Progressive Web App so the dashboard launches full-screen
from the iPad home screen and pairs with the bot running on your PC
over the local network.

**Status: scaffold only.** The HTML shell, manifest, and iOS meta tags
are in place; the React app body (`app.js`), the PNG icons, and the
Flask `/app` static route still need to be written. See the project
TODO list (`Resume iPad PWA build`).

## Files

| File | Purpose | Status |
|---|---|---|
| `index.html` | Entry shell with iOS PWA meta + Tailwind + React via CDN | scaffold |
| `manifest.webmanifest` | Installable web-app metadata | scaffold |
| `app.js` | Dashboard React component (mobile-tuned port of `JarbisDashboard.jsx`) | not yet written |
| `icons/icon-192.png` | Manifest icon | TODO |
| `icons/icon-512.png` | Manifest icon | TODO |
| `icons/icon-512-maskable.png` | Maskable variant | TODO |
| `icons/apple-touch-icon.png` | iOS home-screen icon (180×180) | TODO |

## Planned install flow (target)

1. Bot runs on PC: `python -m JARBIS_Crypto.main --paper`
2. Bot prints LAN URL: `dashboard at http://192.168.x.x:5000/app`
3. Open Safari on iPad → that URL → Share → Add to Home Screen
4. Launch from home screen → fullscreen PWA, polls `/state` over LAN

## When resuming

- Port `JarbisDashboard.jsx` to `app.js` with browser globals
  (`const { useState, … } = React`) instead of ESM imports.
- Beef up tap targets (44px min), single-column portrait layout, no
  hover-only interactions.
- Generate icons with Pillow (script idea: `generate_icons.py`).
- Extend `webhooks.py` with `GET /app` and `GET /app/<path:subpath>`
  routes, plus a startup log line printing the LAN IP + URL.
- Confirm CORS already covers the iPad case (it does — `*` works for
  same-origin and cross-origin alike).
