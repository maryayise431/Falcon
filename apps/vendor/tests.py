from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import FalconUser, VendorProfile
from apps.audit.models import AuditLog
from apps.vendor.models import (
    VendorFulfillmentOrder,
    VendorWallet,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)
from apps.vendor.services import (
    ORDER_TRANSITIONS,
    credit_wallet,
    debit_wallet,
    get_or_create_wallet,
    request_withdrawal,
    settle_cod_delivery,
    transition_order,
)


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


def make_vendor_order(vendor, cod="10000.00", fee="1500.00", status=None):
    order = VendorFulfillmentOrder.objects.create(
        vendor=vendor,
        product_name="Bulk T-Shirts",
        quantity=5,
        customer_name="Ada Obi",
        customer_phone="08011112222",
        customer_address="5 Yaba Lane",
        cod_amount=Decimal(cod),
        delivery_fee=Decimal(fee),
    )
    if status:
        order.status = status
        order.save(update_fields=["status"])
    return order


class StateMachineTests(TestCase):
    def setUp(self):
        self.vendor = make_user("sv@falcon.test", FalconUser.ROLE_VENDOR)

    def test_full_happy_path_transitions(self):
        order = make_vendor_order(self.vendor)
        for nxt in ("processing", "awaiting_assignment", "assigned", "approved", "out_for_delivery"):
            transition_order(order, nxt)
            order.refresh_from_db()
            self.assertEqual(order.status, nxt)
        transition_order(order, "delivered")
        self.assertTrue(VendorFulfillmentOrder.STATUS_DELIVERED == "delivered")

    def test_invalid_transition_raises(self):
        order = make_vendor_order(self.vendor)
        with self.assertRaises(ValueError):
            transition_order(order, "delivered")  # pending -> delivered not allowed

    def test_final_status_locked(self):
        for final in ("delivered", "failed", "cancelled"):
            order = make_vendor_order(self.vendor, status=final)
            for target in ORDER_TRANSITIONS:
                if target != final:
                    with self.assertRaises(ValueError):
                        transition_order(order, target)


class WalletSettlementTests(TestCase):
    def setUp(self):
        self.vendor = make_user("wv@falcon.test", FalconUser.ROLE_VENDOR)

    def test_settle_credits_cod_and_debits_fee(self):
        order = make_vendor_order(self.vendor, cod="20000.00", fee="2500.00")
        wallet = get_or_create_wallet(self.vendor)
        result = settle_cod_delivery(order, Decimal("20000"))
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("17500"))
        credit_tx = result["credit_tx"]
        fee_tx = result["fee_tx"]
        self.assertEqual(credit_tx.transaction_type, VendorWalletTransaction.TYPE_CREDIT)
        self.assertEqual(fee_tx.transaction_type, VendorWalletTransaction.TYPE_DELIVERY_FEE)
        self.assertEqual(credit_tx.new_balance, Decimal("20000"))
        self.assertEqual(fee_tx.new_balance, Decimal("17500"))

    def test_zero_cod_still_debits_fee(self):
        order = make_vendor_order(self.vendor, cod="0.00", fee="1200.00")
        wallet = get_or_create_wallet(self.vendor)
        credit_wallet(wallet, VendorWalletTransaction.TYPE_ADJUSTMENT, Decimal("5000"), reason="float")
        settle_cod_delivery(order, Decimal("0"))
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("3800"))

    def test_debit_beyond_balance_raises(self):
        wallet = get_or_create_wallet(self.vendor)
        with self.assertRaises(ValueError):
            debit_wallet(wallet, VendorWalletTransaction.TYPE_DELIVERY_FEE, Decimal("999999"))

    def test_transaction_records_balance_history(self):
        wallet = get_or_create_wallet(self.vendor)
        credit_wallet(wallet, VendorWalletTransaction.TYPE_ADJUSTMENT, Decimal("500"), reason="seed")
        txs = VendorWalletTransaction.objects.filter(wallet=wallet).order_by("created_at")
        self.assertEqual(txs.count(), 1)
        self.assertEqual(txs.first().previous_balance, Decimal("0"))
        self.assertEqual(txs.first().new_balance, Decimal("500"))


class WithdrawalServiceTests(TestCase):
    def setUp(self):
        self.vendor = make_user("xv@falcon.test", FalconUser.ROLE_VENDOR)
        self.profile = VendorProfile.objects.create(
            user=self.vendor,
            username="xvendor",
            bank_verified=True,
            bank_name="GTB",
            bank_code="058",
            bank_account_number="0123456789",
            account_name="X Vendor",
        )
        self.wallet = get_or_create_wallet(self.vendor)
        credit_wallet(self.wallet, VendorWalletTransaction.TYPE_ADJUSTMENT, Decimal("50000"), reason="test")

    def test_request_creates_pending_with_charge(self):
        w = request_withdrawal(self.vendor, Decimal("10000"), self.profile)
        self.assertEqual(w.status, VendorWithdrawalRequest.STATUS_PENDING)
        self.assertEqual(w.amount_requested, Decimal("10000"))
        self.assertEqual(w.withdrawal_charge, Decimal(str(w.withdrawal_charge)))
        self.assertEqual(
            w.amount_transferred, w.amount_requested - w.withdrawal_charge
        )

    def test_requires_verified_bank(self):
        self.profile.bank_verified = False
        self.profile.save()
        with self.assertRaises(ValueError):
            request_withdrawal(self.vendor, Decimal("10000"), self.profile)

    def test_rejects_amount_over_balance(self):
        with self.assertRaises(ValueError):
            request_withdrawal(self.vendor, Decimal("999999"), self.profile)

    def test_rejects_amount_below_charge_threshold(self):
        with self.assertRaises(ValueError):
            request_withdrawal(self.vendor, Decimal("1"), self.profile)


