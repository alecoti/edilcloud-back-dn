"""HTTP API for authentication and onboarding endpoints."""

import json
import jwt
from django.conf import settings
from django.contrib.auth import get_user_model
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.identity.schemas import (
    AccessCodeConfirmSchema,
    AccessCodeRequestResponseSchema,
    AccessCodeRequestSchema,
    AuthenticatedResponseSchema,
    GenericDetailResponseSchema,
    GoogleAuthRequestSchema,
    LoginRequestSchema,
    LogoutRequestSchema,
    OnboardingCompleteSchema,
    OnboardingInviteSchema,
    OnboardingInviteCodeAcceptSchema,
    OnboardingProfileUpdateSchema,
    OnboardingRequiredResponseSchema,
    OnboardingSessionSchema,
    OnboardingWorkspaceAccessRequestSchema,
    PasswordResetConfirmSchema,
    PasswordResetRequestSchema,
    PublicUserSchema,
    RefreshTokenRequestSchema,
    RegisterRequestSchema,
    SessionVerifyRequestSchema,
)
from edilcloud.modules.identity.services import (
    accept_onboarding_workspace_invite_by_code,
    accept_onboarding_workspace_invite,
    authenticate_with_google,
    authenticated_response_from_payload,
    build_auth_payload,
    complete_onboarding,
    confirm_access_code,
    confirm_password_reset,
    get_onboarding_session_state,
    list_onboarding_workspace_invites,
    login_user,
    logout_user,
    request_onboarding_workspace_access,
    request_access_code,
    request_password_reset,
    refresh_user_token,
    register_user,
    search_onboarding_workspaces,
    update_onboarding_profile,
    verify_user_token,
)
from edilcloud.modules.workspaces.schemas import (
    WorkspaceAccessRequestCreatedSchema,
    WorkspaceSearchResultSchema,
)
from edilcloud.platform.rate_limit import RateLimitExceeded, enforce_rate_limit

router = Router(tags=["identity"])
auth = JWTAuth()
auth_api_response = AuthenticatedResponseSchema | OnboardingRequiredResponseSchema

LOGIN_RATE_LIMIT = (10, 5 * 60)
ACCESS_CODE_REQUEST_RATE_LIMIT = (5, 10 * 60)
ACCESS_CODE_CONFIRM_RATE_LIMIT = (10, 10 * 60)
GOOGLE_AUTH_RATE_LIMIT = (10, 5 * 60)
REFRESH_RATE_LIMIT = (60, 10 * 60)
PASSWORD_RESET_REQUEST_RATE_LIMIT = (5, 10 * 60)
PASSWORD_RESET_CONFIRM_RATE_LIMIT = (10, 10 * 60)


def is_multipart_request(request) -> bool:
    return "multipart/form-data" in (request.headers.get("content-type") or "").lower()


def parse_json_schema(request, schema_class):
    return schema_class(**json.loads(request.body.decode() or "{}"))


def parse_onboarding_profile_payload(request) -> tuple[OnboardingProfileUpdateSchema, object | None]:
    if is_multipart_request(request):
        payload = OnboardingProfileUpdateSchema(
            onboarding_token=request.POST.get("onboarding_token", ""),
            first_name=request.POST.get("first_name", ""),
            last_name=request.POST.get("last_name", ""),
            phone=request.POST.get("phone", ""),
            language=request.POST.get("language", "it"),
        )
        return payload, request.FILES.get("photo")

    return parse_json_schema(request, OnboardingProfileUpdateSchema), None


def parse_onboarding_complete_payload(request) -> tuple[OnboardingCompleteSchema, object | None]:
    if is_multipart_request(request):
        payload = OnboardingCompleteSchema(
            onboarding_token=request.POST.get("onboarding_token", ""),
            first_name=request.POST.get("first_name", ""),
            last_name=request.POST.get("last_name", ""),
            phone=request.POST.get("phone", ""),
            language=request.POST.get("language", "it"),
            company_name=request.POST.get("company_name", ""),
            company_email=request.POST.get("company_email", ""),
            company_phone=request.POST.get("company_phone", ""),
            company_website=request.POST.get("company_website", ""),
            company_vat_number=request.POST.get("company_vat_number", ""),
            company_description=request.POST.get("company_description", ""),
            workspace_type=request.POST.get("workspace_type", ""),
            position=request.POST.get("position", ""),
        )
        return payload, request.FILES.get("company_logo")

    return parse_json_schema(request, OnboardingCompleteSchema), None


