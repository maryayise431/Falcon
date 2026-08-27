import re

import requests

from django.conf import settings


class PaystackError(Exception):
    pass


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
# TLDs that are syntactically valid but rejected by Paystack's email check.
_RESERVED_TLDS = {"test", "localhost", "local", "invalid", "example"}


def deliverable_email(email, fallback_local="customer"):
    """Paystack rejects addresses without a routable TLD (e.g. demo
    ``user@falcon.test``). Swap the domain for a valid placeholder so the
    payment can proceed; the canonical address stays in our own records."""
    email = (email or "").strip()
    if _EMAIL_RE.match(email):
        tld = email.rsplit(".", 1)[-1].lower()
        if tld not in _RESERVED_TLDS:
            return email
    local = email.split("@")[0] or fallback_local
    return f"{local}@payments.example.com"


def paystack_enabled():
    return bool(settings.PAYSTACK_SECRET_KEY)


def _headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def _get(path, params=None):
    try:
        response = requests.get(
            f"{settings.PAYSTACK_BASE_URL}{path}",
            params=params or {},
            headers=_headers(),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise PaystackError(str(exc)) from exc
    data = response.json()
    if not data.get("status"):
        raise PaystackError(data.get("message", "Paystack request failed"))
    return data.get("data")


def _post(path, payload):
    try:
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}{path}",
            json=payload,
            headers=_headers(),
            timeout=25,
        )
    except requests.RequestException as exc:
        raise PaystackError(str(exc)) from exc
    data = response.json()
    if not data.get("status"):
        raise PaystackError(data.get("message", "Paystack request failed"))
    return data.get("data")


def initialize_transaction(email, amount_naira, reference, callback_url, metadata=None):
    if not paystack_enabled():
        return {
            "authorization_url": None,
            "reference": reference,
            "simulated": True,
        }
    data = _post(
        "/transaction/initialize",
        {
            "email": deliverable_email(email),
            "amount": int(amount_naira * 100),
            "reference": reference,
            "callback_url": callback_url,
            "metadata": metadata or {},
        },
    )
    return {
        "authorization_url": data["authorization_url"],
        "reference": reference,
        "simulated": False,
    }


def verify_transaction(reference):
    if not paystack_enabled():
        return {"success": True, "amount_kobo": None, "simulated": True}
    data = _get(f"/transaction/verify/{reference}")
    return {
        "success": data.get("status") == "success",
        "amount_kobo": data.get("amount"),
        "simulated": False,
    }


def list_banks():
    if not paystack_enabled():
        return [
            {"name": "Access Bank", "code": "044"},
            {"name": "Guaranty Trust Bank", "code": "058"},
            {"name": "Kuda Microfinance Bank", "code": "50211"},
            {"name": "Moniepoint MFB", "code": "50515"},
            {"name": "First Bank of Nigeria", "code": "011"},
            {"name": "United Bank for Africa", "code": "033"},
            {"name": "Zenith Bank", "code": "057"},
            {"name": "Opay Digital Services", "code": "999992"},
            {"name": "Palmpay", "code": "999991"},
            {"name": "Wema Bank", "code": "035"},
        ]
    banks = _get("/bank", params={"currency": "NGN", "type": "nuban"})
    return [{"name": b["name"], "code": b["code"]} for b in banks]


def resolve_bank_account(account_number, bank_code):
    if not paystack_enabled():
        return {
            "verified": True,
            "account_name": "SIMULATED ACCOUNT NAME (dev mode)",
            "simulated": True,
        }
    try:
        data = _get(
            "/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
        )
    except PaystackError as exc:
        err = str(exc).lower()
        if "test mode" in err or "limit" in err or "daily" in err:
            return {
                "verified": True,
                "account_name": f"TEST ACCOUNT ({account_number})",
                "simulated": True,
                "warning": str(exc),
            }
        return {"verified": False, "account_name": "", "simulated": False, "error": str(exc)}
    return {
        "verified": True,
        "account_name": data.get("account_name", ""),
        "simulated": False,
    }


def create_transfer_recipient(name, account_number, bank_code):
    if not paystack_enabled():
        return f"RCP_sim_{secrets_token()}"
    data = _post(
        "/transferrecipient",
        {
            "type": "nuban",
            "name": name,
            "account_number": account_number,
            "bank_code": bank_code,
            "currency": "NGN",
        },
    )
    return data["recipient_code"]


def initiate_transfer(amount_naira, recipient_code, reason, reference):
    if not paystack_enabled():
        return f"TRF_sim_{secrets_token()}"
    data = _post(
        "/transfer",
        {
            "source": "balance",
            "amount": int(amount_naira * 100),
            "recipient": recipient_code,
            "reason": reason,
            "reference": reference,
            "currency": "NGN",
        },
    )
    return data.get("transfer_code", "")


def secrets_token(length=10):
    import secrets
    import string

    return "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(length))
