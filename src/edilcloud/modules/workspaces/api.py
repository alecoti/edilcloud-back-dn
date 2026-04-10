from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from edilcloud.modules.identity.auth import JWTAuth
from edilcloud.modules.workspaces.schemas import (
    CompanyContactsResponseSchema,
    CompanySchema,
    CreateWorkspaceInviteRequestSchema,
    CreateWorkspaceRequestSchema,
    UpdateCurrentWorkspaceProfileRequestSchema,
    UpdateWorkspaceTeamMemberRequestSchema,
    WorkspaceCurrentProfileSchema,
    WorkspaceInviteDecisionSchema,
    WorkspaceInviteSchema,
    WorkspaceOptionSchema,
    WorkspaceProfileSchema,
    WorkspaceProvisionedResponseSchema,
    WorkspaceTeamMemberSchema,
    WorkspaceTeamMembersResponseSchema,
)
from edilcloud.modules.workspaces.services import (
    accept_workspace_invite,
    create_current_workspace_member,
    create_workspace_for_user,
    create_workspace_invite,
    delete_current_workspace_member,
    disable_current_workspace_member,
    enable_current_workspace_member,
    get_company_contacts,
    get_current_workspace_profile_settings,
    list_current_workspace_members,
    list_active_profiles,
    list_pending_invites,
    list_workspace_options,
    refuse_workspace_invite,
    resend_current_workspace_invite,
    search_companies,
    update_current_workspace_profile_settings,
    update_current_workspace_member,
)

router = Router(tags=["workspaces"])
companies_router = Router(tags=["companies"])
auth = JWTAuth()


@router.get("", response=list[WorkspaceOptionSchema], auth=auth)
def get_workspaces(request):
    return list_workspace_options(request.auth.user)


@router.get("/profiles/active", response=list[WorkspaceProfileSchema], auth=auth)
def get_active_workspace_profiles(request):
    return list_active_profiles(request.auth.user)


@router.get("/current/profile", response=WorkspaceCurrentProfileSchema, auth=auth)
def get_current_workspace_profile_endpoint(request):
    try:
        return get_current_workspace_profile_settings(request.auth.user, claims=request.auth.claims)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.patch("/current/profile", response=WorkspaceCurrentProfileSchema, auth=auth)
def update_current_workspace_profile_endpoint(
    request,
    payload: UpdateCurrentWorkspaceProfileRequestSchema,
):
    try:
        return update_current_workspace_profile_settings(
            request.auth.user,
            claims=request.auth.claims,
            **payload.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get("/current/members", response=WorkspaceTeamMembersResponseSchema, auth=auth)
def get_current_workspace_members(request):
    try:
        profile_id = request.auth.claims.get("main_profile")
        normalized_profile_id = int(profile_id) if profile_id is not None else None
        return list_current_workspace_members(request.auth.user, profile_id=normalized_profile_id)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/current/members", response={201: WorkspaceTeamMemberSchema}, auth=auth)
def create_current_workspace_members_endpoint(
    request,
    payload: CreateWorkspaceInviteRequestSchema,
):
    try:
        member = create_current_workspace_member(
            request.auth.user,
            claims=request.auth.claims,
            **payload.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, member)


@router.put("/current/members/{member_id}", response=WorkspaceTeamMemberSchema, auth=auth)
def update_current_workspace_members_endpoint(
    request,
    member_id: int,
    payload: UpdateWorkspaceTeamMemberRequestSchema,
):
    try:
        return update_current_workspace_member(
            request.auth.user,
            claims=request.auth.claims,
            member_id=member_id,
            **payload.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.delete("/current/members/{member_id}", response=WorkspaceInviteDecisionSchema, auth=auth)
def delete_current_workspace_members_endpoint(request, member_id: int):
    try:
        return delete_current_workspace_member(
            request.auth.user,
            claims=request.auth.claims,
            member_id=member_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/current/members/{member_id}/disable", response=WorkspaceTeamMemberSchema, auth=auth)
def disable_current_workspace_members_endpoint(request, member_id: int):
    try:
        return disable_current_workspace_member(
            request.auth.user,
            claims=request.auth.claims,
            member_id=member_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/current/members/{member_id}/enable", response=WorkspaceTeamMemberSchema, auth=auth)
def enable_current_workspace_members_endpoint(request, member_id: int):
    try:
        return enable_current_workspace_member(
            request.auth.user,
            claims=request.auth.claims,
            member_id=member_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/current/members/{member_id}/resend", response=WorkspaceTeamMemberSchema, auth=auth)
def resend_current_workspace_members_endpoint(request, member_id: int):
    try:
        return resend_current_workspace_invite(
            request.auth.user,
            claims=request.auth.claims,
            member_id=member_id,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("", response={201: WorkspaceProvisionedResponseSchema}, auth=auth)
def create_workspace(request, payload: CreateWorkspaceRequestSchema):
    try:
        result = create_workspace_for_user(request.auth.user, **payload.dict())
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, result)


@router.post("/{workspace_id}/invites", response={201: WorkspaceInviteSchema}, auth=auth)
def invite_to_workspace(request, workspace_id: int, payload: CreateWorkspaceInviteRequestSchema):
    try:
        invite = create_workspace_invite(
            request.auth.user,
            workspace_id=workspace_id,
            **payload.dict(),
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, invite)


@router.get("/invites/pending", response=list[WorkspaceInviteSchema], auth=auth)
def get_pending_workspace_invites(request):
    return list_pending_invites(request.auth.user)


@router.post("/invites/{uidb36}/{token}/accept", response=WorkspaceProvisionedResponseSchema, auth=auth)
def accept_invite(request, uidb36: str, token: str):
    try:
        return accept_workspace_invite(request.auth.user, uidb36=uidb36, token=token)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.post("/invites/{uidb36}/{token}/refuse", response=WorkspaceInviteDecisionSchema)
def refuse_invite(request, uidb36: str, token: str):
    del request
    try:
        return refuse_workspace_invite(uidb36=uidb36, token=token)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@companies_router.get("", response=list[CompanySchema], auth=auth)
def get_companies(request, query: str = ""):
    return search_companies(query=query)


@companies_router.get("/{company_id}/contacts", response=CompanyContactsResponseSchema, auth=auth)
def get_company_contacts_endpoint(request, company_id: int):
    try:
        return get_company_contacts(company_id=company_id)
    except ValueError as exc:
        raise HttpError(404, str(exc)) from exc
