import secrets
import string
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.utils import timezone

FINAL_STATUSES = {"delivered", "failed"}


def generate_reference(prefix="FD", length=8):
    alphabet = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(length))
    return f"{prefix}-{body}"


def generate_otp():
    return f"{secrets.randbelow(1000000):06d}"


def otp_expiry_time():
    return timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES)


def calculate_settlement(cod_amount, delivery_fee=Decimal("0.00")):
    try:
        cod_amount = Decimal(cod_amount or 0)
    except InvalidOperation:
        cod_amount = Decimal("0")
    try:
        delivery_fee = Decimal(delivery_fee or 0)
    except InvalidOperation:
        delivery_fee = Decimal("0")
    return {
        "cod_collected": cod_amount,
        "delivery_fee": delivery_fee,
        "wallet_credit": cod_amount,
        "fee_debit": delivery_fee,
    }


def is_final_status(status):
    return status in FINAL_STATUSES


def naira(value):
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError):
        return "\u20a60"
    return f"\u20a6{value:,.2f}"
