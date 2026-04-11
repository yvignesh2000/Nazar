# Nazar Deployment

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
