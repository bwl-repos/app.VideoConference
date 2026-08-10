#!/usr/bin/env bash
# Node metrics agent — pushes CPU/MEM/DISK to the app's internal endpoint.
# Usage: agent.sh <name> <role>   (run via cron every minute)
set -uo pipefail
NAME="${1:-node}"
ROLE="${2:-}"
SECRET="$(cat /opt/bwl/agent/node.secret 2>/dev/null)"
URL="https://video.pbltools.io/api/internal/nodes"

# CPU% from /proc/stat delta over 1s
read -r _ u n s i io irq sirq st _ < /proc/stat
idle1=$((i + io)); tot1=$((u + n + s + i + io + irq + sirq + st))
sleep 1
read -r _ u n s i io irq sirq st _ < /proc/stat
idle2=$((i + io)); tot2=$((u + n + s + i + io + irq + sirq + st))
dt=$((tot2 - tot1)); di=$((idle2 - idle1))
cpu=$(( dt > 0 ? (100 * (dt - di) / dt) : 0 ))

mem=$(free | awk '/^Mem:/{printf "%.0f", $3/$2*100}')
disk=$(df / | awk 'NR==2{gsub("%","",$5); print $5}')

curl -s -m 10 -X POST "$URL" \
  -H "X-Node-Secret: $SECRET" -H "Content-Type: application/json" \
  -d "{\"name\":\"$NAME\",\"role\":\"$ROLE\",\"cpu\":$cpu,\"mem\":$mem,\"disk\":$disk}" >/dev/null
echo "$(date -u '+%H:%M:%S') $NAME cpu=$cpu mem=$mem disk=$disk"
