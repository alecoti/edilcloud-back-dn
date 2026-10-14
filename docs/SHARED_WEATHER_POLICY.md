# Shared project weather

Web and APK use the same authenticated project weather and forecast resources.
Project permission checks happen before cache access or provider requests.

- Current observations: refresh after three hours; retain the last observation for 48 hours to tolerate provider outages. `recordedAt` always remains the provider's observation time.
- Forecasts: one ten-day provider response per location, language and calendar day; clients receive seven days. `pageSize=10` avoids the provider's default five-day page. The cached response expires after 24 hours.
- Both clients refresh the visible overview every six hours. Live weather cards are absent from the feed. Historical post weather remains visible.
- Publishing reads cached observations only. An empty or unavailable cache does not block publication. Explicit weather from existing offline clients remains accepted.
- Cache identities include rounded coordinates and language. Projects at the same coordinates share provider responses; project IDs and place IDs are attached after reading the shared cache.
- A Redis lease coalesces concurrent cold requests; failures have a 60-second backoff. Stale forecasts are filtered to remove dates before today.

Configure `GOOGLE_WEATHER_API_KEY` on the backend (falls back to the server Maps key). Keep the value out of clients and Git. The production environment secret must include the same setting to preserve it across deployments.

Deployments with the existing active-slot file install `edilcloud-weather-refresh.timer`, including rolling updates of a named slot. The timer invokes `refresh_project_weather` in the active web container every three hours. Only real, open, unarchived projects with posts in the last seven days are warmed. Requests in the overview also populate the cache for new or less active projects. Scheduled refreshes allow 60 seconds of timer jitter to avoid skipping an entire three-hour interval.

The deployment installer and runner are in `scripts/install_weather_timer.sh` and `scripts/run_weather_refresh.sh`. The runner uses the existing production container names `back-dn-web-blue-1` / `back-dn-web-green-1`; adapt these if the Compose project name changes.

Provider reference: https://developers.google.com/maps/documentation/weather/reference/rest/v1/forecast.days/lookup
