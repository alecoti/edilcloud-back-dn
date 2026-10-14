"""Shared weather snapshots. Publishing reads cache only, never the provider."""
from copy import deepcopy
from datetime import date
import hashlib
import math
import time
from uuid import uuid4

import httpx
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


CURRENT_REFRESH_SECONDS = 3 * 60 * 60
SNAPSHOT_RETENTION_SECONDS = 48 * 60 * 60
FORECAST_CACHE_SECONDS = 24 * 60 * 60
SUPPORTED_LANGUAGES = {"it", "en", "fr", "ro", "ru", "ar"}


class WeatherUnavailable(ValueError):
    pass


def _language(language):
    return language if language in SUPPORTED_LANGUAGES else "it"


def _location_key(project):
    if project.latitude is None or project.longitude is None:
        return None
    latitude, longitude = float(project.latitude), float(project.longitude)
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return None
    return f"{latitude:.4f}:{longitude:.4f}"


def _key(project, language, kind):
    location = _location_key(project)
    if location is None:
        return None
    signature = hashlib.sha256(f"{location}:{_language(language)}:{kind}".encode()).hexdigest()
    return f"project-weather:v1:{signature}"


def _request(project, language, endpoint, **parameters):
    api_key = getattr(settings, "GOOGLE_WEATHER_API_KEY", "")
    if not api_key:
        raise WeatherUnavailable("Servizio meteo non configurato.")
    params = {
        "key": api_key,
        "location.latitude": f"{float(project.latitude):.4f}",
        "location.longitude": f"{float(project.longitude):.4f}",
        "languageCode": _language(language), "unitsSystem": "METRIC", **parameters,
    }
    try:
        response = httpx.get(f"https://weather.googleapis.com/v1/{endpoint}", params=params, timeout=5)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid weather response")
        return payload
    except (httpx.HTTPError, ValueError) as error:
        # Exceptions may contain the URL with the server key: keep it private.
        raise WeatherUnavailable("Meteo temporaneamente non disponibile.") from error


def _value(source, *path):
    for part in path:
        if not isinstance(source, dict):
            return None
        source = source.get(part)
    return source


def _current_payload(raw):
    result = {
        "source": "google-weather", "recordedAt": raw.get("currentTime") or timezone.now().isoformat(),
        "timeZone": _value(raw, "timeZone", "id"),
        "summary": _value(raw, "weatherCondition", "description", "text"),
        "conditionType": _value(raw, "weatherCondition", "type"),
        "isDaytime": raw.get("isDaytime"), "humidity": raw.get("relativeHumidity"),
        "uvIndex": raw.get("uvIndex"), "thunderstormProbability": raw.get("thunderstormProbability"),
        "cloudCover": raw.get("cloudCover"),
    }
    for output, path in {
        "temperatureC": ("temperature", "degrees"), "feelsLikeC": ("feelsLikeTemperature", "degrees"),
        "precipitationProbability": ("precipitation", "probability", "percent"),
        "precipitationType": ("precipitation", "probability", "type"),
        "windSpeedKph": ("wind", "speed", "value"), "windGustKph": ("wind", "gust", "value"),
        "windDirection": ("wind", "direction", "cardinal"),
    }.items():
        result[output] = _value(raw, *path)
    return result


def _for_project(payload, project):
    if payload is None:
        return None
    return {**deepcopy(payload), "latitude": project.latitude, "longitude": project.longitude,
            "googlePlaceId": project.google_place_id or None}


def cached_post_weather(project, language):
    """Use the latest observed snapshot, retaining its actual observation time."""
    key = _key(project, language, "current")
    if key is None:
        return None
    try:
        entry = cache.get(key)
        if entry is None:
            entry = cache.get(f"project-weather:latest:{_location_key(project)}")
        return _for_project(entry.get("weather") if entry else None, project)
    except Exception:
        # Weather metadata must never prevent a post or an offline replay.
        return None


def current_weather(project, language, *, refresh_before_seconds=0):
    key = _key(project, language, "current")
    if key is None:
        return None
    entry = cache.get(key)
    if entry and entry["refresh_after"] > time.time() + refresh_before_seconds:
        return _for_project(entry["weather"], project)
    if cache.get(key + ":failure"):
        if entry:
            return _for_project(entry["weather"], project)
        raise WeatherUnavailable("Meteo temporaneamente non disponibile.")
    lease = uuid4().hex
    if not cache.add(key + ":lease", lease, timeout=30):
        # Concurrent overview requests can reuse the previous observation.
        if entry:
            return _for_project(entry["weather"], project)
        deadline = time.monotonic() + 5.5
        while time.monotonic() < deadline and cache.get(key + ":lease"):
            time.sleep(0.05)
            shared = cache.get(key)
            if shared:
                return _for_project(shared["weather"], project)
        raise WeatherUnavailable("Meteo temporaneamente non disponibile.")
    try:
        payload = _current_payload(_request(project, language, "currentConditions:lookup"))
        entry = {"weather": payload, "refresh_after": time.time() + CURRENT_REFRESH_SECONDS}
        cache.set(key, entry, timeout=SNAPSHOT_RETENTION_SECONDS)
        cache.set(f"project-weather:latest:{_location_key(project)}", entry, timeout=SNAPSHOT_RETENTION_SECONDS)
        return _for_project(payload, project)
    except WeatherUnavailable:
        cache.set(key + ":failure", True, timeout=60)
        if entry:
            return _for_project(entry["weather"], project)
        raise
    finally:
        if cache.get(key + ":lease") == lease:
            cache.delete(key + ":lease")


