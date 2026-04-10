import json
from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from edilcloud.modules.billing.models import (
    BillingCheckoutSession,
    BillingStatus,
    BillingTokenLedger,
)
from edilcloud.modules.billing.services import ensure_workspace_attached_to_owner_account
from edilcloud.modules.projects.models import Project, ProjectMember, ProjectMemberStatus
from edilcloud.modules.workspaces.models import Workspace, WorkspaceRole


def create_workspace_profile(*, email: str, password: str, workspace_name: str = "Workspace Billing"):
    user = get_user_model().objects.create_user(
        email=email,
        password=password,
        username=email.split("@")[0],
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    workspace = Workspace.objects.create(name=workspace_name, email=email)
    profile = workspace.profiles.create(
        user=user,
        email=email,
        role=WorkspaceRole.OWNER,
        first_name="Mario",
        last_name="Rossi",
        language="it",
    )
    ensure_workspace_attached_to_owner_account(workspace, owner_user=user)
    return user, workspace, profile


def auth_headers(client: Client, *, email: str, password: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        data=json.dumps(
            {
                "username_or_email": email,
                "password": password,
            }
        ),
        content_type="application/json",
    )
    assert response.status_code == 200
    return {"HTTP_AUTHORIZATION": f"JWT {response.json()['token']}"}


def create_project_for_workspace(profile):
    project = Project.objects.create(
        workspace=profile.workspace,
        created_by=profile,
        name="Progetto Billing",
        address="Via Milano 10",
        date_start=date(2026, 1, 1),
        date_end=date(2026, 12, 31),
    )
    ProjectMember.objects.create(
        project=project,
        profile=profile,
        role=WorkspaceRole.OWNER,
        status=ProjectMemberStatus.ACTIVE,
    )
    return project


class FakeStripe:
    def __init__(self, *, event=None, subscription=None):
        self._event = event
        self._subscription = subscription or {}
        self.Customer = SimpleNamespace(create=self._create_customer)
        self.checkout = SimpleNamespace(Session=SimpleNamespace(create=self._create_checkout_session))
        self.billing_portal = SimpleNamespace(
            Session=SimpleNamespace(create=self._create_portal_session)
        )
        self.Subscription = SimpleNamespace(retrieve=self._retrieve_subscription)
        self.Webhook = SimpleNamespace(construct_event=self._construct_event)

    def _create_customer(self, **kwargs):
        del kwargs
        return {"id": "cus_test_123"}

    def _create_checkout_session(self, **kwargs):
        session_type = (kwargs.get("metadata") or {}).get("session_type", "subscription")
        mode = kwargs.get("mode", session_type)
        return {
            "id": f"cs_test_{session_type}",
            "mode": mode,
            "status": "open",
            "url": f"https://stripe.test/{session_type}",
        }

    def _create_portal_session(self, **kwargs):
        del kwargs
        return {"url": "https://stripe.test/portal"}

    def _retrieve_subscription(self, subscription_id: str):
        if self._subscription:
            return self._subscription
        return {
            "id": subscription_id,
            "status": "active",
            "currency": "eur",
            "current_period_start": 1_700_000_000,
            "current_period_end": 1_700_100_000,
            "cancel_at_period_end": False,
            "metadata": {
                "plan_code": "fondazioni",
                "workspace_quantity": "0",
                "seat_quantity": "0",
                "storage_block_quantity": "0",
                "billing_interval": "month",
            },
            "items": {"data": []},
        }

    def _construct_event(self, **kwargs):
        del kwargs
        return self._event


@pytest.mark.django_db
def test_billing_catalog_endpoint_is_public():
    client = Client()

    response = client.get("/api/v1/billing/catalog")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_plan_code"] == "fondazioni"
    assert len(payload["plans"]) >= 3
    assert len(payload["token_packs"]) >= 3


@pytest.mark.django_db
def test_billing_current_summary_returns_trial_metrics():
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.summary@example.com",
        password="devpass123",
    )
    headers = auth_headers(client, email="billing.summary@example.com", password="devpass123")

    response = client.get(f"/api/v1/billing/current?workspace_id={workspace.id}", **headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["plan_code"] == "trial"
    assert payload["workspaces"]["limit"] == 1
    assert payload["seats"]["used"] == 1
    assert payload["workspace_usage"]["workspace_id"] == workspace.id


@pytest.mark.django_db
def test_workspace_creation_is_blocked_when_workspace_quota_is_full():
    client = Client()
    user, _workspace, _profile = create_workspace_profile(
        email="billing.workspace-limit@example.com",
        password="devpass123",
    )
    headers = auth_headers(
        client,
        email="billing.workspace-limit@example.com",
        password="devpass123",
    )

    response = client.post(
        "/api/v1/workspaces",
        data=json.dumps(
            {
                "company_name": "Secondo Workspace",
                "company_email": user.email,
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    assert "workspace" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_workspace_invite_is_blocked_when_seat_quota_is_full():
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.seat-limit@example.com",
        password="devpass123",
    )
    account = workspace.billing_assignment.billing_account
    account.seat_limit_base = 1
    account.seat_limit_addon = 0
    account.save(update_fields=["seat_limit_base", "seat_limit_addon", "updated_at"])
    headers = auth_headers(client, email="billing.seat-limit@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/workspaces/{workspace.id}/invites",
        data=json.dumps(
            {
                "email": "new.member@example.com",
                "role": "w",
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 400
    assert "utenti" in response.json()["detail"].lower() or "numero massimo" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_project_document_upload_respects_storage_quota():
    client = Client()
    _user, _workspace, profile = create_workspace_profile(
        email="billing.storage@example.com",
        password="devpass123",
    )
    account = profile.workspace.billing_assignment.billing_account
    account.storage_quota_bytes_base = 1
    account.storage_quota_bytes_addon = 0
    account.save(update_fields=["storage_quota_bytes_base", "storage_quota_bytes_addon", "updated_at"])
    project = create_project_for_workspace(profile)
    headers = auth_headers(client, email="billing.storage@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/projects/{project.id}/documents",
        data={
            "title": "Documento pesante",
            "document": SimpleUploadedFile("test.pdf", b"0123456789", content_type="application/pdf"),
        },
        **headers,
    )

    assert response.status_code == 400
    assert "spazio" in response.json()["detail"].lower()


@pytest.mark.django_db
def test_billing_checkout_endpoint_creates_local_checkout_session(monkeypatch):
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.checkout@example.com",
        password="devpass123",
    )
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_stripe_client",
        lambda: FakeStripe(),
    )
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_env_price",
        lambda name: {
            "STRIPE_PRICE_PLAN_FONDAZIONI_MONTHLY": "price_fondazioni_month",
            "STRIPE_PRICE_ADDON_WORKSPACE_MONTHLY": "price_workspace_month",
            "STRIPE_PRICE_ADDON_SEAT_MONTHLY": "price_seat_month",
            "STRIPE_PRICE_ADDON_STORAGE_100GB_MONTHLY": "price_storage_month",
        }.get(name, ""),
    )
    headers = auth_headers(client, email="billing.checkout@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/billing/workspaces/{workspace.id}/checkout",
        data=json.dumps(
            {
                "session_type": "subscription",
                "plan_code": "fondazioni",
                "billing_interval": "month",
                "workspace_quantity": 1,
                "seat_quantity": 2,
                "storage_block_quantity": 1,
            }
        ),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "cs_test_subscription"
    assert payload["checkout_url"] == "https://stripe.test/subscription"
    assert BillingCheckoutSession.objects.filter(stripe_session_id="cs_test_subscription").exists()


@pytest.mark.django_db
def test_billing_portal_endpoint_returns_portal_url(monkeypatch):
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.portal@example.com",
        password="devpass123",
    )
    workspace.billing_assignment.billing_account.stripe_customer_id = "cus_ready"
    workspace.billing_assignment.billing_account.save(update_fields=["stripe_customer_id", "updated_at"])
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_stripe_client",
        lambda: FakeStripe(),
    )
    headers = auth_headers(client, email="billing.portal@example.com", password="devpass123")

    response = client.post(
        f"/api/v1/billing/workspaces/{workspace.id}/portal",
        data=json.dumps({}),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200
    assert response.json()["url"] == "https://stripe.test/portal"


@pytest.mark.django_db
def test_stripe_webhook_credits_ai_token_pack(monkeypatch):
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.tokens@example.com",
        password="devpass123",
    )
    account = workspace.billing_assignment.billing_account
    account.stripe_customer_id = "cus_test_123"
    account.save(update_fields=["stripe_customer_id", "updated_at"])
    event = {
        "id": "evt_ai_pack",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_ai_pack",
                "customer": "cus_test_123",
                "metadata": {
                    "billing_account_id": str(account.id),
                    "workspace_id": str(workspace.id),
                    "session_type": "ai_tokens",
                    "token_count": "5000000",
                },
            }
        },
    }
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_stripe_client",
        lambda: FakeStripe(event=event),
    )

    response = client.post(
        "/api/v1/billing/stripe/webhook",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=test",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.ai_token_balance_topup == 5_000_000
    assert BillingTokenLedger.objects.filter(reference_id="cs_ai_pack").exists()


@pytest.mark.django_db
def test_stripe_webhook_syncs_subscription_plan(monkeypatch):
    client = Client()
    _user, workspace, _profile = create_workspace_profile(
        email="billing.subscription@example.com",
        password="devpass123",
    )
    account = workspace.billing_assignment.billing_account
    account.stripe_customer_id = "cus_test_123"
    account.save(update_fields=["stripe_customer_id", "updated_at"])
    subscription = {
        "id": "sub_test_123",
        "status": "active",
        "currency": "eur",
        "current_period_start": 1_700_000_000,
        "current_period_end": 1_700_100_000,
        "cancel_at_period_end": False,
        "metadata": {
            "billing_account_id": str(account.id),
            "plan_code": "struttura",
            "workspace_quantity": "2",
            "seat_quantity": "4",
            "storage_block_quantity": "3",
            "billing_interval": "month",
        },
        "items": {
            "data": [
                {
                    "id": "si_plan",
                    "quantity": 1,
                    "price": {
                        "id": "price_struttura_month",
                        "recurring": {"interval": "month"},
                    },
                }
            ]
        },
    }
    event = {
        "id": "evt_subscription",
        "type": "customer.subscription.updated",
        "data": {"object": subscription},
    }

    def fake_price_env(name: str) -> str:
        mapping = {
            "STRIPE_PRICE_PLAN_STRUTTURA_MONTHLY": "price_struttura_month",
        }
        return mapping.get(name, "")

    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_stripe_client",
        lambda: FakeStripe(event=event, subscription=subscription),
    )
    monkeypatch.setattr(
        "edilcloud.modules.billing.services.get_env_price",
        fake_price_env,
    )

    response = client.post(
        "/api/v1/billing/stripe/webhook",
        data=b"{}",
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE="t=1,v1=test",
    )

    assert response.status_code == 200
    account.refresh_from_db()
    assert account.plan_code == "struttura"
    assert account.status == BillingStatus.ACTIVE
    assert account.workspace_limit_addon == 2
    assert account.seat_limit_addon == 4
    assert account.storage_quota_bytes_addon > 0
