#!/bin/bash
# wake.sh — type "7" and the family pops open.
cd ~/factory-family || { echo "no ~/factory-family — clone it first"; exit 1; }
echo "[7] pulling latest family..."
git pull -q 2>&1 | tail -2
echo "[7] restarting server..."
pkill -f "admin/family.py" 2>/dev/null
nohup python3 admin/family.py > family.log 2>&1 &
sleep 3
if curl -s -m 3 -o /dev/null http://127.0.0.1:8471/; then
  echo "[7] server is up."
else
  echo "[7] server did NOT start. last log lines:"
  tail -5 family.log
fi
if command -v termux-open-url >/dev/null 2>&1; then
  termux-open-url http://127.0.0.1:8471/ && echo "[7] opening your home..."
else
  echo "[7] open http://127.0.0.1:8471/ in your browser"
fi
