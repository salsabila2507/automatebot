#!/bin/bash
set -e
cd /home/ubuntu/schedule_bot
if pgrep -f '(^|/)\.venv/bin/python[[:space:]]+bot\.py([[:space:]]|$)' >/dev/null; then
  echo "Bot already running"
  exit 1
fi
exec 9>/home/ubuntu/schedule_bot/.bot.lock
if ! flock -n 9; then
  echo "Bot already running"
  exit 1
fi
rm -f /home/ubuntu/schedule_bot/.ready
nohup .venv/bin/python bot.py >> bot.log 2>&1 &
pid=$!
for _ in $(seq 1 30); do
  ready=""
  if [ -r /home/ubuntu/schedule_bot/.ready ]; then
    ready=$(</home/ubuntu/schedule_bot/.ready)
  fi
  if [ "$ready" = "$pid" ]; then
    echo "Bot started (PID=$pid)"
    exit 0
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Bot failed to start; inspect bot.log"
    exit 1
  fi
  sleep 0.5
done
kill "$pid" 2>/dev/null || true
echo "Bot startup health check failed; inspect bot.log"
exit 1
