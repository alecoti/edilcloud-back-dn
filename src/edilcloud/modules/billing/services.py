from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from typing import Any

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from edilcloud.modules.assistant.models import ProjectAssistantUsage
from edilcloud.modules.billing.models import (
    BillingAccount,
    BillingCheckoutSession,
    BillingInvoice,
    BillingInterval,
    BillingStatus,
    BillingTokenLedger,
    BillingWebhookEvent,
    BillingWorkspace,
    CheckoutMode,
    CheckoutSessionStatus,
    CheckoutSessionType,
    TokenLedgerEntryType,
)
from edilcloud.modules.projects.models import (
    CommentAttachment,
    PostAttachment,
    ProjectDocument,
    ProjectPhoto,
)
from edilcloud.modules.workspaces.models import Profile, Workspace, WorkspaceInvite, WorkspaceRole
from edilcloud.platform.telemetry import increment_counter


GIGABYTE = 1024 * 1024 * 1024
DEFAULT_STORAGE_BLOCK_BYTES = 100 * GIGABYTE
DEFAULT_AI_REQUEST_HEADROOM = 4_000


@dataclass(frozen=True)
class PlanSpec:
    code: str
    name: str
    description: str
    included_workspaces: int
    included_seats: int
    included_storage_bytes: int
    included_ai_tokens: int
    monthly_price_env: str
    yearly_price_env: str
    purchasable: bool = True
    requires_contact: bool = False


@dataclass(frozen=True)
class AddonSpec:
    code: str
    name: str
    description: str
    unit_label: str
    unit_quantity: int
    monthly_price_env: str
    yearly_price_env: str


@dataclass(frozen=True)
class TokenPackSpec:
    code: str
    name: str
    description: str
    token_count: int
    price_env: str


PLAN_CATALOG: tuple[PlanSpec, ...] = (
    PlanSpec(
        code="trial",
        name="Trial",
        description="Accesso iniziale per configurare workspace, provare flussi e preparare il go-live.",
        included_workspaces=1,
        included_seats=5,
        included_storage_bytes=10 * GIGABYTE,
        included_ai_tokens=100_000,
        monthly_price_env="",
        yearly_price_env="",
        purchasable=False,
    ),
    PlanSpec(
        code="fondazioni",
        name="Fondazioni",
        description="Per studi tecnici e squadre snelle che vogliono operare in modo ordinato su pochi cantieri.",
        included_workspaces=1,
        included_seats=10,
        included_storage_bytes=50 * GIGABYTE,
        included_ai_tokens=500_000,
        monthly_price_env="STRIPE_PRICE_PLAN_FONDAZIONI_MONTHLY",
        yearly_price_env="STRIPE_PRICE_PLAN_FONDAZIONI_YEARLY",
    ),
    PlanSpec(
        code="struttura",
        name="Struttura",
        description="Per imprese e uffici tecnici che gestiscono piu commesse, team e documenti in continuita.",
        included_workspaces=3,
        included_seats=30,
        included_storage_bytes=250 * GIGABYTE,
        included_ai_tokens=2_000_000,
        monthly_price_env="STRIPE_PRICE_PLAN_STRUTTURA_MONTHLY",
        yearly_price_env="STRIPE_PRICE_PLAN_STRUTTURA_YEARLY",
    ),
    PlanSpec(
        code="direzione_lavori",
        name="Direzione Lavori",
        description="Per organizzazioni che vogliono controllo multi-workspace, governance e setup dedicato.",
        included_workspaces=10,
        included_seats=100,
        included_storage_bytes=1_000 * GIGABYTE,
        included_ai_tokens=10_000_000,
        monthly_price_env="STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_MONTHLY",
        yearly_price_env="STRIPE_PRICE_PLAN_DIREZIONE_LAVORI_YEARLY",
        requires_contact=True,
        purchasable=False,
    ),
)

ADDON_CATALOG: tuple[AddonSpec, ...] = (
    AddonSpec(
        code="workspace",
        name="Workspace aggiuntivo",
        description="Aumenta il numero di workspace operativi coperti dallo stesso account.",
        unit_label="workspace",
        unit_quantity=1,
        monthly_price_env="STRIPE_PRICE_ADDON_WORKSPACE_MONTHLY",
        yearly_price_env="STRIPE_PRICE_ADDON_WORKSPACE_YEARLY",
    ),
    AddonSpec(
        code="seat",
        name="Utente aggiuntivo",
        description="Aumenta il numero di membri attivi che puoi mantenere dentro i workspace coperti.",
        unit_label="utente",
        unit_quantity=1,
        monthly_price_env="STRIPE_PRICE_ADDON_SEAT_MONTHLY",
        yearly_price_env="STRIPE_PRICE_ADDON_SEAT_YEARLY",
    ),
    AddonSpec(
        code="storage_100gb",
        name="Spazio aggiuntivo",
        description="Aggiunge un blocco ricorrente di spazio per documenti, allegati, foto e materiali di commessa.",
        unit_label="100 GB",
        unit_quantity=DEFAULT_STORAGE_BLOCK_BYTES,
        monthly_price_env="STRIPE_PRICE_ADDON_STORAGE_100GB_MONTHLY",
        yearly_price_env="STRIPE_PRICE_ADDON_STORAGE_100GB_YEARLY",
    ),
)

TOKEN_PACK_CATALOG: tuple[TokenPackSpec, ...] = (
    TokenPackSpec(
        code="ai_1m",
        name="Pacchetto AI 1M",
        description="Pacchetto una tantum per aumentare il plafond AI disponibile.",
        token_count=1_000_000,
        price_env="STRIPE_PRICE_AI_PACK_1M",
    ),
    TokenPackSpec(
        code="ai_5m",
        name="Pacchetto AI 5M",
        description="Pacchetto una tantum per team che usano assistente e drafting in modo ricorrente.",
        token_count=5_000_000,
        price_env="STRIPE_PRICE_AI_PACK_5M",
    ),
    TokenPackSpec(
        code="ai_20m",
        name="Pacchetto AI 20M",
        description="Pacchetto una tantum per uso intensivo AI su documenti, reportistica e retrieval.",
        token_count=20_000_000,
        price_env="STRIPE_PRICE_AI_PACK_20M",
    ),
)


