# Nazar Deployment

Two paths: **Railway** (fastest, recommended) or a **Linux VPS** (most control).

---

## Path A — Railway (Recommended)

Railway gives you managed Postgres, automatic HTTPS, and deploys straight from GitHub.

### 1. Create a Railway account

Go to [railway.app](https://railway.app) → sign up → connect your GitHub account.

### 2. New project from GitHub

- Click **New Project** → **Deploy from GitHub repo**
- Select your `Nazar` repository
- Railway will detect the `Dockerfile` and build the API service automatically

### 3. Add Postgres

Inside your Railway project:
- Click **+ New** → **Database** → **Add PostgreSQL**
- Railway automatically sets `DATABASE_URL` in your service's environment

### 4. Add a second service for the Worker

- Click **+ New** → **GitHub Repo** → same repo
- Go to **Settings** → **Build** → change Dockerfile path to `Dockerfile.worker`
- Name it `worker`

### 5. Set environment variables

In your **API service** → **Variables**, add:

```
WA_PHONE_NUMBER_ID=your_phone_number_id
WA_ACCESS_TOKEN=your_permanent_access_token
WA_VERIFY_TOKEN=nazar_verify_2026
OPENROUTER_API_KEY=your_openrouter_key
GROQ_API_KEY=your_groq_key
NAZAR_API_KEY=change_this_to_a_secret_key
NAZAR_OWNER_NAME=Admin
NAZAR_OWNER_EMAIL=owner@yourcompany.com
NAZAR_WORKSPACE_SLUG=yourworkspace
NAZAR_WORKSPACE_NAME=Your Business Name
NAZAR_ENV=production
TELEGRAM_BOT_TOKEN=optional
TELEGRAM_BOT_USERNAME=optional
```

Copy the same variables to the **Worker service**.
`DATABASE_URL` is already set by the Postgres plugin — don't override it.

### 6. Deploy

Railway builds and deploys automatically on every push to `codex/product-foundation`.

Your app URL will be `https://<your-project>.up.railway.app`.

### 7. Verify

```
curl https://<your-project>.up.railway.app/health
# → {"status": "ok", "db": "connected", ...}
```

### 8. WhatsApp webhook

In Meta Developer Console:
- Callback URL: `https://<your-project>.up.railway.app/webhook`
- Verify token: the value of `WA_VERIFY_TOKEN`

### 9. Custom domain (optional)

In Railway: **Settings** → **Domains** → **Add Custom Domain** → follow the DNS instructions.

---

## Path B — Linux VPS

Use this if you want full control or are running on Hetzner/DigitalOcean.

### Recommended server spec

- Ubuntu 24.04 LTS
- 2 vCPU / 4 GB RAM / 60 GB SSD
- Static public IP + domain (e.g. `app.nazarcrm.com`)

### 1. Install system packages

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git postgresql postgresql-contrib
```

### 2. Create Postgres database

```bash
sudo -u postgres psql -c "CREATE USER nazar WITH PASSWORD 'a_strong_password';"
sudo -u postgres psql -c "CREATE DATABASE nazar OWNER nazar;"
```

### 3. Create app user and clone repo

```bash
sudo useradd -m -s /bin/bash nazar
sudo mkdir -p /opt/nazar
sudo chown nazar:nazar /opt/nazar
sudo -u nazar git clone -b codex/product-foundation https://github.com/yvignesh2000/Nazar.git /opt/nazar
```

### 4. Create virtualenv and install deps

```bash
cd /opt/nazar
sudo -u nazar python3 -m venv .venv
sudo -u nazar .venv/bin/pip install -r nazar/requirements.txt
```

### 5. Environment file

```bash
sudo -u nazar cp /opt/nazar/nazar/.env.template /opt/nazar/nazar/.env
sudo nano /opt/nazar/nazar/.env
```

Set at minimum:
```
DATABASE_URL=postgresql+psycopg://nazar:a_strong_password@localhost:5432/nazar
NAZAR_ENV=production
NAZAR_API_KEY=your_strong_random_key
NAZAR_OWNER_EMAIL=you@yourdomain.com
WA_PHONE_NUMBER_ID=...
WA_ACCESS_TOKEN=...
OPENROUTER_API_KEY=...
```

### 6. Run database migrations

```bash
cd /opt/nazar
PYTHONPATH=/opt/nazar sudo -u nazar .venv/bin/alembic upgrade head
```

### 7. Install systemd services

```bash
sudo cp deploy/nazar-api.service /etc/systemd/system/
sudo cp deploy/nazar-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nazar-api nazar-worker
sudo systemctl start nazar-api nazar-worker
```

Check:
```bash
sudo systemctl status nazar-api
sudo journalctl -u nazar-api -f
```

### 8. Nginx

```bash
sudo cp /opt/nazar/deploy/nginx-nazar.conf /etc/nginx/sites-available/nazar
sudo ln -s /etc/nginx/sites-available/nazar /etc/nginx/sites-enabled/nazar
# Edit server_name to your domain
sudo nano /etc/nginx/sites-available/nazar
sudo nginx -t && sudo systemctl reload nginx
```

### 9. SSL

```bash
sudo certbot --nginx -d app.nazarcrm.com
```

### 10. WhatsApp webhook

In Meta Developer Console:
- Callback URL: `https://app.nazarcrm.com/webhook`
- Verify token: your `WA_VERIFY_TOKEN` value

---

## Local dev with Docker (Postgres locally, no manual SQLite)

```bash
# First time
cp nazar/.env.template nazar/.env
# Fill in your API keys (DATABASE_URL is set automatically by docker-compose)

docker compose up --build

# In another terminal, verify
curl http://localhost:8002/health
```

The app runs at `http://localhost:8002`.
Postgres data persists in the `postgres_data` Docker volume.

---

## Notes

- Never use temporary Cloudflare tunnels for WhatsApp webhooks in production
- Use a permanent system-user token for WhatsApp, not the temporary debug token
- `NAZAR_ALLOW_SCHEMA_CREATE=1` is a local-dev-only fallback — never set in production
- All schema changes go through `alembic upgrade head` — never `Base.metadata.create_all` in prod


This is the stable deployment path for Nazar as it exists today.

## Recommended shape

Use one Linux VPS for now.

Why:
- Nazar still has file-backed pieces such as the knowledge base and customer-memory storage.
- Running the API and worker on the same machine avoids shared-storage issues.
- This gives you one stable public webhook URL for WhatsApp and a clean path to production.

## Recommended server

- Ubuntu 24.04 VPS
- 2 vCPU
- 4 GB RAM
- 60+ GB SSD
- Static public IP
- Domain/subdomain such as `api.nazarcrm.com`

## Install

1. SSH into the server
2. Install system packages:

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx git
```

3. Create app user:

```bash
sudo useradd -m -s /bin/bash nazar
```

4. Clone the repo:

```bash
sudo mkdir -p /opt
sudo chown nazar:nazar /opt
sudo -u nazar git clone https://github.com/yvignesh2000/Nazar.git /opt/nazar
cd /opt/nazar
git checkout codex/product-foundation
```

5. Create a virtualenv and install dependencies:

```bash
cd /opt/nazar
sudo -u nazar python3 -m venv .venv
sudo -u nazar .venv/bin/pip install -r nazar/requirements.txt
```

6. Set the Python path in the service files if your python binary differs from `/usr/bin/python3`.

## Environment

Create:

```bash
/opt/nazar/nazar/.env
```

With at least:

```env
WA_PHONE_NUMBER_ID=...
WA_ACCESS_TOKEN=...
WA_VERIFY_TOKEN=nazar_verify_2026
OPENROUTER_API_KEY=...
GROQ_API_KEY=
NAZAR_API_KEY=...
NAZAR_OWNER_NAME=Admin
DATABASE_URL=sqlite:////opt/nazar/nazar/data/nazar.db
PORT=8001
```

If you want Postgres later, replace `DATABASE_URL`.

## Database

Run migrations:

```bash
cd /opt/nazar
sudo -u nazar .venv/bin/alembic upgrade head
```

## systemd

Copy service files:

```bash
sudo cp deploy/nazar-api.service /etc/systemd/system/
sudo cp deploy/nazar-worker.service /etc/systemd/system/
```

Edit both files so `ExecStart` points to:

```bash
/opt/nazar/.venv/bin/python /opt/nazar/nazar/server.py
/opt/nazar/.venv/bin/python /opt/nazar/nazar/worker.py
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable nazar-api
sudo systemctl enable nazar-worker
sudo systemctl start nazar-api
sudo systemctl start nazar-worker
```

Check:

```bash
sudo systemctl status nazar-api
sudo systemctl status nazar-worker
```

## Nginx

Copy the nginx config:

```bash
sudo cp deploy/nginx-nazar.conf /etc/nginx/sites-available/nazar
sudo ln -s /etc/nginx/sites-available/nazar /etc/nginx/sites-enabled/nazar
sudo nginx -t
sudo systemctl reload nginx
```

Update `server_name` to your real domain.

## SSL

After DNS points to the server:

```bash
sudo certbot --nginx -d api.nazarcrm.com
```

## WhatsApp webhook

In Meta, configure:

- Callback URL: `https://api.nazarcrm.com/webhook`
- Verify token: `nazar_verify_2026`

## Notes

- Do not use temporary tunnels for the final setup.
- Do not rely on the temporary Meta access token long term; replace it with a permanent system-user token.
- With the current codebase, a single VPS is the safest stable deployment shape.