def request_ip(request) -> str:
    forwarded_for = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return (request.META.get("REMOTE_ADDR") or "").strip() or "unknown"


def enforce_identity_rate_limit(
    request,
    *,
    namespace: str,
    limit: int,
    window_seconds: int,
    key_parts: tuple[object, ...],
    message: str,
) -> None:
    enforce_rate_limit(
        namespace,
        limit=limit,
        window_seconds=window_seconds,
        key_parts=(request_ip(request), *key_parts),
        message=message,
    )


@router.post("/register", response={201: PublicUserSchema})
def register(request, payload: RegisterRequestSchema):
    try:
        user = register_user(**payload.dict())
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc

    return Status(201, PublicUserSchema(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language=user.language,
        is_active=user.is_active,
    ))


@router.post("/login", response=AuthenticatedResponseSchema)
def login(request, payload: LoginRequestSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.login",
            limit=LOGIN_RATE_LIMIT[0],
            window_seconds=LOGIN_RATE_LIMIT[1],
            key_parts=(payload.username_or_email,),
            message="Troppi tentativi di login. Riprova tra qualche minuto.",
        )
        return login_user(
            username_or_email=payload.username_or_email,
            password=payload.password,
        )
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/access-code/request", response=AccessCodeRequestResponseSchema)
def access_code_request(request, payload: AccessCodeRequestSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.access_code.request",
            limit=ACCESS_CODE_REQUEST_RATE_LIMIT[0],
            window_seconds=ACCESS_CODE_REQUEST_RATE_LIMIT[1],
            key_parts=(payload.email,),
            message="Hai richiesto troppi codici. Attendi prima di riprovare.",
        )
        return request_access_code(email=payload.email)
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/access-code/confirm", response=auth_api_response)
def access_code_confirm(request, payload: AccessCodeConfirmSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.access_code.confirm",
            limit=ACCESS_CODE_CONFIRM_RATE_LIMIT[0],
            window_seconds=ACCESS_CODE_CONFIRM_RATE_LIMIT[1],
            key_parts=(payload.email,),
            message="Troppi tentativi di verifica. Richiedi un nuovo codice o riprova tra poco.",
        )
        return confirm_access_code(email=payload.email, code=payload.code)
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/google", response=auth_api_response)
def google_auth(request, payload: GoogleAuthRequestSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.google",
            limit=GOOGLE_AUTH_RATE_LIMIT[0],
            window_seconds=GOOGLE_AUTH_RATE_LIMIT[1],
            key_parts=("google",),
            message="Troppi tentativi di accesso con Google. Riprova tra poco.",
        )
        return authenticate_with_google(
            credential=payload.credential,
            access_token=payload.access_token,
        )
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/token/verify", response=AuthenticatedResponseSchema)
def verify_token(request, payload: SessionVerifyRequestSchema):
    try:
        claims = verify_user_token(payload.token)
    except jwt.ExpiredSignatureError as exc:
        raise HttpError(401, "Sessione non valida o scaduta.") from exc
    except jwt.InvalidTokenError as exc:
        raise HttpError(401, "Sessione non valida o scaduta.") from exc

    return authenticated_response_from_payload(claims)


@router.post("/token/refresh/{profile_id}", response=AuthenticatedResponseSchema)
def refresh_token(request, profile_id: int, payload: RefreshTokenRequestSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.refresh",
            limit=REFRESH_RATE_LIMIT[0],
            window_seconds=REFRESH_RATE_LIMIT[1],
            key_parts=(profile_id,),
            message="Sessione temporaneamente bloccata. Riprova tra poco.",
        )
        return refresh_user_token(payload.refresh_token, profile_id=profile_id)
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    except jwt.InvalidTokenError as exc:
        raise HttpError(401, "Sessione non valida o scaduta.") from exc


@router.post("/logout", response=GenericDetailResponseSchema)
def logout(request, payload: LogoutRequestSchema):
    try:
        return logout_user(refresh_token=payload.refresh_token)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/password-reset/request", response=GenericDetailResponseSchema)
