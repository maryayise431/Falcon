from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import FalconUser
from apps.marketplace.models import MarketplaceProduct, ProductCategory
from apps.marketplace.services import (
    add_to_cart,
    build_cart_context,
    place_order,
    set_cart_quantity,
)


def make_user(email, role=FalconUser.ROLE_CUSTOMER, **kw):
    return FalconUser.objects.create_user(
        email=email, password="Passw0rd!123", role=role, **kw
    )


def make_product(name="Widget", price="2500.00", stock=10, published=True):
    return MarketplaceProduct.objects.create(
        name=name,
        price=Decimal(price),
        stock=stock,
        is_published=published,
    )


class CatalogTests(TestCase):
    def test_unpublished_product_hidden_from_detail(self):
        p = make_product(published=False)
        url = reverse("marketplace:product_detail", args=[p.slug])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 404)

        p.is_published = True
        p.save()
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)

    def test_marketplace_search_and_category_filter(self):
        cat = ProductCategory.objects.create(name="Gadgets", icon="ri-rocket-fill")
        a = make_product(name="Blue Widget")
        b = make_product(name="Red Gismo")
        a.category = cat
        a.save()

        r = self.client.get(reverse("marketplace:home"), {"q": "widget"})
        self.assertContains(r, "Blue Widget")
        self.assertNotContains(r, "Red Gismo")

        r = self.client.get(reverse("marketplace:home"), {"category": "gadgets"})
        self.assertContains(r, "Blue Widget")
        self.assertNotContains(r, "Red Gismo")


class CartFlowTests(TestCase):
    def test_add_to_cart_caps_at_stock(self):
        p = make_product(stock=3)
        session = self.client.session
        add_to_cart(session, str(p.id), 5)
        session.save()
        cart = build_cart_context(session)
        self.assertEqual(cart["entries"][0]["quantity"], 3)
        self.assertEqual(cart["total"], p.price * 3)

    def test_set_quantity_to_zero_removes_item(self):
        p = make_product()
        session = self.client.session
        add_to_cart(session, str(p.id), 2)
        set_cart_quantity(session, str(p.id), 0)
        cart = build_cart_context(session)
        self.assertEqual(cart["entries"], [])

    def test_stale_or_unpublished_items_dropped(self):
        p1 = make_product(name="Live", published=True)
        p2 = make_product(name="Ghost", published=False)
        session = self.client.session
        add_to_cart(session, str(p1.id), 1)
        add_to_cart(session, str(p2.id), 2)
        add_to_cart(session, "999999", 1)  # nonexistent
        cart = build_cart_context(session)
        self.assertEqual([e["product"].pk for e in cart["entries"]], [p1.pk])

    def test_cart_http_flow_add_update_remove(self):
        p = make_product(stock=10)
        r = self.client.post(
            reverse("marketplace:cart"),
            {"action": "add", "product_id": p.pk, "quantity": "2"},
        )
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse("marketplace:cart"))
        self.assertContains(r, p.name)

        self.client.post(
            reverse("marketplace:cart"),
            {"action": "update", "product_id": p.pk, "quantity": "4"},
        )
        cart = build_cart_context(self.client.session)
        self.assertEqual(cart["entries"][0]["quantity"], 4)

        self.client.post(
            reverse("marketplace:cart"), {"action": "remove", "product_id": p.pk}
        )
        cart = build_cart_context(self.client.session)
        self.assertEqual(cart["entries"], [])

    def test_place_order_creates_order_with_items(self):
        buyer = make_user("buyer@falcon.test", email_verified=True)
        p1 = make_product(name="Item A", price="1000.00", stock=5)
        p2 = make_product(name="Item B", price="2500.00", stock=5)
        session = self.client.session
        add_to_cart(session, str(p1.pk), 2)   # 2000
        add_to_cart(session, str(p2.pk), 1)   # 2500
        cart = build_cart_context(session)
        order, payment = place_order(
            customer=buyer,
            cart_data=cart,
            delivery_address="12 Test Street",
            receiver_phone="08000000000",
        )
        self.assertEqual(order.total_amount, Decimal("4500"))
        item_names = sorted(order.items.values_list("product_name", flat=True))
        self.assertEqual(item_names, ["Item A", "Item B"])
        self.assertIsNotNone(payment)


class PublishPermissionTests(TestCase):
    def setUp(self):
        self.manager = make_user("m@falcon.test", FalconUser.ROLE_MANAGER)
        self.sub = make_user("s@falcon.test", FalconUser.ROLE_SUB_MANAGER)
        self.vendor = make_user("v@falcon.test", FalconUser.ROLE_VENDOR)
        self.product = make_product(published=False)

    def test_only_manager_can_publish(self):
        c = Client(); c.force_login(self.sub)
        r = c.post(reverse("marketplace:manager_product_publish", args=[self.product.pk]))
        self.assertEqual(r.status_code, 403)

        c = Client(); c.force_login(self.vendor)
        r = c.post(reverse("marketplace:manager_product_publish", args=[self.product.pk]))
        self.assertEqual(r.status_code, 403)

        c = Client(); c.force_login(self.manager)
        r = c.post(reverse("marketplace:manager_product_publish", args=[self.product.pk]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_published)

    def test_vendor_cannot_reach_manager_views(self):
        c = Client(); c.force_login(self.vendor)
        for url in (
            reverse("marketplace:manager_products"),
            reverse("marketplace:manager_orders"),
        ):
            r = c.get(url)
            self.assertEqual(r.status_code, 403, url)
