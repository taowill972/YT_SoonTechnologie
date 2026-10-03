#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "=== [$(date -u +'%Y-%m-%d %H:%M:%S UTC')] Lancement cron YT_SoonTechnologie (lot de 7) ==="
/usr/bin/python3 batch_runner.py
echo "=== [$(date -u +'%Y-%m-%d %H:%M:%S UTC')] Fin du cycle cron YT_SoonTechnologie ==="
