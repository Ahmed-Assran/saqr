#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_SCRIPT="${SCRIPT_DIR}/run_daily_pipeline.sh"

chmod +x "${PIPELINE_SCRIPT}"

# Cron schedule: Daily at 10:30 AM (Asia/Riyadh / Africa/Cairo)
CRON_JOB="30 10 * * * /bin/bash ${PIPELINE_SCRIPT} >/dev/null 2>&1"

# Check if cron job is already installed
if crontab -l 2>/dev/null | grep -Fq "${PIPELINE_SCRIPT}"; then
    echo "Cron job already installed for ${PIPELINE_SCRIPT}."
else
    (crontab -l 2>/dev/null; echo "${CRON_JOB}") | crontab -
    echo "Successfully installed daily 10:30 AM cron job:"
    echo "${CRON_JOB}"
fi