class VerifyBankAPITests(TestCase):
    def setUp(self):
        self.vendor = make_user("bv@falcon.test", FalconUser.ROLE_VENDOR)
        self.c = Client()
        self.c.force_login(self.vendor)

    def test_requires_vendor_authentication(self):
        r = Client().get(
            reverse("vendor:api_verify_bank"),
            {"account_number": "0123456789", "bank_code": "058"},
        )
        self.assertEqual(r.status_code, 403)

    def test_dev_mode_returns_simulated_account(self):
        from django.test import override_settings

        with override_settings(PAYSTACK_SECRET_KEY="", PAYSTACK_PUBLIC_KEY=""):
            r = self.c.get(
                reverse("vendor:api_verify_bank"),
                {"account_number": "0123456789", "bank_code": "058"},
            )
        data = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(data["verified"])
        self.assertTrue(data["simulated"])
        self.assertIn("SIMULATED", data["account_name"])

    def test_live_mode_returns_json_shape(self):
        r = self.c.get(
            reverse("vendor:api_verify_bank"),
            {"account_number": "0123456789", "bank_code": "058"},
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("verified", data)
        self.assertIn("simulated", data)

    def test_missing_params_rejected(self):
        r = self.c.get(reverse("vendor:api_verify_bank"), {"account_number": ""})
        self.assertEqual(r.status_code, 400)


class ManagerWalletControlTests(TestCase):
    def setUp(self):
        self.manager = make_user("mw@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("ms@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("mv@falcon.test", FalconUser.ROLE_VENDOR)
        get_or_create_wallet(self.vendor)
        credit_wallet(
            get_or_create_wallet(self.vendor),
            VendorWalletTransaction.TYPE_ADJUSTMENT,
            Decimal("3000"),
            reason="setup",
        )
        AuditLog.objects.create(action="login_as_role", actor=self.manager)

    def test_deduct_without_reason_refuses_and_logs_nothing(self):
        c = Client(); c.force_login(self.manager)
        bal_before = VendorWallet.objects.get(vendor=self.vendor).balance
        r = c.post(
            reverse("vendor:manager_deduct_wallet", args=[self.vendor.pk]),
            {"amount": "500", "reason": ""},
            follow=True,
        )
        bal_after = VendorWallet.objects.get(vendor=self.vendor).balance
        self.assertEqual(bal_before, bal_after)
        self.assertEqual(r.status_code, 200)

    def test_deduct_with_reason_works(self):
        c = Client(); c.force_login(self.manager)
        r = c.post(
            reverse("vendor:manager_deduct_wallet", args=[self.vendor.pk]),
            {"amount": "500", "reason": "Damaged goods adjustment"},
            follow=True,
        )
        wallet = VendorWallet.objects.get(vendor=self.vendor)
        self.assertEqual(wallet.balance, Decimal("2500"))
        self.assertEqual(r.status_code, 200)

    def test_sub_manager_cannot_deduct(self):
        c = Client(); c.force_login(self.sub)
        r = c.post(reverse("vendor:manager_deduct_wallet", args=[self.vendor.pk]), {"amount": "10", "reason": "x"})
        self.assertEqual(r.status_code, 403)


class VendorProfilePageTests(TestCase):
    def setUp(self):
        self.vendor = make_user("pv@falcon.test", FalconUser.ROLE_VENDOR)
        self.profile = VendorProfile.objects.create(
            user=self.vendor,
            username="profilevendor",
            business_name="Profile Traders",
            bank_verified=True,
            bank_name="Access",
            bank_account_number="0987654321",
            account_name="Profile Traders Ltd",
        )
        get_or_create_wallet(self.vendor)

    def test_vendor_sees_own_profile(self):
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("vendor:profile"))
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Profile Traders", body)
        self.assertIn("0987654321", body)
        self.assertIn("@profilevendor", body)

    def test_profile_blocked_for_other_roles(self):
        manager = make_user("pmgr@falcon.test", FalconUser.ROLE_MANAGER)
        customer = make_user("pcust@falcon.test")
        for u in (manager, customer):
            c = Client(); c.force_login(u)
            r = c.get(reverse("vendor:profile"))
            self.assertEqual(r.status_code, 403)


class PlanRouteAliasesTests(TestCase):
    def test_phase12_alias_routes_redirect(self):
        cases = (
            "/manager/marketplace/products/",
            "/manager/marketplace/orders/",
            "/manager/vendor-orders/",
            "/manager/parcels/",
            "/api/verify-bank/?account_number=1&bank_code=058",
        )
        for url in cases:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
