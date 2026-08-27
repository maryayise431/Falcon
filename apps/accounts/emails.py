"""Account-related emails: registration OTP, password reset OTP, confirmation."""

from apps.core.email import send_templated_email

OTP_EXPIRY_MINUTES = 10


def send_registration_otp(user, otp):
    """Email the email-verification code for a new or unverified account."""
    return send_templated_email(
        subject="Your Falcon Account Verification Code",
        template_base="accounts/emails/registration_otp",
        context={"user": user, "otp": otp, "expiry_minutes": OTP_EXPIRY_MINUTES},
        to_email=user.email,
    )


def send_password_reset_otp(user, otp):
    """Email the one-time code used to authorise a password reset."""
    return send_templated_email(
        subject="Reset Your Falcon Password",
        template_base="accounts/emails/password_reset_otp",
        context={"user": user, "otp": otp, "expiry_minutes": OTP_EXPIRY_MINUTES},
        to_email=user.email,
    )


def send_password_reset_confirmation(user):
    """Notify the user that their password was changed."""
    return send_templated_email(
        subject="Your Falcon Password Was Changed",
        template_base="accounts/emails/password_reset_confirm",
        context={"user": user},
        to_email=user.email,
    )
