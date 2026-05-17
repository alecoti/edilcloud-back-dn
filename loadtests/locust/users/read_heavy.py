from __future__ import annotations

from locust import task

from loadtests.locust.common.flows import (
    refresh_feed_cache,
    refresh_task_id,
    resolve_project_id,
    search_global,
)
from loadtests.locust.users.base import EdilCloudBaseUser


class ReadHeavyUser(EdilCloudBaseUser):
    @task(2)
    def auth_session(self) -> None:
        self.client.get("/api/auth/session", name="auth.session")

    @task(2)
    def projects_list(self) -> None:
        resolve_project_id(self.client, state=self.state, config=self.config)

    @task(2)
    def feed_list(self) -> None:
        refresh_feed_cache(self.client, state=self.state)

    @task(1)
    def notifications_list(self) -> None:
        self.client.get("/api/notifications?limit=10", name="notifications.list")

    @task(1)
    def search_global(self) -> None:
        search_global(self.client, config=self.config)

    @task(3)
    def project_overview(self) -> None:
        if self.has_project():
            self.client.get(
                f"/api/projects/{self.state.project_id}/overview",
                name="project.overview",
            )

    @task(3)
    def project_tasks(self) -> None:
        refresh_task_id(self.client, state=self.state)

    @task(1)
    def project_documents(self) -> None:
        if self.has_project():
            self.client.get(
                f"/api/projects/{self.state.project_id}/documents",
                name="project.documents",
            )

    @task(1)
    def project_gantt(self) -> None:
        if self.has_project():
            self.client.get(
                f"/api/projects/{self.state.project_id}/gantt",
                name="project.gantt",
            )

    @task(1)
    def assistant_state(self) -> None:
        if self.has_project():
            self.client.get(
                f"/api/projects/{self.state.project_id}/assistant",
                name="assistant.state",
            )
