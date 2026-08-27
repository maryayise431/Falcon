import re

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


@deconstructible
class NigerianPhoneValidator:
    regex = r"^(?:\+?234|0)[789][01]\d{8}$"
    message = "Enter a valid Nigerian phone number (e.g. 08012345678)."
    code = "invalid_phone"

    def __call__(self, value):
        cleaned = re.sub(r"[\s\-()]", "", str(value or ""))
        if not re.match(self.regex, cleaned):
            raise ValidationError(self.message, code=self.code)

    def __eq__(self, other):
        return isinstance(other, NigerianPhoneValidator)


@deconstructible
class NubanValidator:
    message = "Enter a valid 10-digit bank account number."
    code = "invalid_nuban"

    def __call__(self, value):
        if not re.fullmatch(r"\d{10}", str(value or "").strip()):
            raise ValidationError(self.message, code=self.code)

    def __eq__(self, other):
        return isinstance(other, NubanValidator)


def validate_positive_amount(value):
    from decimal import Decimal

    try:
        value = Decimal(value)
    except Exception:
        raise ValidationError("Enter a valid amount.", code="invalid_amount")
    if value <= 0:
        raise ValidationError(
            "Amount must be greater than zero.", code="invalid_amount"
        )
