from __future__ import annotations

from locust import task

from loadtests.locust.common.flows import (
    create_post_comment,
    create_task_post,
    delete_comment,
    delete_post,
)
from loadtests.locust.users.read_heavy import ReadHeavyUser


class MixedCrudUser(ReadHeavyUser):
    @task(2)
    def task_post_create(self) -> None:
        create_task_post(self.client, state=self.state)

    @task(2)
    def post_comment_create(self) -> None:
        create_post_comment(self.client, state=self.state)

    @task(1)
    def comment_delete(self) -> None:
        if self.state.created_comment_ids:
            delete_comment(self.client, state=self.state)
        else:
            create_post_comment(self.client, state=self.state)

    @task(1)
    def post_delete(self) -> None:
        if self.state.created_post_ids:
            delete_post(self.client, state=self.state)
        else:
            create_task_post(self.client, state=self.state)
