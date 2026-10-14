#!/usr/bin/env bash
set -euo pipefail
app_dir="${1:-/opt/edilcloud/back-dn}"
slot="$(cat "${app_dir}/.runtime/active-slot")"
case "$slot" in blue|green) ;; *) echo "Invalid active slot" >&2; exit 1;; esac
exec docker exec "back-dn-web-${slot}-1" python manage.py refresh_project_weather --active-days 7
