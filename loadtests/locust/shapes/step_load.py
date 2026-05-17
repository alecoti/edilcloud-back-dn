from __future__ import annotations

from locust import LoadTestShape


class StepLoadShape(LoadTestShape):
    use_common_options = True
    step_time = 120
    step_users = 10
    spawn_rate = 5
    max_users = 80
    hold_seconds = 180

    def tick(self):
        run_time = self.get_run_time()
        max_step = max(1, self.max_users // self.step_users)
        if run_time > self.step_time * max_step + self.hold_seconds:
            return None
        current_step = int(run_time // self.step_time) + 1
        users = min(current_step * self.step_users, self.max_users)
        return users, self.spawn_rate
