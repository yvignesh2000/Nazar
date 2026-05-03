#!/bin/bash
# Tunnel keepalive - auto-restarts localtunnel on failure
while true; do
    echo "$(date) Starting localtunnel..."
    npx localtunnel --port 8001 2>&1
    EXIT_CODE=$?
    echo "$(date) Tunnel exited with code $EXIT_CODE. Restarting in 3s..."
    sleep 3
done
