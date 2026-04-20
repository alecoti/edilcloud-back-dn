from datetime import datetime

from ninja import Schema

from edilcloud.modules.identity.schemas import AuthenticatedResponseSchema


class WorkspaceSummarySchema(Schema):
    id: int
    name: str
    slug: str
    logo: str | None = None
    workspace_type: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    vat_number: str | None = None
    description: str | None = None
    color: str | None = None


class WorkspaceProfileSchema(Schema):
    id: int
    role: str
    position: str | None = None
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    phone_verified_at: datetime | None = None
    language: str | None = None
    photo: str | None = None
    unread_notification_count: int = 0
    company: WorkspaceSummarySchema


class WorkspaceCurrentProfileSchema(Schema):
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    language: str | None = None
    position: str | None = None
    photo: str | None = None
    company: WorkspaceSummarySchema | None = None
    company_name: str | None = None


class WorkspaceOptionSchema(Schema):
    profileId: int
    companyId: int
    companyName: str
    companySlug: str | None = None
    companyLogo: str | None = None
    role: str | None = None
    memberName: str | None = None
    photo: str | None = None


class WorkspaceTeamMemberUserSchema(Schema):
    id: int
    first_name: str | None = None
    last_name: str | None = None


class WorkspaceTeamMemberSchema(Schema):
    id: int
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    mobile: str | None = None
    language: str | None = None
    position: str | None = None
    role: str
    photo: str | None = None
    company_invitation_date: datetime | None = None
    profile_invitation_date: datetime | None = None
    invitation_refuse_date: datetime | None = None
    can_access_files: bool | None = None
    can_access_chat: bool | None = None
    user: WorkspaceTeamMemberUserSchema | None = None


class WorkspaceTeamMembersResponseSchema(Schema):
    approved: list[WorkspaceTeamMemberSchema]
    waiting: list[WorkspaceTeamMemberSchema]
    refused: list[WorkspaceTeamMemberSchema]
    disabled: list[WorkspaceTeamMemberSchema]


class CompanySchema(Schema):
    id: int
    name: str
    slug: str | None = None
    url: str | None = None
    email: str | None = None
    phone: str | None = None
    logo: str | None = None
    address: str | None = None
    province: str | None = None
    cap: str | None = None
    country: str | None = None
    tax_code: str | None = None
    vat_number: str | None = None
    pec: str | None = None
    billing_email: str | None = None


class CompanyContactCompanySchema(Schema):
    id: int
    name: str | None = None
    slug: str | None = None
    email: str | None = None
    tax_code: str | None = None


class CompanyContactUserSchema(Schema):
    id: int
    first_name: str | None = None
    last_name: str | None = None


class CompanyContactSchema(Schema):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    project_role: str
    company: CompanyContactCompanySchema | None = None
    user: CompanyContactUserSchema | None = None


class CompanyContactsResponseSchema(Schema):
    companyId: int
    contacts: list[CompanyContactSchema]
    preferredContact: CompanyContactSchema | None = None


class CreateWorkspaceRequestSchema(Schema):
    company_name: str
    company_email: str = ""
    company_phone: str = ""
    company_website: str = ""
    company_vat_number: str = ""
    company_description: str = ""
    workspace_type: str = ""
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    language: str = "it"
    position: str = ""


class WorkspaceProvisionedResponseSchema(Schema):
    workspace: WorkspaceSummarySchema
    profile: WorkspaceProfileSchema
    auth: AuthenticatedResponseSchema


class CreateWorkspaceInviteRequestSchema(Schema):
    email: str
    role: str = "w"
    first_name: str = ""
    last_name: str = ""
    position: str = ""
    expires_in_days: int = 14


class WorkspaceInviteCodeAcceptRequestSchema(Schema):
    invite_code: str


class CreateWorkspaceAccessRequestSchema(Schema):
    position: str = ""
    message: str = ""


class UpdateWorkspaceTeamMemberRequestSchema(Schema):
    email: str | None = None
    role: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language: str | None = None
    position: str | None = None
    phone: str | None = None
    can_access_files: bool | None = None
    can_access_chat: bool | None = None


class UpdateCurrentWorkspaceProfileRequestSchema(Schema):
    first_name: str | None = None
    last_name: str | None = None
    phone: str | None = None
    language: str | None = None
    position: str | None = None


class WorkspaceInviteSchema(Schema):
    id: int
    invite_code: str
    uidb36: str
    token: str
    email: str
    role: str
    position: str | None = None
    accepted_at: datetime | None = None
    expires_at: datetime | None = None
    refused_at: datetime | None = None
    company: WorkspaceSummarySchema


class WorkspaceSearchResultSchema(Schema):
    id: int
    name: str
    slug: str
    logo: str | None = None
    workspace_type: str | None = None
    already_member: bool = False
    pending_invite: bool = False
    pending_access_request: bool = False


class WorkspaceAccessRequestSchema(Schema):
    id: int
    status: str
    email: str
    first_name: str
    last_name: str
    phone: str | None = None
    language: str | None = None
    position: str | None = None
    message: str | None = None
    approved_at: datetime | None = None
    refused_at: datetime | None = None
    expires_at: datetime | None = None
    company: WorkspaceSummarySchema


class WorkspaceAccessRequestCreatedSchema(Schema):
    status: str
    detail: str
    request: WorkspaceAccessRequestSchema


class WorkspaceInviteDecisionSchema(Schema):
    status: str
    detail: str
