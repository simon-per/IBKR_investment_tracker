# Deployment, Backup & Restore Runbook

Operational guide for running the IBKR Portfolio Analyzer on a server (Hostinger VPS)
and for wiping / rebuilding it without losing data.

- **Live URL:** https://portfolio.srv1211053.hstgr.cloud
- **Repo on server:** `/root/IBKR_investment_tracker`
- **SSH:** `ssh -i ~/.ssh/id_ed25519_hostinger root@portfolio.srv1211053.hstgr.cloud`
- **Stack:** Docker Compose — Traefik (TLS) + FastAPI backend + nginx (built frontend)

## What is and isn't in git

**In git (restored by `git clone`):** all app code, `frontend/.env.production`
(empty `VITE_API_URL` → frontend calls `/api/*` same-origin), `backend/frontend-nginx.conf`,
`backend/docker-compose.yml`, `deploy.sh`, `backend/.env.example`.

**NOT in git — back these up before wiping:**

| Path on server | Contents | Notes |
|---|---|---|
| `backend/portfolio.db` | All portfolio data (securities, tax lots, prices, FX, dividends, fundamentals, etc.) | SQLite, **WAL mode** — stop the backend before copying |
| `backend/.env` | Secrets: `IBKR_TOKEN`, `IBKR_QUERY_ID`, etc. | Can also be rebuilt from `backend/.env.example` |
| `traefik_data` docker volume | Let's Encrypt certs (`acme.json`) | Optional — Traefik re-issues automatically on fresh setup |

---

## 1. Back up (run BEFORE wiping the VPS)

Run from your local machine (PowerShell). Stopping the backend first lets SQLite
checkpoint the WAL into the main `.db` file so the copy is consistent.

```powershell
# a) Stop the backend on the VPS (checkpoints WAL → portfolio.db)
ssh -i ~/.ssh/id_ed25519_hostinger root@portfolio.srv1211053.hstgr.cloud `
  "cd /root/IBKR_investment_tracker/backend && docker compose stop portfolio-backend"

# b) Pull the database and secrets into a local backup folder
mkdir -Force "$HOME\ibkr-backups"
scp -i ~/.ssh/id_ed25519_hostinger `
  root@portfolio.srv1211053.hstgr.cloud:/root/IBKR_investment_tracker/backend/portfolio.db `
  "$HOME\ibkr-backups\portfolio.db"
scp -i ~/.ssh/id_ed25519_hostinger `
  root@portfolio.srv1211053.hstgr.cloud:/root/IBKR_investment_tracker/backend/.env `
  "$HOME\ibkr-backups\backend.env"
```

Verify the DB copied intact (size > 0, and it opens):

```powershell
Get-Item "$HOME\ibkr-backups\portfolio.db" | Select-Object Length
```

> Optional, no shutdown needed: an online snapshot instead of stopping the backend —
> `ssh ... "cd /root/IBKR_investment_tracker/backend && docker compose exec -T portfolio-backend python -c \"import sqlite3; sqlite3.connect('portfolio.db').backup(sqlite3.connect('portfolio.backup.db'))\""` then scp `portfolio.backup.db`.

---

## 2. Fresh server setup (new / wiped VPS)

Prereqs: Docker + Docker Compose plugin, git, and **DNS A record**
`portfolio.srv1211053.hstgr.cloud` → the new server IP (required so Traefik can get a TLS cert).

```bash
# Install Docker if missing:  curl -fsSL https://get.docker.com | sh
cd /root
git clone git@github.com:simon-per/IBKR_investment_tracker.git
cd IBKR_investment_tracker

# Secrets: restore the backup, or create from template
cp backend/.env.example backend/.env   # then edit, OR scp your backup over it (step 3)
```

---

## 3. Restore data, then deploy

Push the backups from your machine up to the new server **before** the first `docker compose up`:

```powershell
# .env (secrets)
scp -i ~/.ssh/id_ed25519_hostinger "$HOME\ibkr-backups\backend.env" `
  root@portfolio.srv1211053.hstgr.cloud:/root/IBKR_investment_tracker/backend/.env

# database (must be a FILE at this exact path before containers start)
scp -i ~/.ssh/id_ed25519_hostinger "$HOME\ibkr-backups\portfolio.db" `
  root@portfolio.srv1211053.hstgr.cloud:/root/IBKR_investment_tracker/backend/portfolio.db
```

Then on the server:

```bash
cd /root/IBKR_investment_tracker
chmod +x deploy.sh
./deploy.sh
```

`deploy.sh` creates the `proxy` network + `traefik_data` volume, ensures `portfolio.db`
exists as a file, builds the frontend, then builds and starts all containers and runs a
health check.

> Starting fresh with **no** backup? Skip the DB copy — `deploy.sh` creates an empty
> `portfolio.db` and the app auto-creates the schema on startup (`init_db` →
> `Base.metadata.create_all`). Then use **Sync IBKR Data** + market-data sync to repopulate.

---

## 4. Verify

```bash
cd /root/IBKR_investment_tracker/backend
docker compose ps
curl -s http://127.0.0.1:8000/health           # {"status":"healthy"}
curl -s http://127.0.0.1:8000/api/scheduler/status
```

In the browser at the live URL: the dashboard loads with your data, **Sync IBKR Data**
succeeds (retries transient 1001s), and the **Dividend Income** card populates.

---

## Gotchas

- **WAL mode:** never copy `portfolio.db` from a running backend without also copying
  `-wal`/`-shm`, or just stop the backend first (as above).
- **Bind mount needs a file:** if `backend/portfolio.db` is missing, Docker creates a
  *directory* and SQLite fails. `deploy.sh` now `touch`es it; for a restore, place the
  real file there first.
- **Traefik owns ports 80/443:** this stack runs its own Traefik. Don't run another
  reverse proxy / second Traefik on the same host (port conflict). (The older setup
  attached to an external `n8n_default` network; the current compose is self-contained.)
- **DNS before TLS:** the domain must resolve to the server before `./deploy.sh`, or the
  Let's Encrypt TLS challenge fails and HTTPS won't come up.
- **Migrations:** startup uses `create_all` (no Alembic on boot). A restored DB from this
  same codebase is fine. If you later add a migration, run `alembic upgrade head` after restore.
