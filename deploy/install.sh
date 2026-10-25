#!/usr/bin/env bash
# Acquisitions Assistant AI - one-command Linux server setup.
#
#   curl -fsSL https://raw.githubusercontent.com/JasonWade45/ACQ-GreenseedTX/main/deploy/install.sh | sudo bash -s -- --domain acq.example.com
#
#   or from a checkout:
#   sudo ./deploy/install.sh --domain acq.example.com
#
# It installs Docker when missing, generates a strong password and session secret, writes
# deploy/.env with mode 600, opens the firewall when ufw is active, and starts the stack
# (app + Caddy with automatic HTTPS). Re-running is safe: an existing .env is preserved.
#
# Options:
#   --domain <name>   public domain that already points at this server (required)
#   --port <n>        local port for the app container (default 8000)
#   --timezone <tz>   business timezone (default Africa/Cairo)
#   --dir <path>      install directory (default /opt/acq)
#   --no-https        run the app on the port directly, no Caddy (open http, not recommended)
#   --dry-run         print what would happen, change nothing
#   --force           regenerate deploy/.env even if a password already exists

set -euo pipefail

DOMAIN=""
APP_PORT="8000"
TIMEZONE="Africa/Cairo"
INSTALL_DIR="/opt/acq"
USE_HTTPS="yes"
DRY_RUN="no"
FORCE="no"
REPO_URL="https://github.com/JasonWade45/ACQ-GreenseedTX.git"

LOG_PREFIX="[acq]"
say()  { printf '%s %s\n' "$LOG_PREFIX" "$*"; }
warn() { printf '%s WARNING: %s\n' "$LOG_PREFIX" "$*" >&2; }
die()  { printf '%s ERROR: %s\n' "$LOG_PREFIX" "$*" >&2; exit 1; }

run() {
    if [ "$DRY_RUN" = "yes" ]; then
        printf '  would run: %s\n' "$*"
    else
        "$@"
    fi
}

usage() {
    sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --domain)   DOMAIN="${2:-}"; shift 2 ;;
        --port)     APP_PORT="${2:-}"; shift 2 ;;
        --timezone) TIMEZONE="${2:-}"; shift 2 ;;
        --dir)      INSTALL_DIR="${2:-}"; shift 2 ;;
        --no-https) USE_HTTPS="no"; shift ;;
        --dry-run)  DRY_RUN="yes"; shift ;;
        --force)    FORCE="yes"; shift ;;
        -h|--help)  usage ;;
        *) die "Unknown option: $1 (try --help)" ;;
    esac
done

[ -n "$DOMAIN" ] || die "--domain is required, for example: --domain acq.example.com"
echo "$DOMAIN" | grep -Eq '^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$' \
    || die "--domain must look like acq.example.com"
echo "$APP_PORT" | grep -Eq '^[0-9]+$' || die "--port must be a number"

if [ "$DRY_RUN" = "no" ] && [ "$(id -u)" -ne 0 ]; then
    die "Run as root (sudo) so Docker, the firewall and the install directory can be set up."
fi

say "Acquisitions Assistant AI - server setup"
say "  domain   : $DOMAIN"
say "  directory: $INSTALL_DIR"
say "  https    : $USE_HTTPS"
say "  timezone : $TIMEZONE"
[ "$DRY_RUN" = "yes" ] && say "  MODE     : dry run, nothing will change"

# ---------------------------------------------------------------- prerequisites
if ! command -v docker >/dev/null 2>&1; then
    say "Docker not found; installing from get.docker.com"
    if [ "$DRY_RUN" = "yes" ]; then
        say "  would download and run the official Docker install script"
    else
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        rm -f /tmp/get-docker.sh
    fi
else
    say "Docker: $(docker --version)"
fi

if docker compose version >/dev/null 2>&1; then
    say "Compose: $(docker compose version --short 2>/dev/null || echo present)"
elif [ "$DRY_RUN" = "no" ]; then
    warn "The Docker Compose v2 plugin is missing; installing docker-compose-plugin"
    (command -v apt-get >/dev/null && apt-get install -y docker-compose-plugin) || true
fi

# ---------------------------------------------------------------- source tree
if [ -f "$INSTALL_DIR/docker-compose.yml" ] || [ -f "$INSTALL_DIR/deploy/docker-compose.yml" ]; then
    say "Existing installation found in $INSTALL_DIR"
    if [ -d "$INSTALL_DIR/.git" ] && [ "$DRY_RUN" = "no" ]; then
        ( cd "$INSTALL_DIR" && git fetch --tags --quiet && git pull --ff-only --quiet ) || \
            warn "git pull failed; keeping the current checkout."
    fi
elif [ -d "$INSTALL_DIR/.git" ]; then
    say "Updating existing checkout in $INSTALL_DIR"
    [ "$DRY_RUN" = "no" ] && ( cd "$INSTALL_DIR" && git fetch --tags --quiet && git pull --ff-only --quiet ) || true
else
    say "Cloning the repository into $INSTALL_DIR"
    if [ "$DRY_RUN" = "yes" ]; then
        say "  would run: git clone --depth 1 $REPO_URL $INSTALL_DIR"
    else
        command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y git; }
        git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    fi
fi

DEPLOY_DIR="$INSTALL_DIR/deploy"
[ -d "$DEPLOY_DIR" ] || [ "$DRY_RUN" = "yes" ] || die "deploy/ not found in $INSTALL_DIR"
ENV_FILE="$DEPLOY_DIR/.env"

