from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

from apps.core.utils import generate_reference


class ProductCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True)
    icon = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "product categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class ProductImage(models.Model):
    image = models.ImageField(upload_to="products/%Y/%m/")
    alt = models.CharField(max_length=160, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.alt or f"Image #{self.id}"


class MarketplaceProduct(models.Model):
    name = models.CharField(max_length=180)
    slug = models.SlugField(max_length=200, unique=True, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    stock = models.PositiveIntegerField(default=0)
    images = models.ManyToManyField(ProductImage, blank=True, related_name="products")
    category = models.ForeignKey(
        ProductCategory, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="products",
    )
    is_published = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
        related_name="marketplace_products",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def primary_image(self):
        return self.images.first()

    @property
    def is_in_stock(self):
        return self.stock > 0

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:180] or "product"
            candidate = base
            counter = 2
            while MarketplaceProduct.objects.filter(slug=candidate).exists():
                candidate = f"{base}-{counter}"
                counter += 1
            self.slug = candidate
        super().save(*args, **kwargs)


class MarketplaceOrder(models.Model):
    STATUS_PENDING = "pending"
    STATUS_AWAITING_FEE = "awaiting_fee"
    STATUS_PROCESSING = "processing"
    STATUS_OUT_FOR_DELIVERY = "out_for_delivery"
    STATUS_DELIVERED = "delivered"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    METHOD_PICKUP = "pickup"
    METHOD_DOOR = "door_delivery"
    METHOD_CHOICES = [
        (METHOD_PICKUP, "Warehouse Pickup"),
        (METHOD_DOOR, "Door Delivery"),
    ]

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_AWAITING_FEE, "Awaiting Delivery Fee"),
        (STATUS_PROCESSING, "Processing"),
        (STATUS_OUT_FOR_DELIVERY, "Out for Delivery"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="marketplace_orders"
    )
    order_reference = models.CharField(max_length=20, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    delivery_method = models.CharField(
        max_length=20, choices=METHOD_CHOICES, default=METHOD_DOOR,
    )
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    delivery_fee_set_at = models.DateTimeField(null=True, blank=True)
    pickup_warehouse = models.ForeignKey(
        "core.Warehouse", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="marketplace_pickups",
    )
    delivery_address = models.TextField(blank=True)
    delivery_address_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    delivery_address_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    receiver_phone = models.CharField(max_length=20, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.order_reference

    @property
    def product_total(self):
        return self.total_amount - self.delivery_fee

    def save(self, *args, **kwargs):
        if not self.order_reference:
            self.order_reference = generate_reference("MK")
        super().save(*args, **kwargs)


class MarketplaceOrderItem(models.Model):
    order = models.ForeignKey(
        MarketplaceOrder, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        MarketplaceProduct, on_delete=models.SET_NULL, null=True, related_name="order_items"
    )
    product_name = models.CharField(max_length=180)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Exact line subtotal when quantity pricing applies (else unit_price x quantity).",
    )

    def __str__(self):
        return f"{self.quantity} x {self.product_name}"

    @property
    def subtotal(self):
        if self.line_total is not None:
            return self.line_total
        return self.unit_price * self.quantity


class MarketplacePayment(models.Model):
    METHOD_PAYSTACK = "paystack"
    METHOD_CHOICES = [(METHOD_PAYSTACK, "Paystack")]

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    order = models.OneToOneField(
        MarketplaceOrder, on_delete=models.CASCADE, related_name="payment"
    )
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_PAYSTACK)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paystack_reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    simulated = models.BooleanField(default=False)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Payment for {self.order.order_reference} ({self.status})"

    def mark_paid(self):
        self.status = self.STATUS_SUCCESS
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "paid_at"])
