from ninja import Router
from ninja.errors import HttpError

from edilcloud.modules.billing.schemas import (
    BillingCatalogSchema,
    BillingCheckoutRequestSchema,
    BillingCheckoutSchema,
    BillingCheckoutStatusSchema,
    BillingPortalSchema,
    BillingSummarySchema,
    BillingWebhookResponseSchema,
)
from edilcloud.modules.billing.services import (
    create_workspace_billing_checkout,
    create_workspace_billing_portal,
    get_workspace_billing_summary,
    get_workspace_checkout_status,
    process_stripe_webhook,
    serialize_billing_catalog,
)
from edilcloud.modules.identity.auth import JWTAuth

router = Router(tags=["billing"])
auth = JWTAuth()


@router.get("/catalog", response=BillingCatalogSchema)
def billing_catalog(request):
    del request
    return serialize_billing_catalog()


@router.get("/current", response=BillingSummarySchema, auth=auth)
def billing_current(request, workspace_id: int | None = None):
    try:
        return get_workspace_billing_summary(
            request.auth.user,
            claims=request.auth.claims,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/checkout", response=BillingCheckoutSchema, auth=auth)
def billing_checkout(request, workspace_id: int, payload: BillingCheckoutRequestSchema):
    try:
        return create_workspace_billing_checkout(
            request.auth.user,
            claims=request.auth.claims,
            workspace_id=workspace_id,
            **payload.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/workspaces/{workspace_id}/portal", response=BillingPortalSchema, auth=auth)
def billing_portal(request, workspace_id: int):
    try:
        return create_workspace_billing_portal(
            request.auth.user,
            claims=request.auth.claims,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get(
    "/workspaces/{workspace_id}/checkout/{session_id}",
    response=BillingCheckoutStatusSchema,
    auth=auth,
)
def billing_checkout_status(request, workspace_id: int, session_id: str):
    try:
        return get_workspace_checkout_status(
            request.auth.user,
            claims=request.auth.claims,
            workspace_id=workspace_id,
            session_id=session_id,
        )
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post("/stripe/webhook", response=BillingWebhookResponseSchema)
def billing_stripe_webhook(request):
    signature = request.headers.get("Stripe-Signature", "").strip()
    if not signature:
        raise HttpError(400, "Firma Stripe mancante.")
    try:
        return process_stripe_webhook(payload=request.body, signature=signature)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except Exception as exc:
        raise HttpError(400, f"Webhook Stripe non valido: {exc}") from exc
