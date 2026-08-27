"""Outgoing email delivery for Falcon.

Every message is rendered from a template pair (``<base>.txt`` +
``<base>.html``) and sent as a multipart/alternative email through the
backend configured in settings.  Delivery problems are logged and
reported to the caller via the boolean return value; they never raise
into auth flows.
"""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger("falcon.email")

SMTP_TIMEOUT_SECONDS = 15


def send_templated_email(subject, template_base, context, to_email):
    """Render ``template_base`` (.txt + .html) and send to ``to_email``.

    Returns True when the backend accepted the message, False otherwise.
    """
    context.setdefault("site_name", "Falcon Delivery Service")
    try:
        text_body = render_to_string(f"{template_base}.txt", context)
        html_body = render_to_string(f"{template_base}.html", context)
    except Exception:
        logger.exception("Email rendering failed for %s (%s)", to_email, subject)
        return False

    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    message.attach_alternative(html_body, "text/html")

    try:
        sent = message.send()
    except Exception:
        logger.exception("Email delivery failed for %s (%s)", to_email, subject)
        return False

    if not sent:
        logger.error("Email backend reported 0 messages sent to %s (%s)", to_email, subject)
        return False
    return True
