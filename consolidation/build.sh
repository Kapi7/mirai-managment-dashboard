#!/usr/bin/env bash
set -euo pipefail
npm ci
npm run build
npm --prefix server ci
python3 -m pip install -r consolidation/requirements-dashboard-production.txt
python3 -m venv .reports-venv
.reports-venv/bin/python -m pip install -r automation_reports/requirements-production.txt
