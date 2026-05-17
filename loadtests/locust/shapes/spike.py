from __future__ import annotations

from locust import LoadTestShape


class SpikeShape(LoadTestShape):
    use_common_options = True
    warmup_seconds = 60
    spike_seconds = 120
    cooldown_seconds = 60
    warmup_users = 10
    spike_users = 120
    spawn_rate = 60

    def tick(self):
        run_time = self.get_run_time()
        if run_time < self.warmup_seconds:
            return self.warmup_users, 5
        if run_time < self.warmup_seconds + self.spike_seconds:
            return self.spike_users, self.spawn_rate
        if run_time < self.warmup_seconds + self.spike_seconds + self.cooldown_seconds:
            return self.warmup_users, self.spawn_rate
        return None
