#!/usr/bin/env bash
# Uptime monitor — checks the public services and emails on state change (Resend).
# Runs from a separate host (egress) so it can detect an app-node outage.
set -uo pipefail
DIR="/opt/bwl/monitor"
KEY="$(cat "$DIR/resend.key" 2>/dev/null)"
TO="bitencourtpaula.gabriel@gmail.com"
FROM="no-reply@openpbl.ai"
STATE="$DIR/state"

problems=""

H="$(curl -s -m 10 https://video.pbltools.io/health/detail || true)"
echo "$H" | grep -q '"ok":true' || problems+="• app /health/detail falhou (resp: ${H:0:120})\n"
echo "$H" | grep -q '"db":true'  || problems+="• Banco de dados inacessível\n"

site=$(curl -s -m 10 -o /dev/null -w "%{http_code}" https://video.pbltools.io/ || echo 000)
[ "$site" = "200" ] || problems+="• Site video.pbltools.io retornou HTTP $site\n"

rtc=$(curl -s -m 10 -o /dev/null -w "%{http_code}" https://rtc.pbltools.io/ || echo 000)
[ "$rtc" = "200" ] || problems+="• LiveKit rtc.pbltools.io retornou HTTP $rtc\n"

now="up"; [ -n "$problems" ] && now="down"
prev="$(cat "$STATE" 2>/dev/null || echo up)"

send() {
  [ -z "$KEY" ] && { echo "no resend key"; return; }
  curl -s -m 15 -X POST https://api.resend.com/emails \
    -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
    -d "{\"from\":\"$FROM\",\"to\":[\"$TO\"],\"subject\":\"$1\",\"text\":\"$2\"}" >/dev/null
}

ts="$(date -u '+%Y-%m-%d %H:%M UTC')"
if [ "$now" = "down" ] && [ "$prev" != "down" ]; then
  send "🔴 Video Rooms com problema" "$(printf "Detectado em %s:\n\n%b" "$ts" "$problems")"
elif [ "$now" = "up" ] && [ "$prev" = "down" ]; then
  send "🟢 Video Rooms recuperado" "Todos os serviços voltaram ao normal em $ts."
fi
echo "$now" > "$STATE"
echo "$ts status=$now ${problems:+| $problems}"
