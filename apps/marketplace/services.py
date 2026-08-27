from django.db import transaction as db_transaction
from django.utils import timezone

from .models import MarketplaceOrder, MarketplaceOrderItem, MarketplacePayment, MarketplaceProduct

CART_SESSION_KEY = "falcon_cart"


def get_cart(session):
    return session.get(CART_SESSION_KEY, {})


def save_cart(session, cart):
    cart = {str(k): int(v) for k, v in cart.items() if int(v) > 0}
    if cart:
        session[CART_SESSION_KEY] = cart
    else:
        session.pop(CART_SESSION_KEY, None)


def add_to_cart(session, product_id, quantity):
    cart = get_cart(session)
    key = str(product_id)
    current = int(cart.get(key, 0))
    cart[key] = min(current + quantity, 999)
    save_cart(session, cart)
    return cart


def set_cart_quantity(session, product_id, quantity):
    cart = get_cart(session)
    key = str(product_id)
    if quantity <= 0:
        cart.pop(key, None)
    else:
        cart[key] = min(quantity, 999)
    save_cart(session, cart)
    return cart


def clear_cart(session):
    session.pop(CART_SESSION_KEY, None)


def build_cart_context(session):
    cart = get_cart(session)
    entries = []
    total = 0
    stale_ids = []
    for key, qty in cart.items():
        product = MarketplaceProduct.objects.filter(id=key).first()
        if product is None or not product.is_published:
            stale_ids.append(key)
            continue
        available = product.stock
        qty = min(qty, max(available, 0)) if available else 0
        if qty == 0:
            stale_ids.append(key)
            continue
        subtotal = product.price * qty
        entries.append({"product": product, "quantity": qty, "subtotal": subtotal})
        total += subtotal
    for key in stale_ids:
        cart.pop(key, None)
    if stale_ids:
        save_cart(session, cart)
    return {"entries": entries, "total": total, "total_display": f"\u20a6{total:,.2f}"}


@db_transaction.atomic
def place_order(customer, cart_data, delivery_address="", receiver_phone="",
                lat=None, lng=None, delivery_method="door_delivery",
                pickup_warehouse=None):
    if not cart_data["entries"]:
        raise ValueError("Your cart is empty.")
    product_total = cart_data["total"]
    order = MarketplaceOrder.objects.create(
        customer=customer,
        total_amount=product_total,
        delivery_method=delivery_method,
        delivery_address=delivery_address,
        receiver_phone=receiver_phone,
        delivery_address_lat=lat,
        delivery_address_lng=lng,
        pickup_warehouse_id=pickup_warehouse,
    )
    for entry in cart_data["entries"]:
        MarketplaceOrderItem.objects.create(
            order=order,
            product=entry["product"],
            product_name=entry["product"].name,
            quantity=entry["quantity"],
            unit_price=entry["product"].price,
        )
    payment = MarketplacePayment.objects.create(order=order, amount=product_total)
    return order, payment


@db_transaction.atomic
def finalize_paid_order(order, paystack_reference="", simulated=False):
    payment = order.payment
    if payment.status == MarketplacePayment.STATUS_SUCCESS:
        return order
    payment.paystack_reference = paystack_reference or payment.paystack_reference
    payment.simulated = simulated
    payment.mark_paid()
    for item in order.items.select_related("product"):
        if item.product is not None:
            product = MarketplaceProduct.objects.select_for_update().get(id=item.product.id)
            product.stock = max(0, product.stock - item.quantity)
            product.save(update_fields=["stock"])
    order.status = MarketplaceOrder.STATUS_PROCESSING
    order.save(update_fields=["status", "updated_at"])
    return order


def fail_order_payment(order):
    payment = order.payment
    if payment.status == MarketplacePayment.STATUS_PENDING:
        payment.status = MarketplacePayment.STATUS_FAILED
        payment.save(update_fields=["status"])


def cancel_order(order):
    from apps.core.utils import is_final_status

    if is_final_status(order.status):
        raise ValueError("This order can no longer be changed.")
    if order.payment.status == MarketplacePayment.STATUS_SUCCESS:
        with db_transaction.atomic():
            for item in order.items.select_related("product"):
                if item.product is not None:
                    item.product.stock += item.quantity
                    item.product.save(update_fields=["stock"])
            order.payment.status = MarketplacePayment.STATUS_FAILED
            order.payment.save(update_fields=["status"])
    order.status = MarketplaceOrder.STATUS_CANCELLED
    order.updated_at = timezone.now()
    order.save(update_fields=["status", "updated_at"])
    return order
