#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
#  Nazar — Demo Launcher
#  One-command setup for live demo: seeds data, starts backend + dashboard.
#
#  Usage:
#    ./demo.sh                   # Full demo (auto-detects mode)
#    ./demo.sh --reseed          # Wipe demo data and reseed
#    ./demo.sh --docker          # Force Docker mode
#    ./demo.sh --native          # Force native (python+npm) mode
#    ./demo.sh --backend-only    # Backend only (no dashboard dev server)
# ──────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# ── Colors ──
G='\033[0;32m'; B='\033[0;34m'; Y='\033[1;33m'; R='\033[0;31m'; C='\033[0;36m'; X='\033[0m'

banner() {
    echo ""
    echo -e "${C}╔══════════════════════════════════════════════════════════════╗${X}"
    echo -e "${C}║${X}  ${B}👁  NAZAR${X}  ·  ${G}Har customer pe nazar${X}                   ${C}║${X}"
    echo -e "${C}║${X}  Demo Launcher · v1.0                                        ${C}║${X}"
    echo -e "${C}╚══════════════════════════════════════════════════════════════╝${X}"
    echo ""
}

step() { echo -e "${B}▸${X} $1"; }
ok()   { echo -e "${G}✓${X} $1"; }
warn() { echo -e "${Y}⚠${X} $1"; }
err()  { echo -e "${R}✗${X} $1"; }

# ── Parse args ──
MODE="auto"
RESEED=0
BACKEND_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --docker)        MODE="docker" ;;
        --native)        MODE="native" ;;
        --reseed)        RESEED=1 ;;
        --backend-only)  BACKEND_ONLY=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^#//; s/^ //'
            exit 0
            ;;
    esac
done

banner

# ── 1. Verify .env ──
step "Checking environment configuration..."
if [[ ! -f .env ]]; then
    if [[ -f .env.template ]]; then
        cp .env.template .env
        warn ".env created from template — fill in your API keys"
    else
        err ".env not found and no template available"
        exit 1
    fi
fi
ok ".env found"

# ── 2. Reseed if requested ──
if [[ $RESEED -eq 1 ]]; then
    step "Wiping demo data..."
    rm -rf data/contacts data/handoffs data/kb data/campaign_kb
    rm -f data/campaigns.json data/templates.json
    rm -rf data/analytics
    ok "Demo data wiped"
fi

# ── 3. Auto-detect mode ──
if [[ "$MODE" == "auto" ]]; then
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        MODE="docker"
    elif command -v python3 >/dev/null 2>&1 && command -v node >/dev/null 2>&1; then
        MODE="native"
    else
        err "Neither Docker nor Python+Node detected. Install one and retry."
        exit 1
    fi
fi
ok "Mode: $MODE"

# ──────────────────────────────────────────────────────────────────────
#  DOCKER MODE
# ──────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "docker" ]]; then
    step "Building Nazar container (this may take 2-3 min the first time)..."
    docker compose build

    step "Starting Nazar..."
    docker compose up -d

    sleep 5
    step "Seeding demo data inside container..."
    docker compose exec -T nazar python3 seed_data.py || warn "seed_data.py may have already run"
    docker compose exec -T nazar python3 seed_demo.py || warn "seed_demo.py may have partially run"

    PORT_VAL="${PORT:-8001}"
    echo ""
    echo -e "${G}╔══════════════════════════════════════════════════════════════╗${X}"
    echo -e "${G}║${X}  ${B}NAZAR IS LIVE${X}                                              ${G}║${X}"
    echo -e "${G}╚══════════════════════════════════════════════════════════════╝${X}"
    echo ""
    echo -e "  📊  Dashboard:    ${C}http://localhost:${PORT_VAL}${X}"
    echo -e "  🔑  API Key:      ${C}$(grep '^NAZAR_API_KEY=' .env | cut -d= -f2-)${X}"
    echo -e "  📜  Logs:         ${C}docker compose logs -f nazar${X}"
    echo -e "  ⏹   Stop:         ${C}docker compose down${X}"
    echo ""
    exit 0
fi

# ──────────────────────────────────────────────────────────────────────
#  NATIVE MODE
# ──────────────────────────────────────────────────────────────────────
if [[ "$MODE" == "native" ]]; then
    # ── 4. Python deps ──
    step "Installing Python dependencies..."
    if [[ ! -d .venv ]]; then
        python3 -m venv .venv
    fi
    # shellcheck disable=SC1091
    source .venv/bin/activate
    pip install --quiet --upgrade pip
    pip install --quiet -r requirements.txt
    ok "Python deps installed"

    # ── 5. Seed data ──
    step "Seeding demo contacts..."
    python3 seed_data.py 2>&1 | tail -3 || true

    step "Seeding rich demo content (memory, KB, templates, campaigns)..."
    python3 seed_demo.py 2>&1 | tail -10 || true

    # ── 6. Dashboard build/install ──
    if [[ $BACKEND_ONLY -eq 0 ]]; then
        step "Installing dashboard dependencies..."
        ( cd dashboard && \
          if [[ ! -d node_modules ]]; then npm install --silent; fi )
        ok "Dashboard ready"
    fi

    # ── 7. Start servers ──
    PORT_VAL="${PORT:-8001}"
    step "Starting backend on :${PORT_VAL}..."
    python3 server.py > /tmp/nazar-backend.log 2>&1 &
    BACKEND_PID=$!
    echo "$BACKEND_PID" > /tmp/nazar-backend.pid

    sleep 4
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
        err "Backend failed to start. Last log lines:"
        tail -20 /tmp/nazar-backend.log
        exit 1
    fi
    ok "Backend running (pid $BACKEND_PID)"

    if [[ $BACKEND_ONLY -eq 0 ]]; then
        step "Starting dashboard dev server on :5173..."
        ( cd dashboard && npm run dev -- --host 0.0.0.0 ) > /tmp/nazar-dashboard.log 2>&1 &
        DASHBOARD_PID=$!
        echo "$DASHBOARD_PID" > /tmp/nazar-dashboard.pid
        sleep 4
        ok "Dashboard running (pid $DASHBOARD_PID)"
    fi

    echo ""
    echo -e "${G}╔══════════════════════════════════════════════════════════════╗${X}"
    echo -e "${G}║${X}  ${B}NAZAR IS LIVE${X}                                              ${G}║${X}"
    echo -e "${G}╚══════════════════════════════════════════════════════════════╝${X}"
    echo ""
    if [[ $BACKEND_ONLY -eq 0 ]]; then
        echo -e "  📊  Dashboard:    ${C}http://localhost:5173${X}"
    fi
    echo -e "  🔧  Backend API:  ${C}http://localhost:${PORT_VAL}${X}"
    echo -e "  🔑  API Key:      ${C}$(grep '^NAZAR_API_KEY=' .env | cut -d= -f2-)${X}"
    echo -e "  📜  Logs:         ${C}tail -f /tmp/nazar-backend.log${X}"
    echo ""
    echo -e "  ${Y}To stop:${X}"
    echo -e "       ${C}kill \$(cat /tmp/nazar-backend.pid) \$(cat /tmp/nazar-dashboard.pid 2>/dev/null) 2>/dev/null${X}"
    echo ""
fi
