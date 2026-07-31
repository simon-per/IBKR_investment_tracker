# Browser checks

Six Playwright scripts covering what unit tests structurally cannot see: keyboard and ARIA on the
real page, the production CSP, the shape of the built bundle, and how the UI behaves when the
backend is down.

These earned their place. The prod-snapshot + browser pass they came from found **three defects that
442 passing backend tests did not** — trades converted with only the EUR→base factor (a CAD realized
gain read 62% high), 67 BUY rows asserting a `0.00` realized result, and fractional share counts
rounding to `0`/`-0`. All three are pinned in `ledger.mjs`.

## Why this is a separate package

It cannot be a `frontend` devDependency: `deploy.sh` runs `npm ci` inside `frontend/` on every
`--no-cache` rebuild, and Playwright's postinstall pulls ~150 MB of Chromium — which would tax a
deploy that already runs every 10 minutes. Nothing in the deploy path touches this directory.

```bash
cd e2e && npm install && npx playwright install chromium
```

## Preconditions differ per script — read these

Most need a dev server on `localhost:5173`. **Check which port Vite actually took**: if 5173 is
occupied it silently moves to 5174, and `frontend/.env` points `VITE_API_URL` at `localhost:8000`,
so only origins listed in `CORS_ORIGINS` work — any other port fails every request with a CORS error
that looks exactly like a backend outage.

Set `SCHEDULER_ENABLED=false` in `backend/.env` for any local run, or starting uvicorn arms the five
daily jobs against the live Flex token and Yahoo.

| Script | Needs |
|---|---|
| `npm run a11y` | dev server; backend optional |
| `npm run sweep` | dev server + backend with data |
| `npm run csp` | `vite preview` on 4173 (**built output**, not the dev server) |
| `npm run ledger` | dev server + backend on a **production snapshot** |
| `npm run errors` | dev server, backend **deliberately stopped** |
| `npm run chunks` | `npm run build && npx vite preview --port 4173` in `frontend/`; no backend |

`BASE` and `PREVIEW` override the URLs.

`ledger.mjs` asserts against real account shapes — transfers badged *not money in*, fractional
quantities, a deposit row. The checked-in `portfolio.db` predates trades, cash flows and the IBKR
dividend era, so every assertion in it fails there. Take a snapshot with `sqlite3 .backup` on the
VPS, point `DATABASE_URL` at it, and **delete it afterwards**: it is real account data.

`chunks.mjs` runs against the *built* output because chunk boundaries do not exist in the dev
server. It also fails deliberately if someone lazy-loads Recharts — three components on the default
Performance tab use it, so deferring it moves the wait rather than removing it.

`csp.mjs` runs against the built output for a subtler reason: **the dev server cannot pass a strict
CSP and never could.** Vite injects an inline `<script type="module">` for react-refresh, which
`script-src 'self'` blocks — so pointing this at :5173 reports a violation that does not exist in
production, where nginx serves a build containing no inline scripts. A CSP check against a dev
server tests the HMR transport, not the policy.

## Output

Each script prints `PASS`/`FAIL` lines and exits non-zero on any failure, so they compose in a shell
loop. They are not wired into CI: CI has no browser, no snapshot and no backend, and a suite that
cannot run is worse than one you have to invoke.

Screenshots are gitignored — they contain real account data and this repo is public.