def get_env_price(env_name: str) -> str:
    return getattr(settings, env_name, "").strip() if env_name else ""


def billing_enabled() -> bool:
    return bool(getattr(settings, "STRIPE_SECRET_KEY", "").strip())


def get_plan_spec(code: str | None) -> PlanSpec:
    normalized = (code or "trial").strip().lower() or "trial"
    for item in PLAN_CATALOG:
        if item.code == normalized:
            return item
    return PLAN_CATALOG[0]


def get_addon_spec(code: str | None) -> AddonSpec | None:
    normalized = (code or "").strip().lower()
    for item in ADDON_CATALOG:
        if item.code == normalized:
            return item
    return None


def get_token_pack_spec(code: str | None) -> TokenPackSpec | None:
    normalized = (code or "").strip().lower()
    for item in TOKEN_PACK_CATALOG:
        if item.code == normalized:
            return item
    return None


def plan_price_id(plan: PlanSpec, interval: str) -> str:
    if interval == BillingInterval.YEAR:
        return get_env_price(plan.yearly_price_env)
    return get_env_price(plan.monthly_price_env)


def addon_price_id(addon: AddonSpec, interval: str) -> str:
    if interval == BillingInterval.YEAR:
        return get_env_price(addon.yearly_price_env)
    return get_env_price(addon.monthly_price_env)


def find_plan_code_by_price_id(price_id: str | None) -> str | None:
    normalized = (price_id or "").strip()
    if not normalized:
        return None
    for plan in PLAN_CATALOG:
        if normalized in {
            plan_price_id(plan, BillingInterval.MONTH),
            plan_price_id(plan, BillingInterval.YEAR),
        }:
            return plan.code
    return None


def find_addon_code_by_price_id(price_id: str | None) -> str | None:
    normalized = (price_id or "").strip()
    if not normalized:
        return None
    for addon in ADDON_CATALOG:
        if normalized in {
            addon_price_id(addon, BillingInterval.MONTH),
            addon_price_id(addon, BillingInterval.YEAR),
        }:
            return addon.code
    return None


def find_token_pack_by_price_id(price_id: str | None) -> TokenPackSpec | None:
    normalized = (price_id or "").strip()
    if not normalized:
        return None
    for item in TOKEN_PACK_CATALOG:
        if get_env_price(item.price_env) == normalized:
            return item
    return None


def serialize_billing_catalog() -> dict[str, Any]:
    return {
        "default_plan_code": "fondazioni",
        "billing_enabled": billing_enabled(),
        "plans": [
            {
                "code": plan.code,
                "name": plan.name,
                "description": plan.description,
                "included_workspaces": plan.included_workspaces,
                "included_seats": plan.included_seats,
                "included_storage_bytes": plan.included_storage_bytes,
                "included_ai_tokens": plan.included_ai_tokens,
                "requires_contact": plan.requires_contact,
                "purchasable": plan.purchasable,
                "prices": [
                    {
                        "interval": BillingInterval.MONTH,
                        "price_id": plan_price_id(plan, BillingInterval.MONTH) or None,
                        "configured": bool(plan_price_id(plan, BillingInterval.MONTH)),
                    },
                    {
                        "interval": BillingInterval.YEAR,
                        "price_id": plan_price_id(plan, BillingInterval.YEAR) or None,
                        "configured": bool(plan_price_id(plan, BillingInterval.YEAR)),
                    },
                ],
            }
            for plan in PLAN_CATALOG
        ],
        "addons": [
            {
                "code": addon.code,
                "name": addon.name,
                "description": addon.description,
                "unit_label": addon.unit_label,
                "unit_quantity": addon.unit_quantity,
                "prices": [
                    {
                        "interval": BillingInterval.MONTH,
                        "price_id": addon_price_id(addon, BillingInterval.MONTH) or None,
                        "configured": bool(addon_price_id(addon, BillingInterval.MONTH)),
                    },
                    {
                        "interval": BillingInterval.YEAR,
                        "price_id": addon_price_id(addon, BillingInterval.YEAR) or None,
                        "configured": bool(addon_price_id(addon, BillingInterval.YEAR)),
                    },
                ],
            }
            for addon in ADDON_CATALOG
        ],
        "token_packs": [
            {
                "code": pack.code,
                "name": pack.name,
                "description": pack.description,
                "token_count": pack.token_count,
                "price_id": get_env_price(pack.price_env) or None,
                "configured": bool(get_env_price(pack.price_env)),
            }
            for pack in TOKEN_PACK_CATALOG
        ],
    }


def get_stripe_client():
    if not billing_enabled():
        raise ValueError("Stripe non configurato.")
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    stripe.api_version = getattr(settings, "STRIPE_API_VERSION", "2026-02-25.clover")
    stripe.max_network_retries = 2
    return stripe


