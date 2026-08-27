from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import FalconUser
from apps.audit.models import AuditLog
from apps.audit.services import log_action


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


class LogActionTests(TestCase):
    def test_log_action_records_actor_target_and_description(self):
        actor = make_user("al@falcon.test", FalconUser.ROLE_MANAGER)
        target = make_user("at@falcon.test", FalconUser.ROLE_VENDOR)
        req = type("R", (), {"user": actor, "META": {"REMOTE_ADDR": "127.0.0.1"}})()
        entry = log_action(req, "vendor_approved", target, description="approved vendor")
        self.assertEqual(entry.actor_id, actor.id)
        self.assertEqual(entry.affected_object_id, target.id)
        self.assertEqual(entry.affected_model, "FalconUser")
        self.assertIn("approved vendor", entry.description)

    def test_long_description_truncated(self):
        actor = make_user("al2@falcon.test", FalconUser.ROLE_MANAGER)
        req = type("R", (), {"user": actor, "META": {}})()
        entry = log_action(req, "login_as_role", description="x" * 500)
        self.assertLessEqual(len(entry.description), 255)


class AuditViewAccessTests(TestCase):
    def setUp(self):
        self.manager = make_user("am@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("as@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("av@falcon.test", FalconUser.ROLE_VENDOR)
        AuditLog.objects.create(actor=self.manager, action="login_as_role")

    def test_manager_and_sub_can_view_trail(self):
        for u in (self.manager, self.sub):
            c = Client(); c.force_login(u)
            r = c.get(reverse("audit:list"))
            self.assertEqual(r.status_code, 200)

    def test_vendor_blocked_from_audit(self):
        c = Client(); c.force_login(self.vendor)
        r = c.get(reverse("audit:list"))
        self.assertEqual(r.status_code, 403)

    def test_anonymous_redirects_to_login(self):
        r = Client().get(reverse("audit:list"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r["Location"])
