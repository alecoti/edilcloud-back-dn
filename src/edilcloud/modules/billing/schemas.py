from datetime import datetime

from ninja import Schema


class BillingCatalogPriceSchema(Schema):
    interval: str
    price_id: str | None = None
    configured: bool


class BillingCatalogPlanSchema(Schema):
    code: str
    name: str
    description: str
    included_workspaces: int
    included_seats: int
    included_storage_bytes: int
    included_ai_tokens: int
    requires_contact: bool = False
    purchasable: bool = True
    prices: list[BillingCatalogPriceSchema]


class BillingCatalogAddonSchema(Schema):
    code: str
    name: str
    description: str
    unit_label: str
    unit_quantity: int
    prices: list[BillingCatalogPriceSchema]


class BillingCatalogTokenPackSchema(Schema):
    code: str
    name: str
    description: str
    token_count: int
    price_id: str | None = None
    configured: bool


class BillingCatalogSchema(Schema):
    default_plan_code: str
    billing_enabled: bool
    plans: list[BillingCatalogPlanSchema]
    addons: list[BillingCatalogAddonSchema]
    token_packs: list[BillingCatalogTokenPackSchema]


class BillingUsageMetricSchema(Schema):
    included: int
    addon: int
    limit: int
    used: int
    remaining: int


class BillingStorageMetricSchema(Schema):
    included_bytes: int
    addon_bytes: int
    limit_bytes: int
    used_bytes: int
    remaining_bytes: int


class BillingAITokensMetricSchema(Schema):
    monthly_included: int
    topup_balance: int
    total_available: int
    used_this_period: int
    remaining_this_period: int
    month_key: str


class BillingInvoiceSchema(Schema):
    id: int
    stripe_invoice_id: str
    invoice_number: str | None = None
    status: str | None = None
    currency: str
    subtotal_amount: int
    total_amount: int
    hosted_invoice_url: str | None = None
    invoice_pdf_url: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    paid_at: datetime | None = None


class BillingWorkspaceUsageSchema(Schema):
    workspace_id: int
    workspace_name: str
    active_members: int
    pending_invites: int
    storage_used_bytes: int


class BillingSummarySchema(Schema):
    account_id: int
    billing_status: str
    plan_code: str
    billing_interval: str
    currency: str
    cancel_at_period_end: bool
    app_access_enabled: bool
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    workspace_usage: BillingWorkspaceUsageSchema
    workspaces: BillingUsageMetricSchema
    seats: BillingUsageMetricSchema
    storage: BillingStorageMetricSchema
    ai_tokens: BillingAITokensMetricSchema
    invoices: list[BillingInvoiceSchema]
    catalog: BillingCatalogSchema
    management_urls: dict[str, str | None]


class BillingCheckoutRequestSchema(Schema):
    session_type: str
    plan_code: str | None = None
    billing_interval: str = "month"
    workspace_quantity: int = 0
    seat_quantity: int = 0
    storage_block_quantity: int = 0
    token_pack_code: str | None = None


class BillingCheckoutSchema(Schema):
    session_id: str
    session_type: str
    status: str
    checkout_url: str


class BillingPortalSchema(Schema):
    url: str


class BillingCheckoutStatusSchema(Schema):
    session_id: str
    status: str
    session_type: str
    workspace_id: int | None = None
    checkout_url: str | None = None


class BillingWebhookResponseSchema(Schema):
    status: str
    detail: str
