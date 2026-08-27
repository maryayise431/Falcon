from django.conf import settings
from django.db import models


class DeliveryAssignment(models.Model):
    STATUS_ASSIGNED = "assigned"
    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_ASSIGNED, "Assigned"),
        (STATUS_OUT_FOR_DELIVERY, "Out for Delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
    ]

    order = models.ForeignKey(
        "vendor.VendorFulfillmentOrder", on_delete=models.CASCADE,
        null=True, blank=True, related_name="assignments",
    )
    parcel = models.ForeignKey(
        "parcel.ParcelRequest", on_delete=models.CASCADE,
        null=True, blank=True, related_name="assignments",
    )
    marketplace_order = models.ForeignKey(
        "marketplace.MarketplaceOrder", on_delete=models.CASCADE,
        null=True, blank=True, related_name="assignments",
    )
    agent = models.ForeignKey(
        "accounts.DeliveryAgentProfile", on_delete=models.PROTECT, related_name="assignments"
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="assignments_made"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ASSIGNED)
    delivery_notes = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cod_collected = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cod_confirmed = models.BooleanField(default=False)

    class Meta:
        ordering = ["-assigned_at"]

    def __str__(self):
        target = self.order or self.parcel or self.marketplace_order
        return f"Assignment #{self.id} -> {target}"

    @property
    def reference(self):
        if self.order:
            return self.order.order_reference
        if self.parcel:
            return self.parcel.parcel_reference
        if self.marketplace_order:
            return self.marketplace_order.order_reference
        return str(self.id)

    @property
    def kind(self):
        if self.order_id:
            return "order"
        if self.marketplace_order_id:
            return "marketplace"
        return "parcel"
