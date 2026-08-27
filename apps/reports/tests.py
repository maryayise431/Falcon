from datetime import timedelta
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import FalconUser
from apps.audit.models import AuditLog
from apps.marketplace.models import MarketplaceOrder, MarketplaceOrderItem, MarketplacePayment, MarketplaceProduct
from apps.parcel.models import ParcelRequest
from apps.vendor.models import (
    VendorFulfillmentOrder,
    VendorWalletTransaction,
)
from apps.vendor.services import get_or_create_wallet
from apps.reports.views import (
    bucket_rows,
    revenue_component_fee_tx,
    revenue_component_marketplace,
    revenue_component_parcel,
)


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


class RevenueExclusionTests(TestCase):
    """Vendor COD money is NOT Falcon revenue — only fees are."""

    def setUp(self):
        self.vendor = make_user("rv@falcon.test", FalconUser.ROLE_VENDOR)
        self.start = timezone.now() - timedelta(days=1)
        self.end = timezone.now() + timedelta(days=1)

    def test_cod_credits_excluded_from_revenue(self):
        wallet = get_or_create_wallet(self.vendor)
        VendorWalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=VendorWalletTransaction.TYPE_CREDIT,
            amount=Decimal("50000"),  # vendor's own COD sales
            previous_balance=Decimal("0"),
            new_balance=Decimal("50000"),
        )
        fee_tx = revenue_component_fee_tx(self.start, self.end, "delivery_fee")
        self.assertEqual(fee_tx, 0)

    def test_delivery_fees_counted(self):
        from apps.vendor.services import settle_cod_delivery

        order = VendorFulfillmentOrder.objects.create(
            vendor=self.vendor,
            product_name="Item",
            quantity=1,
            customer_name="C",
            customer_phone="08",
            customer_address="X",
            cod_amount=Decimal("10000"),
            delivery_fee=Decimal("2000"),
        )
        settle_cod_delivery(order, Decimal("10000"))
        self.assertEqual(
            revenue_component_fee_tx(self.start, self.end, "delivery_fee"),
            Decimal("2000"),
        )

    def test_marketplace_component_uses_paid_orders_only(self):
        product = MarketplaceProduct.objects.create(
            name="P", price=Decimal("1000"), stock=9
        )
        buyer = make_user("rb@falcon.test")
        paid = MarketplaceOrder.objects.create(
            customer=buyer,
            total_amount=Decimal("3000"),
            delivery_address="1 Test Road",
        )
        MarketplacePayment.objects.create(order=paid, status="success", amount=Decimal("3000"))
        MarketplaceOrderItem.objects.create(
            order=paid, product=product, product_name="P", quantity=3, unit_price=Decimal("1000")
        )
        unpaid = MarketplaceOrder.objects.create(
            customer=buyer,
            total_amount=Decimal("5000"),
            delivery_address="1 Test Road",
        )
        MarketplacePayment.objects.create(order=unpaid, status="pending", amount=Decimal("5000"))
        MarketplaceOrderItem.objects.create(
            order=unpaid, product=product, product_name="P", quantity=5, unit_price=Decimal("1000")
        )
        total = revenue_component_marketplace(self.start, self.end)
        self.assertEqual(total, Decimal("3000"))

    def test_parcel_component_counts_paid_parcels(self):
        cust = make_user("rp@falcon.test", email_verified=True)
        p = ParcelRequest.objects.create(
            requested_by=cust,
            sender_name="A", sender_phone="1", pickup_address="a",
            receiver_name="B", receiver_phone="2", receiver_address="b",
            parcel_description="x",
            delivery_fee=Decimal("1800"), payment_status="paid",
            status=ParcelRequest.STATUS_PROCESSING,
            paystack_reference="PS-1", paid_at=timezone.now(),
        )
        self.assertEqual(revenue_component_parcel(self.start, self.end), Decimal("1800"))

    def test_bucket_rows_structure(self):
        rows = bucket_rows(lambda d: d.date().isoformat(), self.start, self.end, timedelta(days=1))
        self.assertTrue(len(rows) >= 1)
        first = rows[0]
        for key in ("marketplace", "fulfilment_fees", "parcel", "withdrawal_charges"):
            self.assertIn(key, first)


class ReportAccessAndExportTests(TestCase):
    def setUp(self):
        self.manager = make_user("rm@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("rs@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("rv2@falcon.test", FalconUser.ROLE_VENDOR)

    def test_manager_can_view_all_reports(self):
        c = Client(); c.force_login(self.manager)
        for name in ("report_revenue", "report_cod", "report_withdrawals", "report_daily", "report_weekly", "report_monthly"):
            url = reverse(f"reports:{name}")
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)

    def test_sub_manager_read_only_access_allowed(self):
        c = Client(); c.force_login(self.sub)
        r = c.get(reverse("reports:report_revenue"))
        self.assertEqual(r.status_code, 200)

    def test_vendor_blocked_from_reports(self):
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("reports:report_revenue"))
        self.assertEqual(r.status_code, 403)

    def test_csv_export_content_type_and_header(self):
        c = Client(); c.force_login(self.manager)
        r = c.get(reverse("reports:report_daily") + "?export=csv&period=this_month")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r["Content-Type"])
        disposition = r["Content-Disposition"]
        self.assertTrue(disposition.startswith("attachment;"))
        first_line = r.content.decode().splitlines()[0].strip().strip('"').lower()
        self.assertIn("bucket", first_line)
        self.assertIn("marketplace", first_line)

    def test_custom_period_params_respected(self):
        c = Client(); c.force_login(self.manager)
        start = (timezone.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        end = timezone.now().strftime("%Y-%m-%d")
        r = c.get(reverse("reports:report_daily") + f"?period=custom&start={start}&end={end}")
        self.assertEqual(r.status_code, 200)
