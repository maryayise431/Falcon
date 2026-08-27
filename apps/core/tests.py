from decimal import Decimal

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import FalconUser
from apps.core.utils import (
    calculate_settlement,
    generate_otp,
    generate_reference,
    is_final_status,
    naira,
)
from apps.core.paystack import deliverable_email
from apps.marketplace.models import MarketplaceProduct
from apps.vendor.services import ORDER_TRANSITIONS


class UtilTests(TestCase):
    def test_generate_reference_prefix_and_uniqueness(self):
        a = generate_reference("FD")
        b = generate_reference("FD")
        self.assertTrue(a.startswith("FD"))
        self.assertNotEqual(a, b)

    def test_generate_otp_is_six_digits(self):
        code = generate_otp()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_calculate_settlement_math(self):
        s = calculate_settlement(Decimal("10000"), Decimal("1500"))
        self.assertEqual(s["cod_collected"], Decimal("10000"))
        self.assertEqual(s["fee_debit"], Decimal("1500"))

        s2 = calculate_settlement(Decimal("10000"))
        self.assertEqual(s2["fee_debit"], Decimal("0"))

    def test_final_statuses_locked(self):
        self.assertTrue(is_final_status("delivered"))
        self.assertTrue(is_final_status("failed"))
        self.assertFalse(is_final_status("processing"))
        # cancelled is terminal in the state machine even though not in FINAL_STATUSES
        for status in ("delivered", "failed", "cancelled"):
            self.assertEqual(ORDER_TRANSITIONS[status], [])

    def test_naira_formatting(self):
        self.assertIn("10,000", naira(Decimal("10000")))


class PublicPageTests(TestCase):
    def test_landing_page_renders_with_featured_products(self):
        MarketplaceProduct.objects.create(
            name="Test Sneakers", price=Decimal("7500"), stock=5, is_published=True
        )
        r = self.client.get(reverse("core:home"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Order it!", body)
        self.assertIn("Test Sneakers", body)
        self.assertIn("landing.css", body)

    def test_role_home_context_for_anonymous(self):
        r = self.client.get(reverse("core:home"))
        self.assertEqual(r.context["role_home"], "/")

    def test_role_home_context_per_role(self):
        cases = {
            "customer": "/customer/dashboard/",
            "vendor": "/vendor/dashboard/",
            "delivery_agent": "/agent/dashboard/",
            "manager": "/manager/dashboard/",
            "sub_manager": "/sub-manager/dashboard/",
        }
        for role, expected in cases.items():
            c = Client()
            u = FalconUser.objects.create_user(
                email=f"{role}@falcon.test", password="Passw0rd!123", role=role
            )
            c.force_login(u)
            r = c.get(reverse("core:home"))
            self.assertEqual(r.context["role_home"], expected, role)

    def test_tracking_page_public_without_login(self):
        r = self.client.get("/track/")
        self.assertEqual(r.status_code, 200)


class DeliverableEmailTests(TestCase):
    def test_valid_email_passes_through(self):
        self.assertEqual(
            deliverable_email("ada@example.com"), "ada@example.com"
        )

    def test_reserved_tld_domain_is_swapped(self):
        self.assertEqual(
            deliverable_email("ada@falcon.test"), "ada@payments.example.com"
        )
        self.assertEqual(
            deliverable_email("x@y.localhost"), "x@payments.example.com"
        )

    def test_malformed_email_gets_placeholder(self):
        self.assertEqual(deliverable_email(""), "customer@payments.example.com")
        self.assertEqual(
            deliverable_email("no-at-sign"), "no-at-sign@payments.example.com"
        )


class SeedDemoStaffPolicyTests(TestCase):
    def _seed(self):
        import io

        out = io.StringIO()
        call_command("seed_demo", "--flush", stdout=out)
        return out.getvalue()

    def test_seed_creates_no_staff_accounts(self):
        self._seed()
        staff = FalconUser.objects.filter(role__in=FalconUser.STAFF_ROLES)
        self.assertEqual(staff.count(), 0)
        self.assertTrue(FalconUser.objects.filter(role=FalconUser.ROLE_VENDOR).exists())
        self.assertTrue(
            FalconUser.objects.filter(role=FalconUser.ROLE_CUSTOMER).exists()
        )

    def test_seed_survives_without_staff_accounts(self):
        self._seed()
        from apps.marketplace.models import MarketplaceOrder
        from apps.vendor.models import VendorFulfillmentOrder

        self.assertTrue(VendorFulfillmentOrder.objects.exists())
        self.assertTrue(MarketplaceOrder.objects.exists())
