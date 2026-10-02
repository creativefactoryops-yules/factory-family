#!/bin/bash
# wake.sh — type "7" and the family pops open.
cd ~/factory-family || { echo "no ~/factory-family — clone it first"; exit 1; }
git pull -q 2>/dev/null
pkill -f "admin/family.py" 2>/dev/null
nohup python3 admin/family.py > family.log 2>&1 &
sleep 3
if command -v termux-open-url >/dev/null 2>&1; then
  termux-open-url http://127.0.0.1:8471/den
else
  echo "open http://127.0.0.1:8471/den"
fi
