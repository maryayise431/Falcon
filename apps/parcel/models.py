from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.utils import generate_reference


class ParcelRequest(models.Model):
    PICKUP = "pickup"
    DROP_OFF = "drop_off"

    PICKUP_TYPE_CHOICES = [
        (PICKUP, "Request Pickup"),
        (DROP_OFF, "Drop Off at Warehouse"),
    ]

    STATUS_PENDING = "pending"
    STATUS_QUOTED = "quoted"
    STATUS_PROCESSING = "processing"
    STATUS_IN_TRANSIT = "in_transit"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Awaiting Quote"),
        (STATUS_QUOTED, "Quoted - Awaiting Payment"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_IN_TRANSIT, "In Transit"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="parcels"
    )
    parcel_reference = models.CharField(max_length=20, unique=True, editable=False)

    sender_name = models.CharField(max_length=120)
    sender_phone = models.CharField(max_length=20)
    pickup_type = models.CharField(max_length=10, choices=PICKUP_TYPE_CHOICES, default=PICKUP)
    dropoff_warehouse = models.ForeignKey(
        "core.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="dropoff_parcels",
    )
    pickup_address = models.TextField(blank=True)
    pickup_address_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    pickup_address_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    receiver_name = models.CharField(max_length=120)
    receiver_phone = models.CharField(max_length=20)
    receiver_address = models.TextField()
    receiver_address_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    receiver_address_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)

    parcel_type = models.CharField(
        max_length=20, blank=True,
        choices=[
            ("document", "Document"),
            ("electronics", "Electronics"),
            ("clothing", "Clothing"),
            ("food", "Food & Perishable"),
            ("fragile", "Fragile"),
            ("heavy", "Heavy/Bulky"),
            ("other", "Other"),
        ],
    )
    parcel_image = models.ImageField(upload_to="parcels/%Y/%m/", blank=True)
    parcel_description = models.TextField()
    delivery_instructions = models.TextField(blank=True)

    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    quoted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="parcel_quotes_made",
    )
    quote_note = models.CharField(max_length=255, blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True)

    paystack_reference = models.CharField(max_length=100, blank=True)
    payment_status = models.CharField(
        max_length=10,
        choices=[("pending", "Pending"), ("paid", "Paid"), ("failed", "Failed")],
        default="pending",
    )
    payment_simulated = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    assigned_agent = models.ForeignKey(
        "accounts.DeliveryAgentProfile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="parcel_assignments",
    )
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.parcel_reference

    def save(self, *args, **kwargs):
        if not self.parcel_reference:
            self.parcel_reference = generate_reference("PR")
        super().save(*args, **kwargs)

    def mark_paid(self, reference="", simulated=False):
        self.payment_status = "paid"
        self.paystack_reference = reference or self.paystack_reference
        self.payment_simulated = simulated
        self.paid_at = timezone.now()
        self.status = self.STATUS_PROCESSING
        self.save(
            update_fields=[
                "payment_status",
                "paystack_reference",
                "payment_simulated",
                "paid_at",
                "status",
                "updated_at",
            ]
        )