def stripe_value(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def to_datetime(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    try:
        return datetime.fromtimestamp(int(value), tz=datetime_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def normalize_checkout_status(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {
        CheckoutSessionStatus.COMPLETED,
        CheckoutSessionStatus.EXPIRED,
        CheckoutSessionStatus.CANCELED,
    }:
        return normalized
    return CheckoutSessionStatus.OPEN


def subscription_allows_access(status: str | None) -> bool:
    return (status or "").strip().lower() in {
        BillingStatus.TRIAL,
        BillingStatus.ACTIVE,
        BillingStatus.PAST_DUE,
    }


def get_or_create_billing_account_for_user(user) -> BillingAccount:
    trial_plan = get_plan_spec("trial")
    account, _created = BillingAccount.objects.get_or_create(
        owner_user=user,
        defaults={
            "status": BillingStatus.TRIAL,
            "plan_code": trial_plan.code,
            "billing_interval": BillingInterval.MONTH,
            "currency": "eur",
            "workspace_limit_base": trial_plan.included_workspaces,
            "seat_limit_base": trial_plan.included_seats,
            "storage_quota_bytes_base": trial_plan.included_storage_bytes,
            "monthly_ai_tokens_base": trial_plan.included_ai_tokens,
            "app_access_enabled": True,
        },
    )
    return account


def get_workspace_owner_user(workspace: Workspace):
    owner_profile = (
        workspace.profiles.select_related("user")
        .filter(role=WorkspaceRole.OWNER, is_active=True, user__is_active=True)
        .order_by("id")
        .first()
    )
    if owner_profile is None:
        raise ValueError("Workspace senza owner valido per il billing.")
    return owner_profile.user


def sync_account_workspace_assignments(account: BillingAccount) -> None:
    workspace_ids = list(
        Workspace.objects.filter(
            profiles__user=account.owner_user,
            profiles__role=WorkspaceRole.OWNER,
            profiles__is_active=True,
            is_active=True,
        )
        .distinct()
        .values_list("id", flat=True)
    )
    existing_ids = set(
        BillingWorkspace.objects.filter(
            billing_account=account,
            workspace_id__in=workspace_ids,
        ).values_list("workspace_id", flat=True)
    )
    missing_ids = [workspace_id for workspace_id in workspace_ids if workspace_id not in existing_ids]
    if missing_ids:
        BillingWorkspace.objects.bulk_create(
            [
                BillingWorkspace(billing_account=account, workspace_id=workspace_id)
                for workspace_id in missing_ids
            ],
            ignore_conflicts=True,
        )


def ensure_workspace_attached_to_owner_account(workspace: Workspace, owner_user=None) -> BillingAccount:
    owner = owner_user or get_workspace_owner_user(workspace)
    account = get_or_create_billing_account_for_user(owner)
    assignment, created = BillingWorkspace.objects.get_or_create(
        workspace=workspace,
        defaults={"billing_account": account},
    )
    if not created and assignment.billing_account_id != account.id:
        assignment.billing_account = account
        assignment.save(update_fields=["billing_account", "updated_at"])
    sync_account_workspace_assignments(account)
    return account


def get_workspace_billing_account(workspace: Workspace) -> BillingAccount:
    assignment = getattr(workspace, "billing_assignment", None)
    if assignment is None:
        return ensure_workspace_attached_to_owner_account(workspace)
    account = assignment.billing_account
    sync_account_workspace_assignments(account)
    return account


def account_workspace_ids(account: BillingAccount) -> list[int]:
    sync_account_workspace_assignments(account)
    return list(
        account.workspace_assignments.select_related("workspace")
        .filter(workspace__is_active=True)
        .values_list("workspace_id", flat=True)
    )


def active_workspace_count(account: BillingAccount) -> int:
    return len(account_workspace_ids(account))


def active_seat_count(account: BillingAccount) -> int:
    workspace_ids = account_workspace_ids(account)
    if not workspace_ids:
        return 0
    return Profile.objects.filter(
        workspace_id__in=workspace_ids,
        is_active=True,
        workspace__is_active=True,
        user__is_active=True,
    ).count()


def pending_invite_count_for_account(account: BillingAccount) -> int:
    workspace_ids = account_workspace_ids(account)
    if not workspace_ids:
        return 0
    now = timezone.now()
    return WorkspaceInvite.objects.filter(
        workspace_id__in=workspace_ids,
        accepted_at__isnull=True,
        refused_at__isnull=True,
        expires_at__gte=now,
    ).count()


def pending_invite_count_for_workspace(workspace: Workspace) -> int:
    now = timezone.now()
    return WorkspaceInvite.objects.filter(
        workspace=workspace,
        accepted_at__isnull=True,
        refused_at__isnull=True,
        expires_at__gte=now,
    ).count()


def storage_size_for_name(name: str | None) -> int:
    normalized = (name or "").strip()
    if not normalized:
        return 0
    try:
        return int(default_storage.size(normalized))
    except Exception:
        return 0


def calculate_storage_usage_for_workspace_ids(workspace_ids: list[int]) -> int:
    if not workspace_ids:
        return 0
    document_names = ProjectDocument.objects.filter(project__workspace_id__in=workspace_ids).values_list(
        "document",
        flat=True,
    )
    photo_names = ProjectPhoto.objects.filter(project__workspace_id__in=workspace_ids).values_list(
        "photo",
        flat=True,
    )
    post_attachment_names = PostAttachment.objects.filter(
        post__project__workspace_id__in=workspace_ids
    ).values_list("file", flat=True)
    comment_attachment_names = CommentAttachment.objects.filter(
        comment__post__project__workspace_id__in=workspace_ids
    ).values_list("file", flat=True)
    total = 0
    for name in [*document_names, *photo_names, *post_attachment_names, *comment_attachment_names]:
        total += storage_size_for_name(str(name))
    return total


def calculate_account_storage_usage(account: BillingAccount) -> int:
    return calculate_storage_usage_for_workspace_ids(account_workspace_ids(account))


def calculate_workspace_storage_usage(workspace: Workspace) -> int:
    return calculate_storage_usage_for_workspace_ids([workspace.id])


def billing_month_bounds(reference: datetime | None = None) -> tuple[datetime, datetime]:
    current = reference or timezone.now()
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def calculate_account_ai_usage(account: BillingAccount, *, reference: datetime | None = None) -> dict[str, int | str]:
    start, end = billing_month_bounds(reference)
    workspace_ids = account_workspace_ids(account)
    total_used = (
        ProjectAssistantUsage.objects.filter(
            project__workspace_id__in=workspace_ids,
            created_at__gte=start,
            created_at__lt=end,
        ).aggregate(total=Sum("total_tokens")).get("total")
        or 0
    )
    return {
        "used": int(total_used),
        "month_key": start.strftime("%Y-%m"),
    }


def entitlement_snapshot(account: BillingAccount) -> dict[str, Any]:
    workspaces_used = active_workspace_count(account)
    seats_used = active_seat_count(account)
    storage_used = calculate_account_storage_usage(account)
    ai_usage = calculate_account_ai_usage(account)

    workspace_limit = int(account.workspace_limit_base + account.workspace_limit_addon)
    seat_limit = int(account.seat_limit_base + account.seat_limit_addon)
    storage_limit = int(account.storage_quota_bytes_base + account.storage_quota_bytes_addon)
    ai_total = int(account.monthly_ai_tokens_base + account.ai_token_balance_topup)
    ai_used = int(ai_usage["used"])

    return {
        "workspaces": {
            "included": int(account.workspace_limit_base),
            "addon": int(account.workspace_limit_addon),
            "limit": workspace_limit,
            "used": workspaces_used,
            "remaining": max(workspace_limit - workspaces_used, 0),
        },
        "seats": {
            "included": int(account.seat_limit_base),
            "addon": int(account.seat_limit_addon),
            "limit": seat_limit,
            "used": seats_used,
            "remaining": max(seat_limit - seats_used, 0),
        },
        "storage": {
            "included_bytes": int(account.storage_quota_bytes_base),
            "addon_bytes": int(account.storage_quota_bytes_addon),
            "limit_bytes": storage_limit,
            "used_bytes": storage_used,
            "remaining_bytes": max(storage_limit - storage_used, 0),
        },
        "ai_tokens": {
            "monthly_included": int(account.monthly_ai_tokens_base),
            "topup_balance": int(account.ai_token_balance_topup),
            "total_available": ai_total,
            "used_this_period": ai_used,
            "remaining_this_period": max(ai_total - ai_used, 0),
            "month_key": str(ai_usage["month_key"]),
        },
    }


def serialize_invoice(invoice: BillingInvoice) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "stripe_invoice_id": invoice.stripe_invoice_id,
        "invoice_number": invoice.invoice_number or None,
        "status": invoice.status or None,
        "currency": invoice.currency,
        "subtotal_amount": invoice.subtotal_amount,
        "total_amount": invoice.total_amount,
        "hosted_invoice_url": invoice.hosted_invoice_url or None,
        "invoice_pdf_url": invoice.invoice_pdf_url or None,
        "period_start": invoice.period_start,
        "period_end": invoice.period_end,
        "paid_at": invoice.paid_at,
    }


def workspace_usage_summary(workspace: Workspace) -> dict[str, Any]:
    active_members = workspace.profiles.filter(is_active=True, user__is_active=True).count()
    return {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "active_members": active_members,
        "pending_invites": pending_invite_count_for_workspace(workspace),
        "storage_used_bytes": calculate_workspace_storage_usage(workspace),
    }


def serialize_billing_summary_for_workspace(workspace: Workspace) -> dict[str, Any]:
    account = get_workspace_billing_account(workspace)
    snapshot = entitlement_snapshot(account)
    invoices = [
        serialize_invoice(invoice)
        for invoice in account.invoices.order_by("-period_start", "-created_at", "-id")[:12]
    ]
    payments_base = getattr(settings, "PAYMENTS_SITE_URL", getattr(settings, "APP_FRONTEND_URL", "")).rstrip("/")
    app_base = getattr(settings, "APP_FRONTEND_URL", "").rstrip("/")
    marketing_base = getattr(settings, "MARKETING_SITE_URL", "").rstrip("/")
    return {
        "account_id": account.id,
        "billing_status": account.status,
        "plan_code": account.plan_code,
        "billing_interval": account.billing_interval,
        "currency": account.currency,
        "cancel_at_period_end": account.cancel_at_period_end,
        "app_access_enabled": account.app_access_enabled,
        "stripe_customer_id": account.stripe_customer_id or None,
        "stripe_subscription_id": account.stripe_subscription_id or None,
        "current_period_start": account.current_period_start,
        "current_period_end": account.current_period_end,
        "workspace_usage": workspace_usage_summary(workspace),
        "workspaces": snapshot["workspaces"],
        "seats": snapshot["seats"],
        "storage": snapshot["storage"],
        "ai_tokens": snapshot["ai_tokens"],
        "invoices": invoices,
        "catalog": serialize_billing_catalog(),
        "management_urls": {
            "payments_site": f"{payments_base}/?workspace_id={workspace.id}" if payments_base else None,
            "app_return": f"{app_base}/dashboard?tab=billing&workspace={workspace.id}" if app_base else None,
            "marketing_site": marketing_base or None,
        },
    }


def get_workspace_billing_summary(
    user,
    *,
    claims: dict | None = None,
    workspace_id: int | None = None,
) -> dict[str, Any]:
    from edilcloud.modules.workspaces.services import get_manageable_current_profile, get_manageable_profile

    if workspace_id is None:
        profile = get_manageable_current_profile(
            user,
            profile_id=int(claims.get("main_profile")) if claims and claims.get("main_profile") else None,
        )
    else:
        profile = get_manageable_profile(user, workspace_id)
    return serialize_billing_summary_for_workspace(profile.workspace)


def assert_workspace_creation_allowed(owner_user) -> None:
    account = get_or_create_billing_account_for_user(owner_user)
    sync_account_workspace_assignments(account)
    snapshot = entitlement_snapshot(account)
    if snapshot["workspaces"]["remaining"] <= 0:
        raise ValueError(
            "Hai raggiunto il numero massimo di workspace inclusi nel piano attuale. "
            "Aumenta il piano o acquista workspace aggiuntivi."
        )


def assert_workspace_seat_available(workspace: Workspace, *, reserve_pending_invite: bool = False) -> None:
    account = get_workspace_billing_account(workspace)
    snapshot = entitlement_snapshot(account)
    seats_used = snapshot["seats"]["used"]
    if reserve_pending_invite:
        seats_used += pending_invite_count_for_account(account)
    if seats_used >= snapshot["seats"]["limit"]:
        raise ValueError(
            "Hai raggiunto il numero massimo di utenti coperti dal piano attuale. "
            "Aumenta il piano o acquista utenti aggiuntivi."
        )


def assert_storage_quota_available(workspace: Workspace, *, incoming_bytes: int) -> None:
    account = get_workspace_billing_account(workspace)
    snapshot = entitlement_snapshot(account)
    if incoming_bytes <= 0:
        return
    if snapshot["storage"]["used_bytes"] + incoming_bytes > snapshot["storage"]["limit_bytes"]:
        raise ValueError(
            "Spazio di archiviazione insufficiente per completare il caricamento. "
            "Acquista spazio aggiuntivo o libera risorse."
        )


def assert_ai_request_headroom(workspace: Workspace, *, minimum_headroom: int = DEFAULT_AI_REQUEST_HEADROOM) -> None:
    account = get_workspace_billing_account(workspace)
    snapshot = entitlement_snapshot(account)
    if snapshot["ai_tokens"]["remaining_this_period"] < max(minimum_headroom, 1):
        raise ValueError(
            "Token AI insufficienti per completare nuove richieste. "
            "Acquista un pacchetto AI o attendi il prossimo reset mensile."
        )


def apply_ai_usage_to_billing(*, workspace: Workspace, total_tokens: int, reference_id: str) -> None:
    account = get_workspace_billing_account(workspace)
    included = int(account.monthly_ai_tokens_base)
    ai_usage = calculate_account_ai_usage(account)
    current_used = int(ai_usage["used"])
    previous_used = max(current_used - max(total_tokens, 0), 0)
    current_overage = max(current_used - included, 0)
    previous_overage = max(previous_used - included, 0)
    delta_to_deduct = max(current_overage - previous_overage, 0)
    if delta_to_deduct <= 0:
        return

    deducted = min(int(account.ai_token_balance_topup), delta_to_deduct)
    account.ai_token_balance_topup = max(int(account.ai_token_balance_topup) - deducted, 0)
    account.save(update_fields=["ai_token_balance_topup", "updated_at"])
    BillingTokenLedger.objects.create(
        billing_account=account,
        workspace=workspace,
        entry_type=TokenLedgerEntryType.USAGE,
        tokens_delta=-deducted,
        balance_after=int(account.ai_token_balance_topup),
        reference_kind="assistant_usage",
        reference_id=str(reference_id),
        description="Consumo token AI oltre il plafond incluso",
        metadata={"deducted_tokens": deducted, "requested_tokens": delta_to_deduct},
    )


def ensure_stripe_customer(account: BillingAccount) -> str:
    if account.stripe_customer_id:
        return account.stripe_customer_id
    stripe = get_stripe_client()
    customer = stripe.Customer.create(
        email=account.owner_user.email,
        name=f"{account.owner_user.first_name} {account.owner_user.last_name}".strip()
        or account.owner_user.email,
        metadata={"billing_account_id": str(account.id)},
    )
    customer_id = str(stripe_value(customer, "id", ""))
    account.stripe_customer_id = customer_id
    account.save(update_fields=["stripe_customer_id", "updated_at"])
    return customer_id


def build_checkout_success_url(*, workspace_id: int, session_type: str) -> str:
    payments_site = getattr(settings, "PAYMENTS_SITE_URL", getattr(settings, "APP_FRONTEND_URL", "")).rstrip("/")
    return (
        f"{payments_site}/success"
        f"?workspace_id={workspace_id}"
        f"&session_type={session_type}"
        f"&checkout_session_id={{CHECKOUT_SESSION_ID}}"
    )


def build_checkout_cancel_url(*, workspace_id: int, session_type: str) -> str:
    payments_site = getattr(settings, "PAYMENTS_SITE_URL", getattr(settings, "APP_FRONTEND_URL", "")).rstrip("/")
    return f"{payments_site}/cancel?workspace_id={workspace_id}&session_type={session_type}"


def create_checkout_session_record(
    *,
    account: BillingAccount,
    workspace: Workspace,
    created_by: Profile,
    stripe_session: Any,
    session_type: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    session = BillingCheckoutSession.objects.create(
        billing_account=account,
        workspace=workspace,
        created_by=created_by,
        mode=stripe_value(stripe_session, "mode", CheckoutMode.SUBSCRIPTION),
        session_type=session_type,
        status=normalize_checkout_status(stripe_value(stripe_session, "status", CheckoutSessionStatus.OPEN)),
        stripe_session_id=stripe_value(stripe_session, "id", ""),
        checkout_url=stripe_value(stripe_session, "url", "") or "",
        payload=payload,
    )
    return {
        "session_id": session.stripe_session_id,
        "session_type": session.session_type,
        "status": session.status,
        "checkout_url": session.checkout_url,
    }


def create_subscription_checkout_for_workspace(
    *,
    profile: Profile,
    workspace: Workspace,
    plan_code: str,
    billing_interval: str,
    workspace_quantity: int,
    seat_quantity: int,
    storage_block_quantity: int,
) -> dict[str, Any]:
    account = get_workspace_billing_account(workspace)
    if account.stripe_subscription_id and account.status in {
        BillingStatus.ACTIVE,
        BillingStatus.PAST_DUE,
        BillingStatus.INCOMPLETE,
        BillingStatus.TRIAL,
    }:
        raise ValueError(
            "Esiste gia un abbonamento Stripe collegato. Usa il portale cliente per modificare piano o quantita."
        )

    plan = get_plan_spec(plan_code)
    if not plan.purchasable or plan.requires_contact:
        raise ValueError("Questo piano richiede un contatto commerciale e non e acquistabile in self-service.")

    interval = BillingInterval.YEAR if billing_interval == BillingInterval.YEAR else BillingInterval.MONTH
    base_price_id = plan_price_id(plan, interval)
    if not base_price_id:
        raise ValueError("Il prezzo Stripe del piano selezionato non e configurato.")

    line_items: list[dict[str, Any]] = [{"price": base_price_id, "quantity": 1}]
    if workspace_quantity > 0:
        addon = get_addon_spec("workspace")
        addon_price = addon_price_id(addon, interval) if addon else ""
        if not addon_price:
            raise ValueError("Il prezzo Stripe per i workspace aggiuntivi non e configurato.")
        line_items.append({"price": addon_price, "quantity": int(workspace_quantity)})
    if seat_quantity > 0:
        addon = get_addon_spec("seat")
        addon_price = addon_price_id(addon, interval) if addon else ""
        if not addon_price:
            raise ValueError("Il prezzo Stripe per gli utenti aggiuntivi non e configurato.")
        line_items.append({"price": addon_price, "quantity": int(seat_quantity)})
    if storage_block_quantity > 0:
        addon = get_addon_spec("storage_100gb")
        addon_price = addon_price_id(addon, interval) if addon else ""
        if not addon_price:
            raise ValueError("Il prezzo Stripe per lo spazio aggiuntivo non e configurato.")
        line_items.append({"price": addon_price, "quantity": int(storage_block_quantity)})

    metadata = {
        "billing_account_id": str(account.id),
        "workspace_id": str(workspace.id),
        "session_type": CheckoutSessionType.SUBSCRIPTION,
        "plan_code": plan.code,
        "billing_interval": interval,
        "workspace_quantity": str(max(int(workspace_quantity), 0)),
        "seat_quantity": str(max(int(seat_quantity), 0)),
        "storage_block_quantity": str(max(int(storage_block_quantity), 0)),
    }
    stripe = get_stripe_client()
    checkout_session = stripe.checkout.Session.create(
        mode=CheckoutMode.SUBSCRIPTION,
        customer=ensure_stripe_customer(account),
        line_items=line_items,
        allow_promotion_codes=True,
        success_url=build_checkout_success_url(
            workspace_id=workspace.id,
            session_type=CheckoutSessionType.SUBSCRIPTION,
        ),
        cancel_url=build_checkout_cancel_url(
            workspace_id=workspace.id,
            session_type=CheckoutSessionType.SUBSCRIPTION,
        ),
        metadata=metadata,
        subscription_data={"metadata": metadata},
    )
    increment_counter("billing.checkout.created", session_type=CheckoutSessionType.SUBSCRIPTION)
    return create_checkout_session_record(
        account=account,
        workspace=workspace,
        created_by=profile,
        stripe_session=checkout_session,
        session_type=CheckoutSessionType.SUBSCRIPTION,
        payload={
            "plan_code": plan.code,
            "billing_interval": interval,
            "workspace_quantity": workspace_quantity,
            "seat_quantity": seat_quantity,
            "storage_block_quantity": storage_block_quantity,
        },
    )


def create_ai_token_checkout_for_workspace(
    *,
    profile: Profile,
    workspace: Workspace,
    token_pack_code: str,
) -> dict[str, Any]:
    account = get_workspace_billing_account(workspace)
    pack = get_token_pack_spec(token_pack_code)
    if pack is None:
        raise ValueError("Pacchetto token AI non valido.")
    price_id = get_env_price(pack.price_env)
    if not price_id:
        raise ValueError("Il prezzo Stripe del pacchetto AI selezionato non e configurato.")

    metadata = {
        "billing_account_id": str(account.id),
        "workspace_id": str(workspace.id),
        "session_type": CheckoutSessionType.AI_TOKENS,
        "token_pack_code": pack.code,
        "token_count": str(pack.token_count),
    }
    stripe = get_stripe_client()
    checkout_session = stripe.checkout.Session.create(
        mode=CheckoutMode.PAYMENT,
        customer=ensure_stripe_customer(account),
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=build_checkout_success_url(
            workspace_id=workspace.id,
            session_type=CheckoutSessionType.AI_TOKENS,
        ),
        cancel_url=build_checkout_cancel_url(
            workspace_id=workspace.id,
            session_type=CheckoutSessionType.AI_TOKENS,
        ),
        metadata=metadata,
    )
    increment_counter("billing.checkout.created", session_type=CheckoutSessionType.AI_TOKENS)
    return create_checkout_session_record(
        account=account,
        workspace=workspace,
        created_by=profile,
        stripe_session=checkout_session,
        session_type=CheckoutSessionType.AI_TOKENS,
        payload={"token_pack_code": pack.code, "token_count": pack.token_count},
    )


def create_workspace_billing_checkout(
    user,
    *,
    claims: dict,
    workspace_id: int,
    session_type: str,
    plan_code: str | None = None,
    billing_interval: str = BillingInterval.MONTH,
    workspace_quantity: int = 0,
    seat_quantity: int = 0,
    storage_block_quantity: int = 0,
    token_pack_code: str | None = None,
) -> dict[str, Any]:
    from edilcloud.modules.workspaces.services import get_manageable_profile

    profile = get_manageable_profile(user, workspace_id)
    if session_type == CheckoutSessionType.AI_TOKENS:
        return create_ai_token_checkout_for_workspace(
            profile=profile,
            workspace=profile.workspace,
            token_pack_code=token_pack_code or "",
        )
    return create_subscription_checkout_for_workspace(
        profile=profile,
        workspace=profile.workspace,
        plan_code=plan_code or "fondazioni",
        billing_interval=billing_interval,
        workspace_quantity=workspace_quantity,
        seat_quantity=seat_quantity,
        storage_block_quantity=storage_block_quantity,
    )


def create_workspace_billing_portal(user, *, claims: dict, workspace_id: int) -> dict[str, Any]:
    from edilcloud.modules.workspaces.services import get_manageable_profile

    profile = get_manageable_profile(user, workspace_id)
    account = get_workspace_billing_account(profile.workspace)
    customer_id = ensure_stripe_customer(account)
    stripe = get_stripe_client()
    portal_session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{getattr(settings, 'PAYMENTS_SITE_URL', getattr(settings, 'APP_FRONTEND_URL', '')).rstrip('/')}/?workspace_id={profile.workspace_id}",
    )
    increment_counter("billing.portal.created")
    return {"url": stripe_value(portal_session, "url", "")}


def get_workspace_checkout_status(user, *, claims: dict, workspace_id: int, session_id: str) -> dict[str, Any]:
    from edilcloud.modules.workspaces.services import get_manageable_profile

    profile = get_manageable_profile(user, workspace_id)
    session = (
        BillingCheckoutSession.objects.filter(
            stripe_session_id=session_id,
            workspace=profile.workspace,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if session is None:
        raise ValueError("Sessione checkout non trovata.")
    return {
        "session_id": session.stripe_session_id,
        "status": session.status,
        "session_type": session.session_type,
        "workspace_id": session.workspace_id,
        "checkout_url": session.checkout_url or None,
    }


def sync_invoice_record(account: BillingAccount, invoice_obj: Any) -> BillingInvoice:
    invoice_id = str(stripe_value(invoice_obj, "id", "") or "").strip()
    if not invoice_id:
        raise ValueError("Invoice Stripe non valida.")

    invoice, _created = BillingInvoice.objects.get_or_create(
        billing_account=account,
        stripe_invoice_id=invoice_id,
    )
    invoice.invoice_number = str(stripe_value(invoice_obj, "number", "") or "")
    invoice.status = str(stripe_value(invoice_obj, "status", "") or "")
    invoice.currency = str(stripe_value(invoice_obj, "currency", account.currency) or account.currency)
    invoice.subtotal_amount = int(stripe_value(invoice_obj, "subtotal", 0) or 0)
    invoice.total_amount = int(stripe_value(invoice_obj, "total", 0) or 0)
    invoice.hosted_invoice_url = str(stripe_value(invoice_obj, "hosted_invoice_url", "") or "")
    invoice.invoice_pdf_url = str(stripe_value(invoice_obj, "invoice_pdf", "") or "")
    status_transitions = stripe_value(invoice_obj, "status_transitions", {}) or {}
    invoice.paid_at = to_datetime(stripe_value(status_transitions, "paid_at"))
    invoice.metadata = dict(stripe_value(invoice_obj, "metadata", {}) or {})
    invoice.save()
    return invoice


def sync_account_from_subscription(account: BillingAccount, subscription_obj: Any) -> BillingAccount:
    status = str(stripe_value(subscription_obj, "status", BillingStatus.ACTIVE) or BillingStatus.ACTIVE)
    metadata = dict(stripe_value(subscription_obj, "metadata", {}) or {})
    items = stripe_value(stripe_value(subscription_obj, "items", {}), "data", []) or []
    plan_code = metadata.get("plan_code") or account.plan_code or "trial"
    workspace_quantity = int(metadata.get("workspace_quantity") or 0)
    seat_quantity = int(metadata.get("seat_quantity") or 0)
    storage_quantity = int(metadata.get("storage_block_quantity") or 0)
    interval = metadata.get("billing_interval") or account.billing_interval or BillingInterval.MONTH
    subscription_item_ids: dict[str, str] = {}

    for item in items:
        price = stripe_value(item, "price", {}) or {}
        price_id = stripe_value(price, "id", "")
        item_id = str(stripe_value(item, "id", "") or "")
        quantity = int(stripe_value(item, "quantity", 1) or 1)
        maybe_plan_code = find_plan_code_by_price_id(price_id)
        maybe_addon_code = find_addon_code_by_price_id(price_id)
        if maybe_plan_code:
            plan_code = maybe_plan_code
            recurring = stripe_value(price, "recurring", {}) or {}
            interval = str(stripe_value(recurring, "interval", interval) or interval)
            subscription_item_ids[f"plan:{plan_code}"] = item_id
            continue
        if maybe_addon_code == "workspace":
            workspace_quantity = quantity
            subscription_item_ids["addon:workspace"] = item_id
        elif maybe_addon_code == "seat":
            seat_quantity = quantity
            subscription_item_ids["addon:seat"] = item_id
        elif maybe_addon_code == "storage_100gb":
            storage_quantity = quantity
            subscription_item_ids["addon:storage_100gb"] = item_id

    plan = get_plan_spec(plan_code)
    account.status = status
    account.plan_code = plan.code
    account.billing_interval = BillingInterval.YEAR if interval == BillingInterval.YEAR else BillingInterval.MONTH
    account.currency = str(stripe_value(subscription_obj, "currency", account.currency) or account.currency)
    account.stripe_subscription_id = str(stripe_value(subscription_obj, "id", "") or "")
    account.stripe_subscription_item_ids = subscription_item_ids
    account.workspace_limit_base = plan.included_workspaces
    account.workspace_limit_addon = max(workspace_quantity, 0)
    account.seat_limit_base = plan.included_seats
    account.seat_limit_addon = max(seat_quantity, 0)
    account.storage_quota_bytes_base = plan.included_storage_bytes
    account.storage_quota_bytes_addon = max(storage_quantity, 0) * DEFAULT_STORAGE_BLOCK_BYTES
    account.monthly_ai_tokens_base = plan.included_ai_tokens
    account.current_period_start = to_datetime(stripe_value(subscription_obj, "current_period_start"))
    account.current_period_end = to_datetime(stripe_value(subscription_obj, "current_period_end"))
    account.cancel_at_period_end = bool(stripe_value(subscription_obj, "cancel_at_period_end", False))
    account.app_access_enabled = subscription_allows_access(status)
    account.metadata = {
        **dict(account.metadata or {}),
        "subscription_metadata": metadata,
    }
    account.save()
    return account


def credit_token_pack_purchase(
    account: BillingAccount,
    *,
    workspace: Workspace | None,
    token_count: int,
    checkout_session_id: str,
) -> None:
    existing = BillingTokenLedger.objects.filter(
        billing_account=account,
        reference_kind="checkout_session",
        reference_id=checkout_session_id,
        entry_type=TokenLedgerEntryType.PURCHASE,
    ).exists()
    if existing:
        return
    account.ai_token_balance_topup = int(account.ai_token_balance_topup) + int(token_count)
    account.save(update_fields=["ai_token_balance_topup", "updated_at"])
    BillingTokenLedger.objects.create(
        billing_account=account,
        workspace=workspace,
        entry_type=TokenLedgerEntryType.PURCHASE,
        tokens_delta=int(token_count),
        balance_after=int(account.ai_token_balance_topup),
        reference_kind="checkout_session",
        reference_id=checkout_session_id,
        description="Acquisto pacchetto token AI",
        metadata={"token_count": int(token_count)},
    )


def get_account_by_customer_id(customer_id: str | None) -> BillingAccount | None:
    normalized = (customer_id or "").strip()
    if not normalized:
        return None
    return BillingAccount.objects.filter(stripe_customer_id=normalized).first()


def get_account_by_checkout_metadata(metadata: dict[str, Any]) -> BillingAccount | None:
    account_id = metadata.get("billing_account_id")
    if str(account_id).isdigit():
        return BillingAccount.objects.filter(id=int(account_id)).first()
    return None


def mark_checkout_session_status(session_id: str, *, status: str, completed_at: datetime | None = None) -> None:
    session = BillingCheckoutSession.objects.filter(stripe_session_id=session_id).first()
    if session is None:
        return
    session.status = normalize_checkout_status(status)
    if completed_at is not None:
        session.completed_at = completed_at
    session.save(update_fields=["status", "completed_at", "updated_at"])


def process_checkout_session_completed(session_obj: Any) -> None:
    metadata = dict(stripe_value(session_obj, "metadata", {}) or {})
    session_id = str(stripe_value(session_obj, "id", "") or "")
    account = get_account_by_checkout_metadata(metadata) or get_account_by_customer_id(
        stripe_value(session_obj, "customer", "")
    )
    if account is None:
        return
    mark_checkout_session_status(session_id, status=CheckoutSessionStatus.COMPLETED, completed_at=timezone.now())
    session_type = metadata.get("session_type") or stripe_value(session_obj, "mode", "")
    if session_type == CheckoutSessionType.AI_TOKENS:
        token_count = int(metadata.get("token_count") or 0)
        workspace = (
            Workspace.objects.filter(id=int(metadata.get("workspace_id"))).first()
            if str(metadata.get("workspace_id")).isdigit()
            else None
        )
        credit_token_pack_purchase(
            account,
            workspace=workspace,
            token_count=token_count,
            checkout_session_id=session_id,
        )
        return
    subscription_id = str(stripe_value(session_obj, "subscription", "") or "")
    if subscription_id:
        stripe = get_stripe_client()
        subscription = stripe.Subscription.retrieve(subscription_id)
        sync_account_from_subscription(account, subscription)


def process_subscription_event(subscription_obj: Any) -> None:
    customer_id = str(stripe_value(subscription_obj, "customer", "") or "")
    metadata = dict(stripe_value(subscription_obj, "metadata", {}) or {})
    account = get_account_by_checkout_metadata(metadata) or get_account_by_customer_id(customer_id)
    if account is None:
        return
    sync_account_from_subscription(account, subscription_obj)


def process_subscription_deleted(subscription_obj: Any) -> None:
    customer_id = str(stripe_value(subscription_obj, "customer", "") or "")
    account = get_account_by_customer_id(customer_id)
    if account is None:
        return
    trial_plan = get_plan_spec("trial")
    account.status = BillingStatus.CANCELED
    account.plan_code = trial_plan.code
    account.billing_interval = BillingInterval.MONTH
    account.stripe_subscription_id = ""
    account.stripe_subscription_item_ids = {}
    account.workspace_limit_base = trial_plan.included_workspaces
    account.workspace_limit_addon = 0
    account.seat_limit_base = trial_plan.included_seats
    account.seat_limit_addon = 0
    account.storage_quota_bytes_base = trial_plan.included_storage_bytes
    account.storage_quota_bytes_addon = 0
    account.monthly_ai_tokens_base = trial_plan.included_ai_tokens
    account.current_period_start = None
    account.current_period_end = None
    account.cancel_at_period_end = False
    account.app_access_enabled = True
    account.save()


def process_invoice_event(invoice_obj: Any) -> None:
    account = get_account_by_customer_id(stripe_value(invoice_obj, "customer", ""))
    if account is None:
        return
    sync_invoice_record(account, invoice_obj)


@transaction.atomic
def process_stripe_webhook(*, payload: bytes, signature: str) -> dict[str, Any]:
    stripe = get_stripe_client()
    event = stripe.Webhook.construct_event(
        payload=payload,
        sig_header=signature,
        secret=getattr(settings, "STRIPE_WEBHOOK_SECRET", ""),
    )
    event_id = str(stripe_value(event, "id", "") or "")
    event_type = str(stripe_value(event, "type", "") or "")
    data_object = stripe_value(stripe_value(event, "data", {}), "object", {}) or {}

    event_record, created = BillingWebhookEvent.objects.get_or_create(
        stripe_event_id=event_id,
        defaults={"event_type": event_type},
    )
    if not created and event_record.processed_at is not None:
        return {"status": "ok", "detail": "Webhook gia processato."}

    if event_type == "checkout.session.completed":
        process_checkout_session_completed(data_object)
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        process_subscription_event(data_object)
    elif event_type == "customer.subscription.deleted":
        process_subscription_deleted(data_object)
    elif event_type in {"invoice.paid", "invoice.payment_failed", "invoice.finalized"}:
        process_invoice_event(data_object)

    event_record.event_type = event_type
    if isinstance(event, dict):
        event_record.payload = event
    event_record.processed_at = timezone.now()
    event_record.save(update_fields=["event_type", "payload", "processed_at", "updated_at"])
    increment_counter("billing.webhook.processed", event_type=event_type)
    return {"status": "ok", "detail": "Webhook processato."}
