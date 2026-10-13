"""Bounded, atomic Redis series; request writes never read the whole metric state."""
from functools import lru_cache
import json
from time import time

from django.core.cache import caches
from django.core.cache.backends.redis import RedisCache
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


MAX_SERIES = 2048
MAX_SAMPLES = 512

_COUNTER_SCRIPT = """
redis.call('SET', KEYS[2], ARGV[4], 'NX')
if redis.call('HEXISTS', KEYS[1], ARGV[1]) == 0 and
   redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
return redis.call('HINCRBY', KEYS[1], ARGV[1], ARGV[2])
"""

_TIMING_SCRIPT = """
redis.call('SET', KEYS[2], ARGV[5], 'NX')
local raw = redis.call('HGET', KEYS[1], ARGV[1])
if not raw and redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
local value = tonumber(ARGV[2])
local series
if raw then series = cjson.decode(raw)
else series = {count=0, sum=0, min=value, max=value, samples={}} end
series.count = series.count + 1
series.sum = series.sum + value
series.min = math.min(series.min, value)
series.max = math.max(series.max, value)
series.samples[((series.count - 1) % tonumber(ARGV[4])) + 1] = value
redis.call('HSET', KEYS[1], ARGV[1], cjson.encode(series))
return series.count
"""


class RedisMetricStore:
    def __init__(self, location: str, prefix: str):
        # Telemetry gets a short network deadline and no automatic retries.
        # Its failure cannot consume the authentication request's time budget.
        self.client = Redis.from_url(
            location, socket_connect_timeout=0.2, socket_timeout=0.2,
            retry=Retry(NoBackoff(), 0), decode_responses=True,
        )
        self.counters_key = f"{prefix}:counters"
        self.timings_key = f"{prefix}:timings"
        self.started_key = f"{prefix}:started"
        self.counter_script = self.client.register_script(_COUNTER_SCRIPT)
        self.timing_script = self.client.register_script(_TIMING_SCRIPT)

    def increment(self, key: str, value: int):
        self.counter_script(
            keys=[self.counters_key, self.started_key],
            args=[key, value, MAX_SERIES, time()],
        )

    def observe(self, key: str, value: float):
        self.timing_script(
            keys=[self.timings_key, self.started_key],
            args=[key, value, MAX_SERIES, MAX_SAMPLES, time()],
        )

    def snapshot(self):
        with self.client.pipeline(transaction=False) as pipeline:
            pipeline.get(self.started_key)
            pipeline.hgetall(self.counters_key)
            pipeline.hgetall(self.timings_key)
            started, counters, timings = pipeline.execute()
        return {
            "started_at": float(started) if started else time(),
            "counters": {key: int(value) for key, value in counters.items()},
            "timings": {key: json.loads(value) for key, value in timings.items()},
        }

    def reset(self):
        with self.client.pipeline() as pipeline:
            pipeline.delete(self.counters_key, self.timings_key, self.started_key)
            pipeline.set(self.started_key, time())
            pipeline.execute()


@lru_cache(maxsize=4)
def _store(location: str, prefix: str):
    return RedisMetricStore(location, prefix)


def redis_metric_store():
    backend = caches["default"]
    if not isinstance(backend, RedisCache):
        return None
    # Match the installed Django 5.2 Redis backend's primary and key function.
    return _store(backend._servers[0], backend.make_key("telemetry:series:v3"))
