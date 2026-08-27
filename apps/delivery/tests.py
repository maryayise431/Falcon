from decimal import Decimal

from django.core.exceptions import PermissionDenied
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import DeliveryAgentProfile, FalconUser
from apps.delivery.models import DeliveryAssignment
from apps.vendor.models import VendorFulfillmentOrder


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


def make_order(vendor, status):
    order = VendorFulfillmentOrder.objects.create(
        vendor=vendor,
        product_name="Crate of Malt",
        quantity=2,
        customer_name="Musa Bello",
        customer_phone="08022223333",
        customer_address="9 Surulere Close",
        cod_amount=Decimal("8000"),
        delivery_fee=Decimal("1000"),
    )
    order.status = status
    order.save(update_fields=["status"])
    return order


class AgentFlowTests(TestCase):
    def setUp(self):
        self.vendor = make_user("dv@falcon.test", FalconUser.ROLE_VENDOR)
        self.agent_user = make_user("da@falcon.test", FalconUser.ROLE_AGENT)
        self.agent = DeliveryAgentProfile.objects.create(
            user=self.agent_user,
            full_name="Dan Agent",
            phone_number="08033334444",
            is_available=True,
        )
        self.other_agent_user = make_user("da2@falcon.test", FalconUser.ROLE_AGENT)
        DeliveryAgentProfile.objects.create(
            user=self.other_agent_user, full_name="Other Agent", is_available=True
        )

    def _assignment(self, order_status="approved"):
        order = make_order(self.vendor, order_status)
        return DeliveryAssignment.objects.create(order=order, agent=self.agent)

    def test_assignment_created_in_assigned_state(self):
        a = self._assignment(order_status="assigned")
        self.assertEqual(a.status, DeliveryAssignment.STATUS_ASSIGNED)

    def test_pickup_requires_manager_dispatch_approval(self):
        # Order is still awaiting_assignment -> pickup must be refused.
        order = make_order(self.vendor, "awaiting_assignment")
        DeliveryAssignment.objects.create(order=order, agent=self.agent)
        c = Client(); c.force_login(self.agent_user)
        r = c.post(reverse("agent:pickup", args=[order.order_reference]), follow=True)
        body = r.content.decode()
        order.refresh_from_db()
        self.assertEqual(order.status, "awaiting_assignment")
        self.assertIn("approval", body.lower())

    def test_full_delivery_marks_order_and_settles_wallet(self):
        from apps.vendor.models import VendorWallet

        order = make_order(self.vendor, "approved")
        DeliveryAssignment.objects.create(order=order, agent=self.agent)
        c = Client(); c.force_login(self.agent_user)

        c.post(reverse("agent:pickup", args=[order.order_reference]), follow=True)
        order.refresh_from_db()
        self.assertEqual(order.status, VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY)

        r = c.post(
            reverse("agent:mark_delivered", args=[order.order_reference]),
            {"cod_collected": "8000"},
            follow=True,
        )
        order.refresh_from_db()
        self.assertEqual(order.status, VendorFulfillmentOrder.STATUS_DELIVERED)
        wallet = VendorWallet.objects.get(vendor=self.vendor)
        # COD credited 8000, delivery fee debited 1000
        self.assertEqual(wallet.balance, Decimal("7000"))

    def test_deliver_before_pickup_refused(self):
        order = make_order(self.vendor, "approved")
        DeliveryAssignment.objects.create(order=order, agent=self.agent)
        c = Client(); c.force_login(self.agent_user)
        c.post(
            reverse("agent:mark_delivered", args=[order.order_reference]),
            {"cod_collected": "8000"},
            follow=True,
        )
        order.refresh_from_db()
        self.assertNotEqual(order.status, VendorFulfillmentOrder.STATUS_DELIVERED)

    def test_agent_cannot_access_other_agents_delivery(self):
        assignment = self._assignment(order_status="approved")
        c = Client(); c.force_login(self.other_agent_user)
        r = c.get(reverse("agent:agent_detail", args=[assignment.order.order_reference]))
        self.assertEqual(r.status_code, 403)


class ManagerOverrideTests(TestCase):
    def setUp(self):
        self.manager = make_user("mo@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("mo2@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("mo3@falcon.test", FalconUser.ROLE_VENDOR)

    def test_override_requires_manager(self):
        order = make_order(self.vendor, "out_for_delivery")
        c = Client(); c.force_login(self.sub)
        r = c.post(
            reverse("manager_delivery_failed", args=[order.order_reference]), follow=True
        )
        self.assertEqual(r.status_code, 403)

    def test_override_marks_failed_and_audits(self):
        from apps.audit.models import AuditLog

        order = make_order(self.vendor, "out_for_delivery")
        DeliveryAssignment.objects.create(order=order, agent=DeliveryAgentProfile.objects.create(
            user=make_user("ovag@falcon.test", FalconUser.ROLE_AGENT),
            full_name="Override Agent",
        ))
        c = Client(); c.force_login(self.manager)
        r = c.post(
            reverse("manager_delivery_failed", args=[order.order_reference]), follow=True
        )
        order.refresh_from_db()
        self.assertEqual(order.status, "failed")
        self.assertTrue(
            AuditLog.objects.filter(
                action="delivery_failed", affected_object_id=order.pk
            ).exists()
        )

    def test_public_tracking_without_login(self):
        order = make_order(self.vendor, "out_for_delivery")
        c = Client()
        self.assertEqual(c.get("/track/").status_code, 200)
        r = c.get(f"/track/{order.order_reference}/")
        self.assertEqual(r.status_code, 200)

    def test_tracking_unknown_reference_redirects(self):
        r = Client().get("/track/FD-NOPE000/")
        self.assertEqual(r.status_code, 302)
