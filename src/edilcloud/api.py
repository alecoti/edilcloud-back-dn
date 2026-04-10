from ninja import NinjaAPI

from edilcloud.modules.assistant.api import router as assistant_router
from edilcloud.modules.billing.api import router as billing_router
from edilcloud.modules.identity.api import router as identity_router
from edilcloud.modules.notifications.api import router as notifications_router
from edilcloud.modules.projects.api import (
    activities_router,
    comments_router,
    documents_router,
    folders_router,
    photos_router,
    posts_router,
    router as projects_router,
    tasks_router,
)
from edilcloud.modules.search.api import router as search_router
from edilcloud.modules.workspaces.api import companies_router, router as workspaces_router
from edilcloud.platform.api.health import router as health_router

api = NinjaAPI(
    title="EdilCloud API",
    version="0.1.0",
    urls_namespace="edilcloud_api",
)

api.add_router("/health", health_router)
api.add_router("/auth", identity_router)
api.add_router("/billing", billing_router)
api.add_router("/workspaces", workspaces_router)
api.add_router("/companies", companies_router)
api.add_router("/notifications", notifications_router)
api.add_router("/projects", projects_router)
api.add_router("/projects", assistant_router)
api.add_router("/search", search_router)
api.add_router("/tasks", tasks_router)
api.add_router("/activities", activities_router)
api.add_router("/posts", posts_router)
api.add_router("/comments", comments_router)
api.add_router("/folders", folders_router)
api.add_router("/documents", documents_router)
api.add_router("/photos", photos_router)
