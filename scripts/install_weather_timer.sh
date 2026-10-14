#!/usr/bin/env bash
set -euo pipefail
app_dir="${1:-/opt/edilcloud/back-dn}"
test -f "${app_dir}/scripts/run_weather_refresh.sh"
cat > /etc/systemd/system/edilcloud-weather-refresh.service <<EOF
[Unit]
Description=Refresh shared weather snapshots for active EdilCloud projects
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/bin/bash ${app_dir}/scripts/run_weather_refresh.sh ${app_dir}
TimeoutStartSec=15min
EOF
cat > /etc/systemd/system/edilcloud-weather-refresh.timer <<'EOF'
[Unit]
Description=Refresh EdilCloud shared weather every three hours

[Timer]
OnCalendar=*-*-* 00,03,06,09,12,15,18,21:05:00
Persistent=true
RandomizedDelaySec=30
Unit=edilcloud-weather-refresh.service

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now edilcloud-weather-refresh.timer
