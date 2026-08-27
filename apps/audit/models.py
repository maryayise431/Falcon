from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("wallet_credit", "Wallet Credit"),
        ("wallet_debit", "Wallet Debit"),
        ("wallet_deduction", "Manual Wallet Deduction"),
        ("order_created", "Order Created"),
        ("order_status_changed", "Order Status Changed"),
        ("order_approved", "Order Approved"),
        ("agent_assigned", "Agent Assigned"),
        ("delivery_completed", "Delivery Completed"),
        ("delivery_failed", "Delivery Failed"),
        ("withdrawal_requested", "Withdrawal Requested"),
        ("withdrawal_approved", "Withdrawal Approved"),
        ("withdrawal_rejected", "Withdrawal Rejected"),
        ("product_created", "Product Created"),
        ("product_updated", "Product Updated"),
        ("product_published", "Product Published"),
        ("product_unpublished", "Product Unpublished"),
        ("product_deleted", "Product Deleted"),
        ("user_created", "User Created"),
        ("user_disabled", "User Disabled"),
        ("user_enabled", "User Enabled"),
        ("user_deleted", "User Deleted"),
        ("bank_details_updated", "Bank Details Updated"),
        ("parcel_quoted", "Parcel Quoted"),
        ("login_as_role", "Role Login"),
    ]

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="audit_actions",
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    affected_model = models.CharField(max_length=80)
    affected_object_id = models.PositiveIntegerField(null=True, blank=True)
    description = models.CharField(max_length=255, blank=True)
    previous_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.action} on {self.affected_model}#{self.affected_object_id}"
