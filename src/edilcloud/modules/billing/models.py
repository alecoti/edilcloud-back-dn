from django.conf import settings
from django.db import models

from edilcloud.modules.workspaces.models import Workspace


class BillingStatus(models.TextChoices):
    TRIAL = "trial", "Trial"
    ACTIVE = "active", "Active"
    INCOMPLETE = "incomplete", "Incomplete"
    INCOMPLETE_EXPIRED = "incomplete_expired", "Incomplete expired"
    PAST_DUE = "past_due", "Past due"
    UNPAID = "unpaid", "Unpaid"
    CANCELED = "canceled", "Canceled"


class BillingInterval(models.TextChoices):
    MONTH = "month", "Month"
    YEAR = "year", "Year"
    ONE_TIME = "one_time", "One time"


class CheckoutMode(models.TextChoices):
    SUBSCRIPTION = "subscription", "Subscription"
    PAYMENT = "payment", "Payment"


class CheckoutSessionType(models.TextChoices):
    SUBSCRIPTION = "subscription", "Subscription"
    AI_TOKENS = "ai_tokens", "AI tokens"


class CheckoutSessionStatus(models.TextChoices):
    OPEN = "open", "Open"
    COMPLETED = "completed", "Completed"
    EXPIRED = "expired", "Expired"
    CANCELED = "canceled", "Canceled"


class TokenLedgerEntryType(models.TextChoices):
    PURCHASE = "purchase", "Purchase"
    USAGE = "usage", "Usage"
    ADJUSTMENT = "adjustment", "Adjustment"


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BillingAccount(TimestampedModel):
    owner_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="billing_account",
    )
    status = models.CharField(
        max_length=32,
        choices=BillingStatus.choices,
        default=BillingStatus.TRIAL,
    )
    plan_code = models.CharField(max_length=64, default="trial")
    billing_interval = models.CharField(
        max_length=16,
        choices=BillingInterval.choices,
        default=BillingInterval.MONTH,
    )
    currency = models.CharField(max_length=8, default="eur")
    stripe_customer_id = models.CharField(max_length=128, blank=True)
    stripe_subscription_id = models.CharField(max_length=128, blank=True)
    stripe_subscription_item_ids = models.JSONField(default=dict, blank=True)
    workspace_limit_base = models.PositiveIntegerField(default=1)
    workspace_limit_addon = models.PositiveIntegerField(default=0)
    seat_limit_base = models.PositiveIntegerField(default=5)
    seat_limit_addon = models.PositiveIntegerField(default=0)
    storage_quota_bytes_base = models.BigIntegerField(default=10 * 1024 * 1024 * 1024)
    storage_quota_bytes_addon = models.BigIntegerField(default=0)
    monthly_ai_tokens_base = models.PositiveBigIntegerField(default=100_000)
    ai_token_balance_topup = models.PositiveBigIntegerField(default=0)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    app_access_enabled = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("owner_user_id",)

    def __str__(self) -> str:
        return f"BillingAccount<{self.owner_user_id}:{self.plan_code}>"


class BillingWorkspace(TimestampedModel):
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name="workspace_assignments",
    )
    workspace = models.OneToOneField(
        Workspace,
        on_delete=models.CASCADE,
        related_name="billing_assignment",
    )

    class Meta:
        ordering = ("workspace_id",)

    def __str__(self) -> str:
        return f"BillingWorkspace<{self.workspace_id}>"


class BillingCheckoutSession(TimestampedModel):
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name="checkout_sessions",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        related_name="billing_checkout_sessions",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        "workspaces.Profile",
        on_delete=models.SET_NULL,
        related_name="created_billing_checkout_sessions",
        null=True,
        blank=True,
    )
    mode = models.CharField(
        max_length=24,
        choices=CheckoutMode.choices,
    )
    session_type = models.CharField(
        max_length=24,
        choices=CheckoutSessionType.choices,
    )
    status = models.CharField(
        max_length=24,
        choices=CheckoutSessionStatus.choices,
        default=CheckoutSessionStatus.OPEN,
    )
    stripe_session_id = models.CharField(max_length=128, unique=True)
    checkout_url = models.URLField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"BillingCheckoutSession<{self.stripe_session_id}>"


class BillingInvoice(TimestampedModel):
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name="invoices",
    )
    stripe_invoice_id = models.CharField(max_length=128, unique=True)
    invoice_number = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=64, blank=True)
    currency = models.CharField(max_length=8, default="eur")
    subtotal_amount = models.BigIntegerField(default=0)
    total_amount = models.BigIntegerField(default=0)
    hosted_invoice_url = models.URLField(blank=True)
    invoice_pdf_url = models.URLField(blank=True)
    period_start = models.DateTimeField(null=True, blank=True)
    period_end = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-period_start", "-created_at", "-id")

    def __str__(self) -> str:
        return f"BillingInvoice<{self.stripe_invoice_id}>"


class BillingWebhookEvent(TimestampedModel):
    stripe_event_id = models.CharField(max_length=128, unique=True)
    event_type = models.CharField(max_length=128)
    processed_at = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return f"BillingWebhookEvent<{self.stripe_event_id}>"


class BillingTokenLedger(TimestampedModel):
    billing_account = models.ForeignKey(
        BillingAccount,
        on_delete=models.CASCADE,
        related_name="token_ledger_entries",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.SET_NULL,
        related_name="billing_token_ledger_entries",
        null=True,
        blank=True,
    )
    entry_type = models.CharField(
        max_length=24,
        choices=TokenLedgerEntryType.choices,
    )
    tokens_delta = models.BigIntegerField()
    balance_after = models.BigIntegerField(default=0)
    reference_kind = models.CharField(max_length=64, blank=True)
    reference_id = models.CharField(max_length=128, blank=True)
    description = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("billing_account", "created_at")),
            models.Index(fields=("reference_kind", "reference_id")),
        ]

    def __str__(self) -> str:
        return f"BillingTokenLedger<{self.billing_account_id}:{self.tokens_delta}>"
