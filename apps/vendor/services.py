from decimal import Decimal

from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone

from apps.core.paystack import (
    PaystackError,
    create_transfer_recipient,
    initiate_transfer,
)
from apps.core.utils import calculate_settlement, generate_reference

from .models import (
    VendorFulfillmentOrder,
    VendorProduct,
    VendorWallet,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)


def get_or_create_wallet(vendor):
    wallet, _ = VendorWallet.objects.get_or_create(vendor=vendor)
    return wallet


def _apply_wallet_change(wallet, tx_type, amount, sign, reason="", created_by=None, related_order=None):
    amount = Decimal(amount).quantize(Decimal("0.01"))
    wallet = VendorWallet.objects.select_for_update().get(id=wallet.id)
    previous = wallet.balance
    new_balance = previous + (sign * amount)
    if new_balance < 0:
        raise ValueError("Insufficient wallet balance for this operation.")
    wallet.balance = new_balance
    wallet.save(update_fields=["balance", "last_updated"])
    return VendorWalletTransaction.objects.create(
        wallet=wallet,
        transaction_type=tx_type,
        amount=amount,
        previous_balance=previous,
        new_balance=new_balance,
        reason=reason,
        created_by=created_by,
        related_order=related_order,
    )


def credit_wallet(wallet, tx_type, amount, **kwargs):
    return _apply_wallet_change(wallet, tx_type, amount, Decimal("1"), **kwargs)


def debit_wallet(wallet, tx_type, amount, **kwargs):
    return _apply_wallet_change(wallet, tx_type, amount, Decimal("-1"), **kwargs)


@db_transaction.atomic
def settle_cod_delivery(order, cod_collected):
    settlement = calculate_settlement(cod_collected, order.delivery_fee or 0)
    wallet = get_or_create_wallet(order.vendor)
    credit_tx = credit_wallet(
        wallet,
        VendorWalletTransaction.TYPE_CREDIT,
        settlement["cod_collected"],
        related_order=order,
        reason=f"COD collected on {order.order_reference}",
    )
    fee_tx = None
    if settlement["fee_debit"] > 0:
        fee_tx = debit_wallet(
            wallet,
            VendorWalletTransaction.TYPE_DELIVERY_FEE,
            settlement["fee_debit"],
            related_order=order,
            reason=f"Falcon delivery fee for {order.order_reference}",
        )
    order.delivered_at = timezone.now()
    order.save(update_fields=["delivered_at", "updated_at"])
    return {"settlement": settlement, "credit_tx": credit_tx, "fee_tx": fee_tx}


def receive_stock(product, warehouse, acting_user):
    product.warehouse = warehouse
    product.status = VendorProduct.STATUS_RECEIVED
    product.quantity_received = product.quantity_available if product.quantity_received == 0 else product.quantity_received
    product.received_at = timezone.now()
    product.save(update_fields=["warehouse", "status", "quantity_received", "received_at"])
    return product


def deduct_order_stock(order):
    product = order.product
    if product is None:
        raise ValueError("Order has no linked inventory item.")
    if product.quantity_available < order.quantity:
        raise ValueError(
            f"Only {product.quantity_available} unit(s) of {product.name} available."
        )
    product.quantity_available -= order.quantity
    if product.quantity_available == 0:
        product.status = VendorProduct.STATUS_DEPLETED
    product.save(update_fields=["quantity_available", "status"])


ORDER_TRANSITIONS = {
    VendorFulfillmentOrder.STATUS_PENDING: [
        VendorFulfillmentOrder.STATUS_PROCESSING,
        VendorFulfillmentOrder.STATUS_CANCELLED,
    ],
    VendorFulfillmentOrder.STATUS_PROCESSING: [
        VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT,
        VendorFulfillmentOrder.STATUS_CANCELLED,
    ],
    VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT: [
        VendorFulfillmentOrder.STATUS_ASSIGNED,
        VendorFulfillmentOrder.STATUS_CANCELLED,
    ],
    VendorFulfillmentOrder.STATUS_ASSIGNED: [
        VendorFulfillmentOrder.STATUS_APPROVED,
        VendorFulfillmentOrder.STATUS_CANCELLED,
    ],
    VendorFulfillmentOrder.STATUS_APPROVED: [
        VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY,
        VendorFulfillmentOrder.STATUS_DELIVERED,
        VendorFulfillmentOrder.STATUS_FAILED,
        VendorFulfillmentOrder.STATUS_CANCELLED,
    ],
    VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY: [
        VendorFulfillmentOrder.STATUS_DELIVERED,
        VendorFulfillmentOrder.STATUS_FAILED,
    ],
    VendorFulfillmentOrder.STATUS_DELIVERED: [],
    VendorFulfillmentOrder.STATUS_FAILED: [],
    VendorFulfillmentOrder.STATUS_CANCELLED: [],
}