def password_reset_request(request, payload: PasswordResetRequestSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.password_reset.request",
            limit=PASSWORD_RESET_REQUEST_RATE_LIMIT[0],
            window_seconds=PASSWORD_RESET_REQUEST_RATE_LIMIT[1],
            key_parts=(payload.email,),
            message="Hai richiesto troppi reset password. Attendi prima di riprovare.",
        )
        return request_password_reset(email=payload.email)
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/password-reset/confirm", response=GenericDetailResponseSchema)
def password_reset_confirm(request, payload: PasswordResetConfirmSchema):
    try:
        enforce_identity_rate_limit(
            request,
            namespace="auth.password_reset.confirm",
            limit=PASSWORD_RESET_CONFIRM_RATE_LIMIT[0],
            window_seconds=PASSWORD_RESET_CONFIRM_RATE_LIMIT[1],
            key_parts=(payload.email,),
            message="Troppi tentativi di reset password. Riprova tra poco.",
        )
        return confirm_password_reset(
            email=payload.email,
            code=payload.code,
            new_password=payload.new_password,
        )
    except RateLimitExceeded as exc:
        raise HttpError(429, str(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/me", response=PublicUserSchema, auth=auth)
def me(request):
    user = request.auth.user
    return PublicUserSchema(
        id=user.id,
        email=user.email,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        language=user.language,
        is_active=user.is_active,
    )


@router.post("/onboarding/profile", response=OnboardingRequiredResponseSchema)
def onboarding_profile(request):
    try:
        payload, photo = parse_onboarding_profile_payload(request)
        return update_onboarding_profile(**payload.dict(), photo=photo)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/onboarding/session", response=OnboardingRequiredResponseSchema)
def onboarding_session(request, onboarding_token: str):
    try:
        return get_onboarding_session_state(onboarding_token=onboarding_token)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/onboarding/complete", response=AuthenticatedResponseSchema)
def onboarding_complete(request):
    try:
        payload, company_logo = parse_onboarding_complete_payload(request)
        return complete_onboarding(**payload.dict(), company_logo=company_logo)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/onboarding/invites", response=list[OnboardingInviteSchema])
def onboarding_invites(request, onboarding_token: str):
    try:
        return list_onboarding_workspace_invites(onboarding_token=onboarding_token)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/onboarding/invites/{uidb36}/{token}/accept", response=AuthenticatedResponseSchema)
def onboarding_accept_invite(request, uidb36: str, token: str, payload: OnboardingSessionSchema):
    try:
        return accept_onboarding_workspace_invite(
            onboarding_token=payload.onboarding_token,
            uidb36=uidb36,
            token=token,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/onboarding/invites/code/accept", response=AuthenticatedResponseSchema)
def onboarding_accept_invite_code(request, payload: OnboardingInviteCodeAcceptSchema):
    try:
        return accept_onboarding_workspace_invite_by_code(
            onboarding_token=payload.onboarding_token,
            invite_code=payload.invite_code,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/onboarding/workspaces/search", response=list[WorkspaceSearchResultSchema])
def onboarding_workspace_search(request, onboarding_token: str, query: str):
    try:
        return search_onboarding_workspaces(
            onboarding_token=onboarding_token,
            query=query,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post(
    "/onboarding/workspaces/{workspace_id}/request-access",
    response=WorkspaceAccessRequestCreatedSchema,
)
def onboarding_workspace_request_access(
    request,
    workspace_id: int,
    payload: OnboardingWorkspaceAccessRequestSchema,
):
    try:
        return request_onboarding_workspace_access(
            onboarding_token=payload.onboarding_token,
            workspace_id=workspace_id,
            position=payload.position,
            message=payload.message,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/dev/bootstrap", response=AuthenticatedResponseSchema)
def bootstrap_dev_identity(request):
    if not settings.DEBUG or not settings.ENABLE_DEV_BOOTSTRAP_AUTH:
        raise HttpError(404, "Endpoint non disponibile.")

    user_model = get_user_model()
    user = user_model.objects.filter(email="owner@edilcloud.dev").first()
    if user is None:
        user = user_model.objects.create_user(
            email="owner@edilcloud.dev",
            password="devpass123",
            username="owner",
            first_name="Dev",
            last_name="Owner",
            language="it",
        )

    return authenticated_response_from_payload(build_auth_payload(user))