def _forecast_payload(raw):
    result = []
    for day in raw.get("forecastDays", []):
        try:
            display = day["displayDate"]
            date_value = date(display["year"], display["month"], display["day"]).isoformat()
        except (KeyError, TypeError, ValueError):
            continue
        row = {"date": date_value, "maxTemperatureC": _value(day, "maxTemperature", "degrees"),
               "minTemperatureC": _value(day, "minTemperature", "degrees"),
               "uvIndex": _value(day, "daytimeForecast", "uvIndex"),
               "sunriseTime": _value(day, "sunEvents", "sunriseTime"),
               "sunsetTime": _value(day, "sunEvents", "sunsetTime")}
        for suffix, part in (("Day", "daytimeForecast"), ("Night", "nighttimeForecast")):
            for output, path in {
                "summary": ("weatherCondition", "description", "text"),
                "conditionType": ("weatherCondition", "type"),
                "precipitationProbability": ("precipitation", "probability", "percent"),
                "cloudCover": ("cloudCover",), "windSpeedKph": ("wind", "speed", "value"),
            }.items():
                row[output + suffix] = _value(day, part, *path)
        result.append(row)
    return result


def forecast_weather(project, language, days=7):
    # Always cache the provider's ten-day window, so requesting 5/7/10 days
    # does not create additional billable lookups for the same place and day.
    key = _key(project, language, "forecast:" + timezone.localdate().isoformat())
    if key is None:
        return []
    days = max(1, min(int(days), 10))
    existing = cache.get(key)
    if existing is not None:
        return deepcopy(existing[:days])
    fallback_key = _key(project, language, "forecast:latest")
    fallback = [row for row in cache.get(fallback_key, []) if row["date"] >= timezone.localdate().isoformat()]
    if cache.get(key + ":failure"):
        if fallback:
            return deepcopy(fallback[:days])
        raise WeatherUnavailable("Previsione temporaneamente non disponibile.")
    lease = uuid4().hex
    if not cache.add(key + ":lease", lease, timeout=30):
        if fallback:
            return deepcopy(fallback[:days])
        deadline = time.monotonic() + 5.5
        while time.monotonic() < deadline and cache.get(key + ":lease"):
            time.sleep(0.05)
            shared = cache.get(key)
            if shared is not None:
                return deepcopy(shared[:days])
        raise WeatherUnavailable("Previsione in aggiornamento. Riprova tra poco.")
    try:
        result = _forecast_payload(_request(project, language, "forecast/days:lookup", days=10, pageSize=10))
        cache.set(key, result, timeout=FORECAST_CACHE_SECONDS)
        cache.set(fallback_key, result, timeout=SNAPSHOT_RETENTION_SECONDS)
        return deepcopy(result[:days])
    except WeatherUnavailable:
        cache.set(key + ":failure", True, timeout=60)
        if fallback:
            return deepcopy(fallback[:days])
        raise
    finally:
        if cache.get(key + ":lease") == lease:
            cache.delete(key + ":lease")


def refresh_active_project_weather(*, active_days=7):
    """Periodic warming for active sites; never run from a post mutation."""
    from datetime import timedelta
    from edilcloud.modules.projects.models import Project
    projects = Project.objects.filter(
        is_demo_master=False, archived_at__isnull=True, closed_at__isnull=True,
        posts__created_at__gte=timezone.now() - timedelta(days=active_days),
        latitude__isnull=False, longitude__isnull=False,
    ).select_related("created_by").distinct()
    result = {"projects": 0, "errors": 0}
    for project in projects.iterator():
        try:
            language = project.created_by.language if project.created_by else "it"
            # Avoid skipping an entire scheduled interval because of the
            # timer's small randomized delay or clock scheduling jitter.
            current_weather(project, language, refresh_before_seconds=60)
            forecast_weather(project, language)
            result["projects"] += 1
        except WeatherUnavailable:
            result["errors"] += 1
    return result