def transition_order(order, new_status, save_fields=("status", "updated_at")):
    from apps.core.utils import is_final_status

    if is_final_status(order.status):
        raise ValueError(f"'{order.status}' orders are locked and cannot change.")
    allowed = ORDER_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        raise ValueError(f"Cannot move an order from '{order.status}' to '{new_status}'.")
    order.status = new_status
    order.updated_at = timezone.now()
    order.save(update_fields=list(save_fields))
    return order


def request_withdrawal(vendor, amount, profile):
    wallet = get_or_create_wallet(vendor)
    amount = Decimal(amount).quantize(Decimal("0.01"))
    charge = Decimal(settings.WITHDRAWAL_FEE)
    if not profile.bank_verified:
        raise ValueError("Verify your bank account before requesting a withdrawal.")
    if amount <= charge:
        raise ValueError(f"Withdrawal amount must exceed the \u20a6{charge} charge.")
    if wallet.balance < amount:
        raise ValueError("Requested amount exceeds your wallet balance.")
    return VendorWithdrawalRequest.objects.create(
        vendor=vendor,
        amount_requested=amount,
        withdrawal_charge=charge,
        amount_transferred=amount - charge,
        bank_name=profile.bank_name,
        bank_code=profile.bank_code,
        account_number=profile.bank_account_number,
        account_name=profile.account_name,
    )


@db_transaction.atomic
def approve_withdrawal(withdrawal, processed_by):
    from apps.audit.services import log_action  # noqa

    if withdrawal.status not in (
        VendorWithdrawalRequest.STATUS_PENDING,
        VendorWithdrawalRequest.STATUS_APPROVED,
    ):
        raise ValueError("Only pending withdrawals can be approved.")
    wallet = get_or_create_wallet(withdrawal.vendor)
    debit_wallet(
        wallet,
        VendorWalletTransaction.TYPE_WITHDRAWAL,
        withdrawal.amount_transferred,
        reason=f"Withdrawal payout to {withdrawal.bank_name} {withdrawal.account_number}",
    )
    debit_wallet(
        wallet,
        VendorWalletTransaction.TYPE_WITHDRAWAL_FEE,
        withdrawal.withdrawal_charge,
        reason="\u20a6250 Falcon withdrawal charge",
    )
    recipient_code = withdrawal.paystack_recipient_code
    if not recipient_code:
        try:
            recipient_code = create_transfer_recipient(
                name=withdrawal.account_name,
                account_number=withdrawal.account_number,
                bank_code=withdrawal.bank_code or "058",
            )
            withdrawal.paystack_recipient_code = recipient_code
        except PaystackError as exc:
            withdrawal.status = VendorWithdrawalRequest.STATUS_APPROVED
            withdrawal.processed_by = processed_by
            withdrawal.processed_at = timezone.now()
            withdrawal.save()
            return withdrawal, f"Approved but transfer pending: {exc}"
    simulated = recipient_code.startswith("RCP_sim_")
    try:
        transfer_code = initiate_transfer(
            amount_naira=float(withdrawal.amount_transferred),
            recipient_code=recipient_code,
            reason="Falcon vendor withdrawal",
            reference=f"WD-{withdrawal.id}-{generate_reference('T', 6)}",
        )
        withdrawal.paystack_transfer_code = transfer_code
    except PaystackError as exc:
        withdrawal.paystack_recipient_code = recipient_code
        withdrawal.status = VendorWithdrawalRequest.STATUS_APPROVED
        withdrawal.processed_by = processed_by
        withdrawal.processed_at = timezone.now()
        withdrawal.save()
        return withdrawal, f"Approved; automatic transfer failed ({exc}). Payout manually."
    withdrawal.simulated = simulated
    withdrawal.status = VendorWithdrawalRequest.STATUS_COMPLETED
    withdrawal.processed_by = processed_by
    withdrawal.processed_at = timezone.now()
    withdrawal.save()
    note = "completed via simulated transfer (dev mode)" if simulated else "completed"
    return withdrawal, f"Withdrawal approved and {note}."
