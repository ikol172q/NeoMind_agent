#!/usr/bin/env bash
# gen_miniflux_creds.sh — generate Miniflux admin credentials and
# write them to .env in the repo root. Safe to re-run: never
# overwrites existing non-empty values.
#
# Usage:
#   ./scripts/gen_miniflux_creds.sh
#
# After this runs:
#   docker compose --profile news up -d miniflux miniflux-db
#   open http://127.0.0.1:8080

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "✗ .env not found at $ENV_FILE" >&2
  echo "  Copy .env.example to .env first: cp .env.example .env" >&2
  exit 1
fi

# Read existing values (blank if not set or empty)
existing_user="$(grep -E '^MINIFLUX_USERNAME=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"
existing_pass="$(grep -E '^MINIFLUX_PASSWORD=' "$ENV_FILE" | tail -n1 | cut -d= -f2- || true)"

if [[ -n "${existing_pass// }" ]]; then
  echo "✓ MINIFLUX_PASSWORD already set in .env — leaving it alone"
  echo "  (delete the line manually if you want to regenerate)"
  exit 0
fi

# Generate a 32-char URL-safe random password.
# Read a bounded chunk from /dev/urandom instead of streaming, so tr
# doesn't hit SIGPIPE when head closes early (set -o pipefail would
# exit 141 otherwise on macOS bash 3.2).
new_pass="$(LC_ALL=C head -c 256 /dev/urandom | LC_ALL=C tr -dc 'A-Za-z0-9_-' | LC_ALL=C head -c 32)"
if [[ ${#new_pass} -ne 32 ]]; then
  # Fallback: openssl (always available on macOS)
  new_pass="$(openssl rand -base64 48 | LC_ALL=C tr -d '=+/\n' | LC_ALL=C head -c 32)"
fi
new_user="${existing_user:-neomind}"

# Strip any existing commented/blank placeholder lines
tmp="$(mktemp)"
grep -vE '^(# )?MINIFLUX_(URL|USERNAME|PASSWORD)=' "$ENV_FILE" > "$tmp" || true

cat >> "$tmp" <<EOF

# Miniflux (auto-generated $(date -u +%Y-%m-%dT%H:%M:%SZ))
MINIFLUX_URL=http://127.0.0.1:8080
MINIFLUX_USERNAME=$new_user
MINIFLUX_PASSWORD=$new_pass
EOF

mv "$tmp" "$ENV_FILE"
chmod 600 "$ENV_FILE"

echo "✓ Miniflux credentials written to $ENV_FILE"
echo "  username: $new_user"
echo "  password: (32 random chars, stored in .env mode 600)"
echo ""
echo "Next:"
echo "  docker compose --profile news up -d miniflux miniflux-db"
echo "  open http://127.0.0.1:8080   # log in with the credentials above"
