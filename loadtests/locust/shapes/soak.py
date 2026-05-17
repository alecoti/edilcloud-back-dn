from __future__ import annotations

from locust import LoadTestShape


class SoakShape(LoadTestShape):
    use_common_options = True
    users = 35
    spawn_rate = 10
    duration_seconds = 60 * 60

    def tick(self):
        if self.get_run_time() > self.duration_seconds:
            return None
        return self.users, self.spawn_rate
