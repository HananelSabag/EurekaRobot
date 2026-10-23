#!/usr/bin/env bash
# Live command test through the local server: sends one action, then prints the robot state every few seconds.
# Usage: tools/cmdtest.sh <start|pause|stop|dock> [seconds=20] [mode fan water]
set -u
API=http://127.0.0.1:8765/api
action=$1; secs=${2:-20}
if [ $# -ge 5 ]; then
  curl -s -X POST "$API/prefs" -H 'content-type: application/json' \
    -d "{\"mode\":\"$3\",\"fan\":\"$4\",\"water\":\"$5\"}" > /dev/null
fi
echo "$(date +%T) -> $action: $(curl -s -X POST "$API/command" -H 'content-type: application/json' -d "{\"action\":\"$action\"}")"
end=$(( $(date +%s) + secs ))
while [ "$(date +%s)" -lt "$end" ]; do
  sleep 4
  curl -s "$API/state" | ./.venv/Scripts/python -c "
import json, sys, time
s = json.load(sys.stdin)['state']
print(time.strftime('%T'), s['status'], f\"bat={s['battery']}%\", f\"mode={s['mode']}\", f\"fan={s['fan']}\", f\"water={s['water']}\",
      f\"area={s['area']}\", f\"min={s['work_time']}\", f\"err={s['error_type']}/{s['error_desc']}\")"
done
