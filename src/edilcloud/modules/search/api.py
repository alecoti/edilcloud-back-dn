from ninja import Router
from ninja.errors import HttpError

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.search.schemas import GlobalSearchResponseSchema
from edilcloud.modules.search.services import search_workspace_index


router = Router(tags=["search"])
auth = JWTAuth()


@router.get("/global", response=GlobalSearchResponseSchema, auth=auth)
def global_search(request, q: str = "", limit: int = 6, category: str = "all"):
    try:
        return search_workspace_index(
            user=request.auth.user,
            claims=request.auth.claims,
            query=q,
            limit_per_section=limit,
            category=category,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
