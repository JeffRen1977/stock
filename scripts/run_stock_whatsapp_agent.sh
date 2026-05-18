#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/renjeff/Documents/projects/Stock"
LOG_DIR="${PROJECT_DIR}/logs"

mkdir -p "${LOG_DIR}"

export PATH="/home/renjeff/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"
export PYTHONPATH="${PROJECT_DIR}/src"

cd "${PROJECT_DIR}"

echo "===== $(date -Is) stock-whatsapp-agent start ====="
python3 -m stock_whatsapp_agent.main --log-level INFO
echo "===== $(date -Is) stock-whatsapp-agent end ====="
