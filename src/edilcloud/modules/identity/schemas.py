from ninja import Schema


class AuthProfileSchema(Schema):
    id: int
    role: str
    company: int | None


class AuthExtraSchema(Schema):
    profile: AuthProfileSchema | None = None


class AuthenticatedResponseSchema(Schema):
    status: str
    token: str
    refresh_token: str | None = None
    user: str
    active: bool
    language: str | None
    is_superuser: bool = False
    is_staff: bool = False
    extra: AuthExtraSchema | None
    exp: int
    orig_iat: int
    refresh_exp: int | None = None
    session_id: str | None = None
    main_profile: int | None
    onboarding_completed: bool | None = None
    joined_workspace: bool | None = None


class SessionVerifyRequestSchema(Schema):
    token: str


class RefreshTokenRequestSchema(Schema):
    refresh_token: str


class LogoutRequestSchema(Schema):
    refresh_token: str


class LoginRequestSchema(Schema):
    username_or_email: str
    password: str


class RegisterRequestSchema(Schema):
    email: str
    password: str
    first_name: str = ""
    last_name: str = ""
    username: str | None = None
    language: str = "it"


class PublicUserSchema(Schema):
    id: int
    email: str
    username: str
    first_name: str
    last_name: str
    language: str
    is_active: bool


class AccessCodeRequestSchema(Schema):
    email: str


class AccessCodeRequestResponseSchema(Schema):
    detail: str
    status: str
    dev_code: str | None = None
    debug_flow_token: str | None = None


class AccessCodeConfirmSchema(Schema):
    email: str
    code: str


class GoogleAuthRequestSchema(Schema):
    credential: str = ""
    access_token: str = ""


class PasswordResetRequestSchema(Schema):
    email: str


class PasswordResetConfirmSchema(Schema):
    email: str
    code: str
    new_password: str


class GenericDetailResponseSchema(Schema):
    status: str
    detail: str


class OnboardingPrefillSchema(Schema):
    email: str
    first_name: str
    last_name: str
    phone: str
    language: str
    picture: str
    company_name: str
    company_email: str
    company_phone: str
    company_website: str
    company_vat_number: str
    company_description: str
    company_logo: str | None = None


class OnboardingRequiredResponseSchema(Schema):
    status: str
    onboarding_token: str
    prefill: OnboardingPrefillSchema


class OnboardingProfileUpdateSchema(Schema):
    onboarding_token: str
    first_name: str
    last_name: str
    phone: str
    language: str = "it"


class OnboardingCompleteSchema(Schema):
    onboarding_token: str
    first_name: str = ""
    last_name: str = ""
    phone: str = ""
    language: str = "it"
    company_name: str
    company_email: str = ""
    company_phone: str = ""
    company_website: str = ""
    company_vat_number: str = ""
    company_description: str = ""
    workspace_type: str = ""
    position: str = ""


class OnboardingInviteSchema(Schema):
    id: int
    invite_code: str | None = None
    uidb36: str
    token: str
    email: str
    role: str
    status: int
    company: dict | None = None


class OnboardingSessionSchema(Schema):
    onboarding_token: str


class OnboardingInviteCodeAcceptSchema(Schema):
    onboarding_token: str
    invite_code: str


class OnboardingWorkspaceAccessRequestSchema(Schema):
    onboarding_token: str
    position: str = ""
    message: str = ""