# ---------------------------------------------------------------- secrets
gen_secret() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex "$1"
    else
        python3 -c "import secrets,sys; print(secrets.token_hex(int(sys.argv[1])))" "$1"
    fi
}

EXISTING_PASSWORD=""
if [ -f "$ENV_FILE" ]; then
    EXISTING_PASSWORD="$(grep -E '^APP_ACCESS_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2- || true)"
fi

if [ -n "$EXISTING_PASSWORD" ] && [ "${#EXISTING_PASSWORD}" -ge 12 ] && [ "$FORCE" = "no" ]; then
    say "Keeping the existing password from $ENV_FILE"
    PASSWORD="$EXISTING_PASSWORD"
else
    PASSWORD="Acq-$(gen_secret 12)"
    say "Generated a new APP_ACCESS_PASSWORD (save it now):"
    printf '\n    %s\n\n' "$PASSWORD"
fi
SESSION_SECRET="$(gen_secret 32)"

if [ "$DRY_RUN" = "yes" ]; then
    say "  would write $ENV_FILE (mode 600) with SITE_ADDRESS=$DOMAIN"
else
    if [ -f "$ENV_FILE" ] && [ "$FORCE" = "yes" ]; then
        cp "$ENV_FILE" "$ENV_FILE.bak-$(date +%Y%m%d-%H%M%S)"
        say "Previous .env backed up"
    fi
    if [ -f "$ENV_FILE" ] && [ "$FORCE" = "no" ]; then
        # Keep every existing key, only refresh what we own.
        tmp="$(mktemp)"
        grep -vE '^(SITE_ADDRESS|APP_ACCESS_PASSWORD|SESSION_SECRET|APP_TIMEZONE)=' "$ENV_FILE" > "$tmp" || true
        {
            cat "$tmp"
            printf 'SITE_ADDRESS=%s\n' "$DOMAIN"
            printf 'APP_ACCESS_PASSWORD=%s\n' "$PASSWORD"
            printf 'SESSION_SECRET=%s\n' "$SESSION_SECRET"
            printf 'APP_TIMEZONE=%s\n' "$TIMEZONE"
        } > "$ENV_FILE"
        rm -f "$tmp"
    else
        umask 077
        cat > "$ENV_FILE" <<EOF
# Generated by deploy/install.sh. Never commit or share this file.
SITE_ADDRESS=$DOMAIN
APP_ACCESS_PASSWORD=$PASSWORD
SESSION_SECRET=$SESSION_SECRET
APP_TIMEZONE=$TIMEZONE
RESIMPLI_MODE=disabled
SYNC_ENABLED=false
GROQ_ENABLED=false
OLLAMA_ENABLED=false
EOF
    fi
    chmod 600 "$ENV_FILE"
    say "Wrote $ENV_FILE (mode 600)"
fi

# ---------------------------------------------------------------- firewall
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    say "Opening 80/443 in ufw"
    run ufw allow 80/tcp
    run ufw allow 443/tcp
else
    warn "ufw is not active; make sure ports 80 and 443 are reachable from the internet."
fi

# ---------------------------------------------------------------- start
if [ "$USE_HTTPS" = "yes" ]; then
    COMPOSE_FILE="docker-compose.yml"
else
    COMPOSE_FILE="docker-compose.yml"
    warn "--no-https: the app is still started behind Caddy in this release; use the app port directly only for testing."
fi

say "Building and starting the stack (this can take a minute)"
if [ "$DRY_RUN" = "yes" ]; then
    say "  would run: cd $DEPLOY_DIR && docker compose -f $COMPOSE_FILE up -d --build"
else
    ( cd "$DEPLOY_DIR" && docker compose -f "$COMPOSE_FILE" up -d --build )
fi

# ---------------------------------------------------------------- verify
if [ "$DRY_RUN" = "no" ]; then
    say "Waiting for the app to answer /api/health"
    ok="no"
    for _ in $(seq 1 30); do
        if docker compose -f "$DEPLOY_DIR/$COMPOSE_FILE" --project-directory "$DEPLOY_DIR" \
              exec -T app python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).status==200 else 1)" 2>/dev/null; then
            ok="yes"
            break
        fi
        sleep 2
    done
    if [ "$ok" = "yes" ]; then
        say "App is healthy inside the container."
    else
        warn "The container did not report healthy yet. Check: docker compose -f $DEPLOY_DIR/$COMPOSE_FILE logs app"
    fi
fi

say ""
say "Done."
say "  Open      : https://$DOMAIN"
say "  Password  : the APP_ACCESS_PASSWORD printed above (also in $ENV_FILE)"
say "  Logs      : cd $DEPLOY_DIR && docker compose logs -f"
say "  Restart   : cd $DEPLOY_DIR && docker compose restart"
say "  Upgrade   : cd $INSTALL_DIR && git pull && cd deploy && docker compose up -d --build"
say ""
say "The SQLite database lives in the docker volume '$(echo "${COMPOSE_PROJECT_NAME:-acq-assistant}")_app-data'."
say "Back it up before any upgrade: docker compose exec app python -c \"import sqlite3;sqlite3.connect('/app/data/acquisitions.db').backup(sqlite3.connect('/app/data/backup.db'))\""
