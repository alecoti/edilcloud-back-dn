from __future__ import annotations

from edilcloud.modules.assistant.models import ProjectAssistantState
from edilcloud.modules.assistant.services import (
    get_or_create_project_assistant_state,
    index_project_assistant_state,
    schedule_project_assistant_sync,
    sync_project_assistant_sources,
)
from edilcloud.modules.projects.models import Project

__all__ = [
    "get_or_create_project_assistant_state",
    "index_project_assistant_state",
    "schedule_project_assistant_sync",
    "sync_project_assistant_sources",
]


def ensure_project_index_scheduled(project: Project) -> ProjectAssistantState:
    state = get_or_create_project_assistant_state(project)
    schedule_project_assistant_sync(state)
    return state
