#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
DATE_TAG=$(date +%F)
SESSION_NAME="ksa-leads-${DATE_TAG}"

mkdir -p logs exports

# If virtualenv exists, activate it
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

# Launch detached tmux session with --resume checkpoint support
if command -v tmux >/dev/null 2>&1; then
    tmux new -d -s "$SESSION_NAME" \
      "python -m src.cli run-all --date ${DATE_TAG} --limit 50 --resume 2>&1 | tee -a logs/pipeline_${DATE_TAG}.log"
    echo "Started detached tmux session: ${SESSION_NAME}. Output will be written to exports/ksa_us_stock_leads_${DATE_TAG}.xlsx by 12:00 PM."
else
    echo "tmux not found, running directly in background with nohup..."
    nohup python -m src.cli run-all --date "${DATE_TAG}" --limit 50 --resume > "logs/pipeline_${DATE_TAG}.log" 2>&1 &
    echo "Started background process. PID: $!"
fi
