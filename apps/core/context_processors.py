from django.conf import settings


ROLE_HOME = {
    "customer": "/marketplace/",
    "vendor": "/vendor/dashboard/",
    "delivery_agent": "/agent/dashboard/",
    "manager": "/manager/dashboard/",
    "sub_manager": "/sub-manager/dashboard/",
}


def falcon_context(request):
    context = {
        "GOOGLE_MAPS_API_KEY": settings.GOOGLE_MAPS_API_KEY,
        "WITHDRAWAL_FEE": settings.WITHDRAWAL_FEE,
        "PAYSTACK_ENABLED": bool(settings.PAYSTACK_SECRET_KEY),
        "role_home": ROLE_HOME.get(getattr(request.user, "role", ""), "/"),
    }
    user = request.user
    counts = {}
    if user.is_authenticated:
        role = getattr(user, "role", "")
        try:
            counts = _role_counts(user, role)
        except Exception:
            counts = {}
    context["pending_counts"] = counts
    cart = request.session.get("falcon_cart", {})
    context["cart_count"] = sum(int(v) for v in cart.values() if int(v) > 0)
    return context


def _role_counts(user, role):
    from apps.delivery.models import DeliveryAssignment
    from apps.parcel.models import ParcelRequest
    from apps.vendor.models import (
        VendorFulfillmentOrder,
        VendorWithdrawalRequest,
        VendorWallet,
    )

    if role in ("manager", "sub_manager"):
        return {
            "pending_orders": VendorFulfillmentOrder.objects.filter(
                status__in=["pending", "processing"]
            ).count(),
            "pending_withdrawals": VendorWithdrawalRequest.objects.filter(
                status="pending"
            ).count(),
            "parcels_to_quote": ParcelRequest.objects.filter(status="pending").count(),
        }
    if role == "vendor":
        wallet = VendorWallet.objects.filter(vendor=user).first()
        active_orders = VendorFulfillmentOrder.objects.filter(
            vendor=user,
            status__in=[
                "pending",
                "processing",
                "awaiting_assignment",
                "assigned",
                "approved",
                "out_for_delivery",
            ],
        ).count()
        return {
            "wallet_balance": wallet.balance if wallet else 0,
            "active_orders": active_orders,
            "vendor_parcels": ParcelRequest.objects.filter(
                requested_by=user,
                status__in=["pending", "quoted", "processing", "in_transit"],
            ).count(),
        }
    if role == "delivery_agent":
        profile = getattr(user, "deliveryagentprofile", None)
        qs = DeliveryAssignment.objects.none()
        if profile:
            qs = DeliveryAssignment.objects.filter(
                agent=profile, status__in=["assigned", "out_for_delivery"]
            )
        return {"active_deliveries": qs.count()}
    return {}
