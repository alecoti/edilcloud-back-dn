"""Labor endpoints share contracts across the native and Django runtimes."""
from datetime import date
from uuid import UUID
from django.http import JsonResponse
from ninja import Body, Router
from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.projects.services import get_current_profile
from . import labor_registers as ledger
from . import labor_ai_requests as interpretations

router = Router(tags=["Resource registers"], auth=JWTAuth())


@router.post("/labor/interpretations")
def interpret(request, payload: dict = Body(...)):
    return response(interpretations.interpret(profile(request), payload))


@router.get("/labor/interpretations/{command_id}")
def interpretation(request, command_id: UUID):
    return response(interpretations.read(profile(request), command_id))


def profile(request):
    return get_current_profile(user=request.auth.user, claims=request.auth.claims)


def response(value):
    return JsonResponse(value, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/identities")
def identities(request, project_id: int, q: str = ""):
    return response(ledger.identities(profile(request), project_id, q))


@router.post("/identities")
def create_identity(request, payload: dict = Body(...)):
    return response(ledger.create_identity(profile(request), payload))


@router.get("/commands/{command_id}")
def recover(request, command_id: UUID):
    return response(ledger.recover(profile(request), command_id))


@router.get("/labor/registers")
def listing(request, project_id: int, start: date | None = None, end: date | None = None, offset: int = 0, limit: int = 30):
    return response(ledger.listing(profile(request), project_id, start, end, offset, limit))


@router.post("/labor/registers")
def create(request, payload: dict = Body(...)):
    return response(ledger.create_register(profile(request), payload))


@router.get("/labor/registers/{register_id}")
def read(request, register_id: UUID, version: int | None = None):
    return response(ledger.read(profile(request), register_id, version))


@router.post("/labor/registers/{register_id}/commands")
def command(request, register_id: UUID, payload: dict = Body(...)):
    return response(ledger.command(profile(request), register_id, payload))
