from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.conf.urls.static import static
from django.urls import include, path

from edilcloud.api import api
from edilcloud.modules.workspaces.views import (
    approve_access_request_view,
    refuse_access_request_view,
)


def root_view(_request):
    return JsonResponse(
        {
            "service": "edilcloud-back-dn",
            "status": "ok",
            "docs_path": "/api/v1/docs",
            "health_path": "/api/v1/health",
        }
    )


urlpatterns = [
    path("", root_view, name="root"),
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
    path(
        "access-requests/<int:request_id>/<str:token>/approve/",
        approve_access_request_view,
        name="access-request-approve",
    ),
    path(
        "access-requests/<int:request_id>/<str:token>/refuse/",
        refuse_access_request_view,
        name="access-request-refuse",
    ),
]

if settings.DEBUG and "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += [
        path("__debug__/", include("debug_toolbar.urls")),
    ]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
