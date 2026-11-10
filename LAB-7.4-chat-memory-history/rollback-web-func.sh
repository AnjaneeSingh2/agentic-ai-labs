#!/usr/bin/env bash
# LAB 7.4 – Rollback: restore a backed-up index.html and redeploy web-func.
#
# Usage:
#   bash rollback-web-func.sh                              # lists available backups
#   bash rollback-web-func.sh index.html.bak-202611101559  # restores that backup
set -euo pipefail

FUNC_DIR="${FUNC_DIR:-$HOME/WEB-FUNC}"
APP="${APP:-WEB-APP}"
cd "$FUNC_DIR"

if [ $# -eq 0 ]; then
  echo "Backups in $FUNC_DIR:"
  ls -1t index.html.bak-* 2>/dev/null || echo "  (none)"
  echo "Run again with the backup file name."
  exit 0
fi

[ -f "$1" ] || { echo "Backup not found: $FUNC_DIR/$1"; exit 1; }
cp index.html "index.html.before-rollback-$(date +%Y%m%d%H%M)"
cp "$1" index.html
echo "Restored $1 as index.html. Deploying..."
fn -v deploy --app "$APP"
echo "Deployed version: $(grep '^version:' func.yaml | awk '{print $2}')"
