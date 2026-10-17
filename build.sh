#!/usr/bin/env bash
# Exit on error
set -o errexit

echo "===> Building Frontend (React + Vite)..."
cd frontend
npm ci || npm install
npm run build
cd ..

echo "===> Installing Python Dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
pip install -e backend/ || true

echo "===> Build completed successfully!"
