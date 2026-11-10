#!/usr/bin/env bash
# LAB 7.4 – Steps 9–13: swap index.html in ~/WEB-FUNC and redeploy web-func (run in OCI Cloud Shell).
#
# Usage:
#   1. Upload the new index.html to Cloud Shell (Cloud Shell menu → Upload), e.g. to ~/index.html
#   2. bash deploy-web-func.sh ~/index.html
#
# What it does: backs up the live index.html, copies the new one in, checks disk space,
# logs in to OCIR if needed (asks for your auth token), runs fn deploy, and shows the new image.
set -euo pipefail

NEW_HTML="${1:-$HOME/index.html}"
FUNC_DIR="${FUNC_DIR:-$HOME/WEB-FUNC}"
APP="${APP:-WEB-APP}"
REGISTRY="${REGISTRY:-iad.ocir.io}"
MIN_FREE_MB="${MIN_FREE_MB:-1200}"   # fn deploy needs roughly 1 GB for the build

[ -f "$NEW_HTML" ] || { echo "New index.html not found: $NEW_HTML"; exit 1; }
[ -f "$FUNC_DIR/func.yaml" ] || { echo "Function source not found in $FUNC_DIR"; exit 1; }
cd "$FUNC_DIR"

# Step 9 – back up the live page and swap in the new one
backup="index.html.bak-$(date +%Y%m%d%H%M)"
cp index.html "$backup"
cp "$NEW_HTML" index.html
echo "Backed up live page to $FUNC_DIR/$backup"
echo "New index.html sha256: $(sha256sum index.html | cut -d' ' -f1)"
grep -q 'const API_URL = "/multi-agent/chat"' index.html || echo "WARNING: API_URL is not \"/multi-agent/chat\" – check before deploying."

# Step 10 – disk space (Cloud Shell home is only 5 GB)
free_mb=$(df -Pm "$HOME" | awk 'NR==2 {print $4}')
echo "Free space in \$HOME: ${free_mb} MB"
if [ "$free_mb" -lt "$MIN_FREE_MB" ]; then
  echo "Less than ${MIN_FREE_MB} MB free. Run cleanup-cloudshell-images.sh first, then re-run this script."
  exit 1
fi

# Step 11 – OCIR login (the login is cleared when Cloud Shell restarts)
if ! grep -q "$REGISTRY" "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/containers/auth.json" 2>/dev/null; then
  if [ -z "${OCIR_USER:-}" ]; then
    ns=$(oci os ns get --query data --raw-output)
    user=$(oci iam user get --user-id "${OCI_CS_USER_OCID:-}" --query 'data.name' --raw-output 2>/dev/null || true)
    [ -n "$user" ] || read -r -p "OCI username (e.g. you@example.com): " user < /dev/tty
    OCIR_USER="$ns/$user"   # identity-domain users may need "$ns/<domain>/$user"
  fi
  echo "Logging in to $REGISTRY as $OCIR_USER. Password = your OCI auth token (Profile → Auth tokens)."
  docker login "$REGISTRY" -u "$OCIR_USER"
fi

# Step 12 – deploy
fn -v deploy --app "$APP"

# Step 13 – show the new image
echo
echo "Deployed version: $(grep '^version:' func.yaml | awk '{print $2}')"
fn list functions "$APP"
echo
echo "Now open https://ociagent.anjaneesinghpro.website/multi-agent/ and press Ctrl+F5."
echo "Rollback: bash rollback-web-func.sh $backup"
