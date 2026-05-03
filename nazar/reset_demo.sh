#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
#  Nazar — One-Shot Demo Reset
#  Wipes & reseeds the Bloom Interiors demo dataset, then warms up
#  the inbox with a few simulated AI conversations.
#
#  Usage:
#    ./reset_demo.sh             # full local reset (uses .venv if present)
#    ./reset_demo.sh --remote    # call the running server's /api/admin
#                                # endpoint instead (no terminal needed
#                                # on the host that runs the server)
#
#  Tip: run this once before every prospect demo. It's idempotent and
#  takes ~10–20 seconds.
# ──────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

G='\033[0;32m'; B='\033[0;34m'; Y='\033[1;33m'; R='\033[0;31m'; X='\033[0m'
ok()   { echo -e "${G}✓${X} $1"; }
step() { echo -e "${B}▸${X} $1"; }
warn() { echo -e "${Y}⚠${X} $1"; }
err()  { echo -e "${R}✗${X} $1"; }

MODE="local"
for arg in "$@"; do
    case "$arg" in
        --remote) MODE="remote" ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^#//; s/^ //'
            exit 0
            ;;
    esac
done

if [[ "$MODE" == "remote" ]]; then
    PORT_VAL="${PORT:-8001}"
    BASE="http://localhost:${PORT_VAL}"
    EMAIL="${NAZAR_DEMO_EMAIL:-admin@nazar.app}"
    PASS="${NAZAR_DEMO_PASSWORD:-changeme123}"

    step "Logging in as ${EMAIL}…"
    TOKEN=$(curl -s -X POST "${BASE}/api/auth/login" \
        -H "Content-Type: application/json" \
        -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASS}\"}" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin).get("token",""))')

    if [[ -z "$TOKEN" ]]; then
        err "Login failed. Check credentials or server is up."
        exit 1
    fi
    ok "Logged in"

    step "Triggering /api/admin/reset-demo (this takes ~15s)…"
    curl -s -X POST "${BASE}/api/admin/reset-demo" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "Content-Type: application/json" \
        --max-time 240 \
        | python3 -c '
import json, sys
try:
    r = json.load(sys.stdin)
    print(("✓ ok=" + str(r.get("ok"))))
    log = r.get("log","")
    # show last 25 lines for sanity
    for line in log.splitlines()[-25:]:
        print("  " + line)
except Exception as e:
    print("✗ Bad JSON response:", e)
    sys.exit(1)
'
    ok "Done"
    exit 0
fi

# ── Local mode ──
PY="python3"
if [[ -x ".venv/bin/python" ]]; then
    PY=".venv/bin/python"
fi

step "Running seed_demo.py (wipe + reseed)…"
"$PY" seed_demo.py
ok "Demo data seeded"

# Optionally pre-warm the inbox if the server is running.
PORT_VAL="${PORT:-8001}"
if curl -sf "http://localhost:${PORT_VAL}/" -o /dev/null --max-time 2; then
    step "Server detected — running demo_polish.py to warm the inbox…"
    "$PY" demo_polish.py || warn "demo_polish.py failed (non-fatal)"
else
    warn "Server not running on :${PORT_VAL}; skipping inbox warm-up."
    warn "Start the server, then re-run with --remote (or just rerun)."
fi

echo ""
ok "Demo is reset and ready. Open the dashboard and go!"
