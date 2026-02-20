#!/bin/bash
# Log system state every 5 minutes for debugging freezes.
# Used by cron: */5 * * * * /opt/visa_bulletin/scripts/health_check.sh
# Requires root crontab so /var/log/health_check.log is writable.

LOG=/var/log/health_check.log
DATE=$(date '+%Y-%m-%d %H:%M:%S')

CPU=$(top -bn1 | grep 'Cpu(s)' | awk '{print $2}')
MEM=$(free | awk '/Mem/{printf("%.1f", $3/$2 * 100)}')
SWAP=$(free | awk '/Swap/{if($2>0) printf("%.1f", $3/$2 * 100); else print "0"}')
LOAD=$(cat /proc/loadavg | awk '{print $1}')

echo "$DATE | CPU: ${CPU}% | MEM: ${MEM}% | SWAP: ${SWAP}% | LOAD: $LOAD" >> "$LOG"

# Keep log from growing too large (keep last 1000 lines)
tail -1000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG" 2>/dev/null || true
