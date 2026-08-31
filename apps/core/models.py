from django.db import models


class QuantityPrice(models.Model):
    """Custom quantity pricing rules for a product.

    A row links a product to a specific quantity and the total price to
    charge for that quantity. If no row exists for a quantity, the
    default (base unit price x quantity) applies instead.
    """

    marketplace_product = models.ForeignKey(
        "marketplace.MarketplaceProduct", on_delete=models.CASCADE,
        null=True, blank=True, related_name="quantity_prices",
    )
    vendor_product = models.ForeignKey(
        "vendor.VendorProduct", on_delete=models.CASCADE,
        null=True, blank=True, related_name="quantity_prices",
    )
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["quantity"]
        constraints = [
            models.UniqueConstraint(
                fields=["marketplace_product", "quantity"],
                name="uniq_marketplace_qty_price",
            ),
            models.UniqueConstraint(
                fields=["vendor_product", "quantity"],
                name="uniq_vendor_qty_price",
            ),
        ]

    def __str__(self):
        return f"qty {self.quantity} -> \u20a6{self.price}"


def save_quantity_prices(product, quantity_keys, value_keys):
    """Parse parallel lists of quantity/price form data and persist rules.

    ``product`` accepts either a MarketplaceProduct or VendorProduct.
    ``quantity_keys`` / ``value_keys`` are lists of raw POST values.
    Returns the number of rules persisted. Rows with no quantity or no
    valid price are skipped.
    """
    from decimal import Decimal, InvalidOperation

    manager = getattr(product, "quantity_prices", None)
    if manager is None:
        return 0
    new_rules = []
    for qty_raw, val_raw in zip(quantity_keys, value_keys):
        try:
            qty = int(qty_raw)
        except (TypeError, ValueError):
            continue
        if qty <= 1:  # quantity 1 is always the base product price (Rule 1)
            continue
        try:
            val = Decimal(str(val_raw or ""))
        except (InvalidOperation, ValueError):
            continue
        if val < 0:
            continue
        new_rules.append((qty, val))
    seen = {}
    for qty, val in new_rules:
        seen[qty] = val
    manager.all().delete()
    for qty, val in seen.items():
        manager.create(quantity=qty, price=val)
    return len(seen)


def effective_unit_price(product, quantity):
    """Return the effective per-unit price for a product and quantity.

    Priority 1: a custom quantity price exists for the exact quantity ->
    the per-unit price is custom_total / quantity.
    Priority 2: base unit price.
    """
    qty = int(quantity or 1)
    rules = None
    try:
        if hasattr(product, "quantity_prices"):
            rules = list(product.quantity_prices.all())
    except Exception:
        rules = None
    custom_total = None
    for rule in rules or []:
        if rule.quantity == qty and rule.quantity > 1:  # qty 1 is always base price (Rule 1)
            custom_total = rule.price
            break
    base = getattr(product, "price", None)
    from decimal import Decimal, InvalidOperation
    try:
        base = Decimal(base or 0)
    except (InvalidOperation, TypeError, ValueError):
        base = Decimal("0")
    if custom_total is not None and qty > 1:
        return Decimal(custom_total) / Decimal(qty)
    return base


def line_total(product, quantity):
    """Return the total price for a product and quantity.

    Priority 1: custom quantity price for the exact quantity.
    Priority 2: base unit price x quantity.
    """
    qty = int(quantity or 1)
    rules = None
    try:
        if hasattr(product, "quantity_prices"):
            rules = list(product.quantity_prices.all())
    except Exception:
        rules = None
    for rule in rules or []:
        if rule.quantity == qty and rule.quantity > 1:  # qty 1 is always base price (Rule 1)
            return rule.price
    base = getattr(product, "price", None)
    from decimal import Decimal, InvalidOperation
    try:
        base = Decimal(base or 0)
    except (InvalidOperation, TypeError, ValueError):
        base = Decimal("0")
    return base * Decimal(qty)


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=12, unique=True)
    address = models.TextField()
    city = models.CharField(max_length=80)
    state = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.address}" if self.address else self.name
