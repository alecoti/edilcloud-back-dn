from __future__ import annotations

from locust import HttpUser, constant, task

from loadtests.locust.common.config import load_config
from loadtests.locust.common.flows import ScenarioState, login, next_user_email


class AuthBurstUser(HttpUser):
    wait_time = constant(0.1)

    @task
    def login_burst(self) -> None:
        config = load_config()
        state = ScenarioState(email=next_user_email(config.email_prefix))
        login(self.client, state=state, config=config)
