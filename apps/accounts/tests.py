from datetime import timedelta

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import FalconUser, OTPRecord, VendorProfile
from apps.accounts.views import role_home


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


class RoleHomeTests(TestCase):
    def test_role_home_mapping(self):
        self.assertEqual(role_home("customer"), "/customer/dashboard/")
        self.assertEqual(role_home("manager"), "/manager/dashboard/")
        self.assertEqual(role_home("sub_manager"), "/sub-manager/dashboard/")
        self.assertEqual(role_home("unknown"), "/")


class RegistrationOTPTests(TestCase):
    def test_registration_creates_pending_user_and_otp(self):
        r = self.client.post(
            reverse("accounts:register_customer"),
            {
                "full_name": "Test Buyer",
                "email": "buyer@falcon.test",
                "phone_number": "08011122233",
                "password": "Str0ngPass!x",
                "confirm_password": "Str0ngPass!x",
            },
            follow=True,
        )
        user = FalconUser.objects.filter(email="buyer@falcon.test").first()
        self.assertIsNotNone(user)
        self.assertFalse(user.email_verified)
        self.assertFalse(user.is_active)
        self.assertTrue(self.client.session.get("pending_verification"))
        self.assertTrue(
            OTPRecord.objects.filter(user=user, is_used=False).exists()
        )

    def test_wrong_code_rejected_and_session_kept(self):
        from django.conf import settings as dj_settings
        from django.contrib.sessions.backends.db import SessionStore

        user = make_user("otp@falcon.test", email_verified=False, is_active=False)
        OTPRecord.objects.create(
            user=user,
            otp_code="111222",
            purpose=OTPRecord.PURPOSE_REGISTRATION,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        c = Client()
        store = SessionStore()
        store["pending_verification"] = {
            "user_id": user.id,
            "purpose": OTPRecord.PURPOSE_REGISTRATION,
        }
        store.save()
        c.cookies[dj_settings.SESSION_COOKIE_NAME] = store.session_key
        r = c.post(reverse("accounts:verify_otp"), {"otp_code": "999999"}, follow=True)
        body = r.content.decode()
        self.assertIn("Incorrect code", body)
        self.assertTrue(c.session.get("pending_verification"))
        user.refresh_from_db()
        self.assertFalse(user.is_active)

    def test_expired_code_rejected(self):
        from django.conf import settings as dj_settings
        from django.contrib.sessions.backends.db import SessionStore

        user = make_user("old@falcon.test", email_verified=False, is_active=False)
        OTPRecord.objects.create(
            user=user,
            otp_code="333444",
            purpose=OTPRecord.PURPOSE_REGISTRATION,
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        c = Client()
        store = SessionStore()
        store["pending_verification"] = {
            "user_id": user.id,
            "purpose": OTPRecord.PURPOSE_REGISTRATION,
        }
        store.save()
        c.cookies[dj_settings.SESSION_COOKIE_NAME] = store.session_key
        r = c.post(reverse("accounts:verify_otp"), {"otp_code": "333444"}, follow=True)
        self.assertIn("expired", r.content.decode().lower())
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.email_verified)

    def test_correct_code_activates_user(self):
        from django.conf import settings as dj_settings
        from django.contrib.sessions.backends.db import SessionStore

        user = make_user("good@falcon.test", email_verified=False, is_active=False)
        OTPRecord.objects.create(
            user=user,
            otp_code="555666",
            purpose=OTPRecord.PURPOSE_REGISTRATION,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        c = Client()
        store = SessionStore()
        store["pending_verification"] = {
            "user_id": user.id,
            "purpose": OTPRecord.PURPOSE_REGISTRATION,
        }
        store.save()
        c.cookies[dj_settings.SESSION_COOKIE_NAME] = store.session_key
        c.post(reverse("accounts:verify_otp"), {"otp_code": "555666"}, follow=True)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.email_verified)


class AuthPortalTests(TestCase):
    def test_public_login_blocks_staff_roles(self):
        make_user("staff@falcon.test", FalconUser.ROLE_MANAGER)
        r = self.client.post(
            reverse("accounts:login"),
            {"email": "staff@falcon.test", "password": "Passw0rd!123"},
            follow=True,
        )
        self.assertIn("staff portal", r.content.decode().lower())

    def test_public_login_success_redirects_to_role_home(self):
        u = make_user("cust@falcon.test", email_verified=True)
        r = self.client.post(
            reverse("accounts:login"),
            {"email": "cust@falcon.test", "password": "Passw0rd!123"},
        )
        self.assertRedirects(r, "/customer/dashboard/", fetch_redirect_response=False)

    def test_disabled_account_cannot_log_in(self):
        make_user("off@falcon.test", email_verified=True, is_active=False)
        r = self.client.post(
            reverse("accounts:login"),
            {"email": "off@falcon.test", "password": "Passw0rd!123"},
            follow=True,
        )
        self.assertIn("disabled", r.content.decode().lower())


class CheckAPITests(TestCase):
    def test_check_email_exists(self):
        make_user("taken@falcon.test")
        r = self.client.get(reverse("accounts:check_email"), {"email": "taken@falcon.test"})
        self.assertTrue(r.json()["exists"])

    def test_check_email_free(self):
        r = self.client.get(reverse("accounts:check_email"), {"email": "free@falcon.test"})
        self.assertFalse(r.json()["exists"])

    def test_check_username_case_insensitive(self):
        VendorProfile.objects.create(user=make_user("v@falcon.test"), username="CoolVendor")
        r = self.client.get(reverse("accounts:check_username"), {"username": "coolvendor"})
        self.assertEqual(r.json(), {"exists": True})


class ManagerUserManagementTests(TestCase):
    def setUp(self):
        self.manager = make_user("mgr@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("ops@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("ven@falcon.test", FalconUser.ROLE_VENDOR)
        self.customer = make_user("cus@falcon.test", FalconUser.ROLE_CUSTOMER)

    def test_manager_lists_users_with_search_and_role_filter(self):
        c = Client(); c.force_login(self.manager)
        r = c.get(reverse("manager_users"), {"q": "ven@"})
        self.assertContains(r, "ven@falcon.test")
        self.assertNotContains(r, "cus@falcon.test")
        r = c.get(reverse("manager_users"), {"role": "customer"})
        self.assertContains(r, "cus@falcon.test")

    def test_toggle_disables_then_enables_with_audit(self):
        from apps.audit.models import AuditLog

        c = Client(); c.force_login(self.manager)
        c.post(reverse("manager_user_toggle", args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertFalse(self.customer.is_active)
        self.assertTrue(
            AuditLog.objects.filter(action="user_disabled", affected_object_id=self.customer.pk).exists()
        )
        c.post(reverse("manager_user_toggle", args=[self.customer.pk]))
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)

    def test_manager_cannot_disable_self(self):
        c = Client(); c.force_login(self.manager)
        c.post(reverse("manager_user_toggle", args=[self.manager.pk]), follow=True)
        self.manager.refresh_from_db()
        self.assertTrue(self.manager.is_active)

    def test_delete_last_superuser_blocked(self):
        self.manager.is_superuser = True
        self.manager.save()
        c = Client(); c.force_login(self.manager)
        c.post(reverse("manager_user_delete", args=[self.manager.pk]), follow=True)
        self.assertTrue(FalconUser.objects.filter(pk=self.manager.pk).exists())

    def test_sub_manager_can_view_but_not_post(self):
        c = Client(); c.force_login(self.sub)
        r = c.get(reverse("manager_users"))
        self.assertEqual(r.status_code, 200)
        r = c.post(reverse("manager_user_toggle", args=[self.customer.pk]))
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse("manager_user_delete", args=[self.customer.pk]))
        self.assertEqual(r.status_code, 403)

    def test_vendor_cannot_access_user_management(self):
        c = Client(); c.force_login(self.vendor)
        for url in (
            reverse("manager_users"),
            reverse("manager_user_toggle", args=[self.customer.pk]),
        ):
            r = c.get(url) if url.endswith("users/") else c.post(url)
            self.assertEqual(r.status_code, 403, url)
