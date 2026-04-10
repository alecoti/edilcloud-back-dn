from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

from edilcloud.platform.email import send_email_message


def send_project_invite_code_email(
    *,
    to_email: str,
    project_name: str,
    inviter_name: str,
    invite_code: str,
) -> None:
    context = {
        "project_name": project_name,
        "inviter_name": inviter_name,
        "invite_code": invite_code,
        "support_email": settings.DEFAULT_FROM_EMAIL,
    }
    subject = render_to_string(
        "projects/emails/project_invite_subject.txt",
        context,
    ).strip()
    text_body = render_to_string("projects/emails/project_invite.txt", context)
    html_body = render_to_string("projects/emails/project_invite.html", context)

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.REGISTRATION_FROM_EMAIL or settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    message.attach_alternative(html_body, "text/html")
    send_email_message(message)
