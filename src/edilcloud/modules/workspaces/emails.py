from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from edilcloud.platform.email import send_email_message


def build_backend_url(path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{settings.BACKEND_PUBLIC_URL}{normalized_path}"


def send_templated_email(
    *,
    template_prefix: str,
    to_email: str,
    context: dict,
    from_email: str | None = None,
) -> None:
    subject = render_to_string(f"{template_prefix}_subject.txt", context).strip()
    text_body = render_to_string(f"{template_prefix}.txt", context)
    html_body = render_to_string(f"{template_prefix}.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or settings.REGISTRATION_FROM_EMAIL or settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    message.attach_alternative(html_body, "text/html")
    send_email_message(message)


def send_workspace_invite_email(
    *,
    to_email: str,
    workspace_name: str,
    inviter_name: str,
    role_label: str,
    invite_code: str,
    invite_url: str,
    registration_url: str,
) -> None:
    send_templated_email(
        template_prefix="workspaces/emails/workspace_invite",
        to_email=to_email,
        context={
            "workspace_name": workspace_name,
            "inviter_name": inviter_name,
            "role_label": role_label,
            "invite_code": invite_code,
            "invite_url": invite_url,
            "registration_url": registration_url,
            "support_email": settings.SERVER_EMAIL or settings.DEFAULT_FROM_EMAIL,
        },
    )


def send_workspace_access_request_review_email(
    *,
    to_email: str,
    reviewer_name: str,
    workspace_name: str,
    requester_name: str,
    requester_email: str,
    requester_phone: str,
    position: str,
    message: str,
    approve_path: str,
    refuse_path: str,
) -> None:
    send_templated_email(
        template_prefix="workspaces/emails/access_request_review",
        to_email=to_email,
        context={
            "reviewer_name": reviewer_name,
            "workspace_name": workspace_name,
            "requester_name": requester_name,
            "requester_email": requester_email,
            "requester_phone": requester_phone,
            "position": position,
            "message": message,
            "approve_url": build_backend_url(approve_path),
            "refuse_url": build_backend_url(refuse_path),
            "support_email": settings.SERVER_EMAIL or settings.DEFAULT_FROM_EMAIL,
        },
    )


def send_workspace_access_approved_email(
    *,
    to_email: str,
    workspace_name: str,
    member_name: str,
) -> None:
    send_templated_email(
        template_prefix="workspaces/emails/access_request_approved",
        to_email=to_email,
        context={
            "workspace_name": workspace_name,
            "member_name": member_name,
            "login_url": f"{settings.APP_FRONTEND_URL}/auth",
            "support_email": settings.SERVER_EMAIL or settings.DEFAULT_FROM_EMAIL,
        },
    )
