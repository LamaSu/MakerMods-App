#!/usr/bin/env bash
# Developer-only script — requires Node.js.
# End-users do NOT need to run this. The frontend/out/ directory should be
# pre-built and included in the distribution zip.
set -e

cd frontend
npm install
NEXT_STATIC_EXPORT=1 npm run build
echo ""
echo "Frontend built to frontend/out/"
echo "Include this directory in the distribution zip alongside the source."
