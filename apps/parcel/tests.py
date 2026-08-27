from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import FalconUser
from apps.parcel.models import ParcelRequest


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


def make_parcel(requested_by, status=None):
    parcel = ParcelRequest.objects.create(
        requested_by=requested_by,
        sender_name="Ada Obi",
        sender_phone="08011112222",
        pickup_address="1 Allen Avenue",
        receiver_name="Musa Bello",
        receiver_phone="08022223333",
        receiver_address="2 Herbert Macaulay Way",
        parcel_description="Documents envelope",
    )
    if status:
        parcel.status = status
        parcel.save(update_fields=["status"])
    return parcel


class ParcelLifecycleTests(TestCase):
    def setUp(self):
        self.customer = make_user("pc@falcon.test", email_verified=True)
        self.manager = make_user("pm@falcon.test", FalconUser.ROLE_MANAGER)
        self.other = make_user("po@falcon.test", email_verified=True)

    def test_new_parcel_starts_pending_with_reference(self):
        p = make_parcel(self.customer)
        self.assertEqual(p.status, ParcelRequest.STATUS_PENDING)
        self.assertTrue(p.parcel_reference.startswith("PR"))
        self.assertIsNone(p.delivery_fee)

    def test_manager_quotes_pending_parcel(self):
        p = make_parcel(self.customer)
        c = Client(); c.force_login(self.manager)
        r = c.post(
            reverse("parcel:manager_quote", args=[p.parcel_reference]),
            {"delivery_fee": "2500"},
            follow=True,
        )
        p.refresh_from_db()
        self.assertEqual(p.delivery_fee, Decimal("2500"))
        self.assertEqual(p.status, ParcelRequest.STATUS_QUOTED)
        self.assertEqual(p.quoted_by_id, self.manager.id)

    def test_cannot_quote_twice(self):
        p = make_parcel(self.customer)
        p.delivery_fee = Decimal("2000")
        p.status = ParcelRequest.STATUS_QUOTED
        p.save()
        c = Client(); c.force_login(self.manager)
        c.post(
            reverse("parcel:manager_quote", args=[p.parcel_reference]),
            {"delivery_fee": "9999"},
            follow=True,
        )
        p.refresh_from_db()
        self.assertEqual(p.delivery_fee, Decimal("2000"))

    def test_mark_paid_moves_to_processing(self):
        p = make_parcel(self.customer)
        p.delivery_fee = Decimal("2500")
        p.mark_paid("PS-TEST-123")
        p.refresh_from_db()
        self.assertEqual(p.payment_status, "paid")
        self.assertEqual(p.paystack_reference, "PS-TEST-123")
        self.assertEqual(p.status, ParcelRequest.STATUS_PROCESSING)
        self.assertIsNotNone(p.paid_at)

    def test_owner_sees_detail_but_others_do_not(self):
        mine = make_parcel(self.customer)
        theirs = make_parcel(self.other)
        c = Client(); c.force_login(self.customer)

        r = c.get(reverse("parcel:detail", args=[mine.parcel_reference]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, mine.parcel_reference)

        # scoped queryset -> 404, never leaks another customer's parcel
        r = c.get(reverse("parcel:detail", args=[theirs.parcel_reference]))
        self.assertEqual(r.status_code, 404)

    def test_manager_override_delivers_paid_parcel(self):
        p = make_parcel(self.customer)
        p.delivery_fee = Decimal("2000")
        p.mark_paid("PS-X")
        c = Client(); c.force_login(self.manager)
        r = c.post(
            reverse("parcel:manager_delivered", args=[p.parcel_reference]), follow=True
        )
        p.refresh_from_db()
        self.assertEqual(p.status, ParcelRequest.STATUS_DELIVERED)
        self.assertIsNotNone(p.delivered_at)


class ParcelAccessControlTests(TestCase):
    def setUp(self):
        self.customer = make_user("pac@falcon.test", email_verified=True)

    def test_send_page_public_or_customer_only(self):
        r = Client().get(reverse("parcel:send"))
        self.assertIn(r.status_code, (200, 302))

    def test_anonymous_cannot_view_parcel_history(self):
        r = Client().get(reverse("parcel:history"))
        self.assertEqual(r.status_code, 302)

    def test_manager_area_blocks_customers(self):
        c = Client(); c.force_login(self.customer)
        r = c.get(reverse("parcel:manager_list"))
        self.assertEqual(r.status_code, 403)


class VendorParcelAccessTests(TestCase):
    def setUp(self):
        self.vendor = make_user("vp@falcon.test", FalconUser.ROLE_VENDOR)
        self.vendor.email_verified = True
        self.vendor.save(update_fields=["email_verified"])

    def test_vendor_can_open_send_page(self):
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("parcel:send"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("SEND A PARCEL", r.content.decode())

    def test_send_form_prefills_vendor_profile(self):
        from apps.accounts.models import VendorProfile

        VendorProfile.objects.create(
            user=self.vendor,
            business_name="Kola Collections",
            username="kolacollections",
            contact_name="Kola Adebayo",
            phone_number="08033334444",
        )
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("parcel:send"))
        self.assertContains(r, 'value="Kola Adebayo"')
        self.assertContains(r, 'value="08033334444"')

    def test_vendor_sees_own_parcels_with_vendor_sidebar(self):
        make_parcel(self.vendor)
        other = make_user("vc@falcon.test", email_verified=True)
        make_parcel(other)
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("parcel:history"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("My Parcels", html)
        self.assertNotIn("customer/dashboard/", html.split("</aside>")[0])
        detail = self.client  # noqa: F841
        ref = ParcelRequest.objects.filter(requested_by=self.vendor).first().parcel_reference
        rd = c.get(reverse("parcel:detail", args=[ref]))
        self.assertEqual(rd.status_code, 200)
        self.assertIn("Send a Parcel", rd.content.decode())

    def test_manager_sidebar_has_no_admin_links(self):
        manager = make_user("vm@falcon.test", FalconUser.ROLE_MANAGER, is_superuser=True)
        manager.email_verified = True
        manager.save(update_fields=["email_verified"])
        c = Client(); c.force_login(manager)
        r = c.get("/manager/dashboard/")
        html = r.content.decode().split("</aside>")[0]
        self.assertNotIn("Django Admin", html)
        self.assertNotIn("Audit Trail", html)
