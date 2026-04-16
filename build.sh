#!/usr/bin/env bash
# Render Build Script — builds frontend + installs backend deps
set -e

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r nazar/requirements.txt

echo "=== Building React dashboard ==="
cd nazar/dashboard
npm ci --silent
npm run build
cd ../..

echo "=== Build complete ==="
