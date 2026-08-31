from django.conf import settings
from django.db import models

from apps.core.utils import generate_reference


class VendorProduct(models.Model):
    STATUS_PENDING = "pending"
    STATUS_RECEIVED = "received"
    STATUS_DEPLETED = "depleted"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Awaiting Receipt"),
        (STATUS_RECEIVED, "In Warehouse"),
        (STATUS_DEPLETED, "Depleted"),
    ]

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="vendor_products"
    )
    warehouse = models.ForeignKey(
        "core.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="vendor_products",
    )
    assigned_agent = models.ForeignKey(
        "accounts.DeliveryAgentProfile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="vendor_products_assigned",
    )
    name = models.CharField(max_length=180)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    image = models.ImageField(upload_to="vendor_products/%Y/%m/", blank=True)
    customer_location = models.CharField(max_length=255, blank=True)
    quantity_received = models.PositiveIntegerField(default=0)
    quantity_available = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    received_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.vendor.vendorprofile.business_name})"

    @property
    def is_orderable(self):
        return self.status == self.STATUS_RECEIVED and self.quantity_available > 0

    @property
    def quantity_total(self):
        return self.quantity_received or self.quantity_available


class VendorFulfillmentOrder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PROCESSING = "processing"
    STATUS_AWAITING_ASSIGNMENT = "awaiting_assignment"
    STATUS_ASSIGNED = "assigned"
    STATUS_APPROVED = "approved"
    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_AWAITING_ASSIGNMENT, "Awaiting Assignment"),
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_APPROVED, "Approved for Dispatch"),
        (STATUS_OUT_FOR_DELIVERY, "Out for Delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fulfillment_orders"
    )
    product = models.ForeignKey(
        VendorProduct, on_delete=models.SET_NULL, null=True, related_name="orders"
    )
    product_name = models.CharField(max_length=180, blank=True)
    warehouse = models.ForeignKey(
        "core.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="fulfillment_orders",
    )
    quantity = models.PositiveIntegerField(default=1)
    order_reference = models.CharField(max_length=20, unique=True, editable=False)

    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=20, blank=True)
    customer_whatsapp = models.CharField(max_length=20, blank=True)
    customer_address = models.TextField()
    customer_address_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    customer_address_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )

    cod_amount = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    # Fee earned by the delivery agent (separate from the vendor's delivery fee).
    agent_delivery_fee = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
    )
    delivery_instructions = models.TextField(blank=True)

    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING)
    assigned_agent = models.ForeignKey(
        "accounts.DeliveryAgentProfile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="fulfillment_orders",
    )
    created_by_manager = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_vendor_orders",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_reference

    @property
    def net_to_vendor(self):
        if self.delivery_fee is not None:
            return self.cod_amount - self.delivery_fee
        return None

    @property
    def agent_fee(self):
        return self.agent_delivery_fee if self.agent_delivery_fee is not None else self.delivery_fee

    def save(self, *args, **kwargs):
        if not self.order_reference:
            self.order_reference = generate_reference("VO")
        super().save(*args, **kwargs)


class VendorWallet(models.Model):
    vendor = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wallet"
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet: {self.vendor.email} (\u20a6{self.balance})"


class VendorWalletTransaction(models.Model):
    TYPE_CREDIT = "credit"
    TYPE_DELIVERY_FEE = "delivery_fee"
    TYPE_MANUAL_DEDUCTION = "manual_deduction"
    TYPE_WITHDRAWAL = "withdrawal"
    TYPE_WITHDRAWAL_FEE = "withdrawal_fee"
    TYPE_ADJUSTMENT = "adjustment"

    TYPE_CHOICES = [
        (TYPE_CREDIT, "COD Credit"),
        (TYPE_DELIVERY_FEE, "Delivery Fee"),
        (TYPE_MANUAL_DEDUCTION, "Manual Deduction"),
        (TYPE_WITHDRAWAL, "Withdrawal"),
        (TYPE_WITHDRAWAL_FEE, "Withdrawal Fee"),
        (TYPE_ADJUSTMENT, "Adjustment"),
    ]

    wallet = models.ForeignKey(
        VendorWallet, on_delete=models.CASCADE, related_name="transactions"
    )
    transaction_ref = models.CharField(max_length=20, unique=True, editable=False)
    transaction_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    previous_balance = models.DecimalField(max_digits=14, decimal_places=2)
    new_balance = models.DecimalField(max_digits=14, decimal_places=2)
    reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wallet_transactions_created",
    )
    related_order = models.ForeignKey(
        VendorFulfillmentOrder, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="wallet_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.transaction_ref} {self.transaction_type} \u20a6{self.amount}"

    def save(self, *args, **kwargs):
        if not self.transaction_ref:
            self.transaction_ref = generate_reference("WT")
        super().save(*args, **kwargs)


class VendorWithdrawalRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_COMPLETED = "completed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_COMPLETED, "Completed"),
    ]

    vendor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="withdrawals"
    )
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    withdrawal_charge = models.DecimalField(max_digits=12, decimal_places=2)
    amount_transferred = models.DecimalField(max_digits=12, decimal_places=2)
    bank_name = models.CharField(max_length=120)
    bank_code = models.CharField(max_length=12, blank=True)
    account_number = models.CharField(max_length=10)
    account_name = models.CharField(max_length=160)
    paystack_recipient_code = models.CharField(max_length=40, blank=True)
    paystack_transfer_code = models.CharField(max_length=40, blank=True)
    simulated = models.BooleanField(default=False)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    rejection_reason = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="processed_withdrawals",
    )

    class Meta:
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.id}: {self.vendor.email} \u20a6{self.amount_requested}"
