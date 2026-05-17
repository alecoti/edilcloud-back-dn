from __future__ import annotations

from locust import HttpUser, between

from loadtests.locust.common.config import LocustRunConfig, load_config
from loadtests.locust.common.flows import (
    ScenarioState,
    bootstrap_user,
    cleanup_created_content,
    next_user_email,
)


class EdilCloudBaseUser(HttpUser):
    abstract = True
    wait_time = between(0.35, 1.2)

    config: LocustRunConfig
    state: ScenarioState

    def on_start(self) -> None:
        self.config = load_config()
        self.state = ScenarioState(email=next_user_email(self.config.email_prefix))
        bootstrap_user(self.client, state=self.state, config=self.config)

    def on_stop(self) -> None:
        cleanup_created_content(self.client, state=self.state)

    def has_project(self) -> bool:
        return self.state.authenticated and self.state.project_id is not None
