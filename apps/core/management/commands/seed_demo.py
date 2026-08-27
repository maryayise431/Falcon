from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.models import (
    CustomerProfile,
    DeliveryAgentProfile,
    FalconUser,
    VendorProfile,
)
from apps.core.utils import calculate_settlement, generate_reference
from apps.core.models import Warehouse
from apps.delivery.models import DeliveryAssignment
from apps.marketplace.models import (
    MarketplaceOrder,
    MarketplaceOrderItem,
    MarketplacePayment,
    MarketplaceProduct,
    ProductCategory,
)
from apps.parcel.models import ParcelRequest
from apps.vendor.models import (
    VendorFulfillmentOrder,
    VendorProduct,
    VendorWallet,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)

PASSWORD = "Falcon#2026"


class Command(BaseCommand):
    help = "Seed the database with demo users and data for every role."

    def add_arguments(self, parser):
        parser.add_argument("--flush", action="store_true", help="Delete existing demo data first")

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()

        now = timezone.now()

        manager = (
            FalconUser.objects.filter(role=FalconUser.ROLE_MANAGER, is_active=True)
            .order_by("date_joined")
            .first()
        )
        sub = FalconUser.objects.filter(role=FalconUser.ROLE_SUB_MANAGER).first()
        agent_users = [
            (profile, profile.user)
            for profile in DeliveryAgentProfile.objects.select_related("user").filter(
                user__is_active=True
            )
        ]
        if manager is None:
            self.stdout.write(
                self.style.WARNING(
                    "No active manager account. Staff accounts are managed "
                    "exclusively at /admin/. Seeding vendors & customers only."
                )
            )
        vendors = []
        for v_idx, (email, business, username) in enumerate([
            ("vendor1@falcon.test", "Kola Collections", "kolacollections"),
            ("vendor2@falcon.test", "Zara Fabrics", "zarafabrics"),
        ]):
            user = self._user(email, FalconUser.ROLE_VENDOR, email_verified=True)
            profile, _ = VendorProfile.objects.get_or_create(
                user=user,
                defaults={
                    "business_name": business,
                    "username": username,
                    "contact_name": business,
                    "phone_number": "0812000000%d" % (v_idx + 3),
                    "is_verified": True,
                },
            )
            wallet, _ = VendorWallet.objects.get_or_create(vendor=user, defaults={"balance": Decimal("0")})
            vendors.append((user, profile, wallet))

        customers = []
        for c_idx, (email, name) in enumerate([("ada@falcon.test", "Ada Obi"), ("musa@falcon.test", "Musa Danjuma")]):
            user = self._user(email, FalconUser.ROLE_CUSTOMER, email_verified=True)
            CustomerProfile.objects.get_or_create(user=user, defaults={"full_name": name, "phone_number": "0706000000%d" % (c_idx + 5)})
            customers.append(user)

        wh_ikeja, _ = Warehouse.objects.get_or_create(
            code="WH-IKJ",
            defaults={"name": "Ikeja Hub", "address": "12 Obafemi Awolowo Way, Ikeja", "city": "Lagos", "state": "Lagos"},
        )
        wh_yaba, _ = Warehouse.objects.get_or_create(
            code="WH-YBA",
            defaults={"name": "Yaba Depot", "address": "5 Herbert Macaulay Way, Yaba", "city": "Lagos", "state": "Lagos"},
        )

        cat_fashion, _ = ProductCategory.objects.get_or_create(name="Fashion")
        cat_gadgets, _ = ProductCategory.objects.get_or_create(name="Gadgets")
        cat_electronics, _ = ProductCategory.objects.get_or_create(name="Electronics")
        cat_home, _ = ProductCategory.objects.get_or_create(name="Home & Kitchen")
        cat_beauty, _ = ProductCategory.objects.get_or_create(name="Beauty & Health")
        cat_sports, _ = ProductCategory.objects.get_or_create(name="Sports & Outdoors")
        cat_books, _ = ProductCategory.objects.get_or_create(name="Books & Stationery")
        cat_food, _ = ProductCategory.objects.get_or_create(name="Food & Groceries")
        cat_automotive, _ = ProductCategory.objects.get_or_create(name="Automotive")
        cat_agriculture, _ = ProductCategory.objects.get_or_create(name="Agriculture")

        mp_products = []
        for idx, (name, price, stock, category) in enumerate([
            ("Ankara Tote Bag", 12500, 40, cat_fashion),
            ("Handwoven Agbada Set", 45000, 15, cat_fashion),
            ("Solar Power Bank 20k", 21000, 30, cat_gadgets),
            ("Wireless Earbuds Pro", 18000, 50, cat_gadgets),
        ]):
            product, created = MarketplaceProduct.objects.get_or_create(
                name=name,
                defaults={"price": price, "stock": stock, "category": category, "is_published": True, "created_by": manager},
            )
            mp_products.append(product)

        vendor_products = {}
        vp_prices = [[Decimal("15000"), Decimal("22000")], [Decimal("18500"), Decimal("9750")]]
        for i, (vendor_user, _, _) in enumerate(vendors):
            for j in range(2):
                name = f"{vendor_users_business(vendors[i][1])} Bulk Item {j + 1}"
                vp, _ = VendorProduct.objects.get_or_create(
                    vendor=vendor_user,
                    name=name,
                    defaults={
                        "warehouse": [wh_ikeja, wh_yaba][(i + j) % 2],
                        "price": vp_prices[i][j],
                        "quantity_received": 100,
                        "quantity_available": 80 - j * 10,
                        "status": VendorProduct.STATUS_RECEIVED,
                        "received_at": now - timedelta(days=10 - j),
                    },
                )
                vendor_products.setdefault(i, []).append(vp)

        fee = Decimal("2500")
        cod_values = [Decimal("18500"), Decimal("32000"), Decimal("9750"), Decimal("46000")]

        delivered_specs = [
            (0, 0, customers[0], 6, True),
            (0, 1, customers[1], 4, True),
            (1, 0, customers[0], 2, True),
            (1, 1, customers[1], 1, False),
        ]
        for v_idx, p_idx, customer, days_ago, confirmed in delivered_specs:
            vendor_user, _, wallet = vendors[v_idx]
            vp = vendor_products[v_idx][p_idx]
            order = VendorFulfillmentOrder.objects.create(
                vendor=vendor_user,
                product=vp,
                product_name=vp.name,
                warehouse=vp.warehouse,
                quantity=1,
                customer_name=customer.customerprofile.full_name,
                customer_phone=customer.customerprofile.phone_number,
                customer_address=f"{14 + days_ago} Allen Avenue, Ikeja, Lagos",
                cod_amount=cod_values[(v_idx + p_idx) % len(cod_values)],
                delivery_fee=fee,
                status=VendorFulfillmentOrder.STATUS_DELIVERED,
            )
            order.created_at = now - timedelta(days=days_ago)
            order.save(update_fields=["created_at"])
            if not agent_users:
                continue
            agent_profile, agent_user = agent_users[(v_idx + p_idx) % len(agent_users)]
            assignment = DeliveryAssignment.objects.create(
                order=order,
                agent=agent_profile,
                assigned_by=manager,
                status=DeliveryAssignment.STATUS_DELIVERED,
                cod_collected=order.cod_amount,
                cod_confirmed=confirmed,
                delivered_at=now - timedelta(days=days_ago, hours=-2),
            )
            settlement = calculate_settlement(order.cod_amount, fee)
            self._wallet_tx(wallet, VendorWalletTransaction.TYPE_CREDIT, settlement["wallet_credit"], order, manager, f"COD settled for {order.order_reference}", when=assignment.delivered_at)
            self._wallet_tx(wallet, VendorWalletTransaction.TYPE_DELIVERY_FEE, -settlement["fee_debit"], order, manager, f"Delivery fee for {order.order_reference}", when=assignment.delivered_at)

        active_specs = [
            (0, VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY, customers[1], 0),
            (1, VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT, customers[0], 1),
            (1, VendorFulfillmentOrder.STATUS_PENDING, customers[1], 0),
        ]
        for v_idx, status, customer, p_idx in active_specs:
            vendor_user, _, _ = vendors[v_idx]
            vp = vendor_products[v_idx][p_idx]
            order = VendorFulfillmentOrder.objects.create(
                vendor=vendor_user,
                product=vp,
                product_name=vp.name,
                warehouse=vp.warehouse,
                quantity=1,
                customer_name=customer.customerprofile.full_name,
                customer_phone=customer.customerprofile.phone_number,
                customer_address="7 Adeola Odeku Street, Victoria Island, Lagos",
                cod_amount=cod_values[p_idx],
                delivery_fee=fee,
                status=status,
            )
            if status == VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY and agent_users:
                agent_profile, _ = agent_users[v_idx % len(agent_users)]
                DeliveryAssignment.objects.create(
                    order=order,
                    agent=agent_profile,
                    assigned_by=manager,
                    status=DeliveryAssignment.STATUS_OUT_FOR_DELIVERY,
                )

        marketplace_order = MarketplaceOrder.objects.create(
            customer=customers[0],
            total_amount=mp_products[0].price + mp_products[2].price,
            delivery_address="22 Awolowo Road, Ikoyi, Lagos",
            receiver_phone="07060000005",
            status=MarketplaceOrder.STATUS_PROCESSING,
        )
        MarketplaceOrderItem.objects.create(order=marketplace_order, product=mp_products[0], product_name=mp_products[0].name, quantity=1, unit_price=mp_products[0].price)
        MarketplaceOrderItem.objects.create(order=marketplace_order, product=mp_products[2], product_name=mp_products[2].name, quantity=1, unit_price=mp_products[2].price)
        payment = MarketplacePayment.objects.create(order=marketplace_order, amount=marketplace_order.total_amount, simulated=True)
        payment.mark_paid()

        parcel_paid = ParcelRequest.objects.create(
            requested_by=customers[1],
            sender_name=customers[1].customerprofile.full_name,
            sender_phone=customers[1].customerprofile.phone_number,
            receiver_name="Ngozi Ade",
            receiver_phone="09090000001",
            receiver_address="3 Ahmadu Bello Way, Abuja",
            parcel_description="Sealed documents envelope",
            delivery_fee=Decimal("5500"),
            status=ParcelRequest.STATUS_IN_TRANSIT,
        )
        parcel_paid.mark_paid(reference="SIM-" + generate_reference("PS"), simulated=True)
        if agent_users:
            DeliveryAssignment.objects.create(parcel=parcel_paid, agent=agent_users[0][0], assigned_by=manager, status=DeliveryAssignment.STATUS_OUT_FOR_DELIVERY)

        ParcelRequest.objects.get_or_create(
            requested_by=customers[0],
            sender_name=customers[0].customerprofile.full_name,
            sender_phone=customers[0].customerprofile.phone_number,
            receiver_name="Bola Tinuke",
            receiver_phone="09090000002",
            receiver_address="18 Ring Road, Ibadan",
            parcel_description="Small carton of fabrics",
            defaults={"status": ParcelRequest.STATUS_PENDING},
        )

        w1 = VendorWithdrawalRequest.objects.create(
            vendor=vendors[0][0],
            amount_requested=Decimal("20000"),
            withdrawal_charge=Decimal("200"),
            amount_transferred=Decimal("19800"),
            bank_name="GTBank",
            account_number="0123456789",
            account_name="KOLA COLLECTIONS LTD",
            status=VendorWithdrawalRequest.STATUS_COMPLETED,
            processed_at=now - timedelta(days=3),
            processed_by=manager,
            simulated=True,
        )
        w1.requested_at = now - timedelta(days=4)
        w1.save(update_fields=["requested_at"])
        wallet0 = vendors[0][2]
        self._wallet_tx(wallet0, VendorWalletTransaction.TYPE_WITHDRAWAL, -Decimal("19800"), None, manager, "Payout to GTBank", when=w1.requested_at)
        self._wallet_tx(wallet0, VendorWalletTransaction.TYPE_WITHDRAWAL_FEE, -Decimal("200"), None, manager, "Withdrawal charge", when=w1.requested_at)
        wallet0.balance = sum(tx.amount for tx in wallet0.transactions.all())
        wallet0.save(update_fields=["balance"])
        VendorWithdrawalRequest.objects.create(
            vendor=vendors[1][0],
            amount_requested=Decimal("15000"),
            withdrawal_charge=Decimal("150"),
            amount_transferred=Decimal("14850"),
            bank_name="Access Bank",
            account_number="0987654321",
            account_name="ZARA FABRICS ENT",
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded (customers & vendors). Password: %s" % PASSWORD))
        if manager is None or not agent_users:
            self.stdout.write("Staff accounts are managed exclusively at http://localhost:8000/admin/.")

    def _flush(self):
        DeliveryAssignment.objects.all().delete()
        VendorWalletTransaction.objects.all().delete()
        VendorWithdrawalRequest.objects.all().delete()
        VendorFulfillmentOrder.objects.all().delete()
        VendorProduct.objects.all().delete()
        MarketplacePayment.objects.all().delete()
        MarketplaceOrderItem.objects.all().delete()
        MarketplaceOrder.objects.all().delete()
        MarketplaceProduct.objects.all().delete()
        ProductCategory.objects.all().delete()
        Warehouse.objects.all().delete()
        ParcelRequest.objects.all().delete()
        from apps.accounts.models import CustomerProfile, VendorProfile
        CustomerProfile.objects.all().delete()
        VendorProfile.objects.all().delete()
        VendorWallet.objects.all().delete()
        FalconUser.objects.filter(email__endswith="@falcon.test").exclude(
            role__in=FalconUser.STAFF_ROLES
        ).delete()

    def _user(self, email, role, **extra):
        defaults = {"role": role, "email_verified": True}
        defaults.update(extra)
        user, created = FalconUser.objects.get_or_create(email=email, defaults=defaults)
        if created:
            user.set_password(PASSWORD)
            user.save(update_fields=["password"])
        return user

    def _wallet_tx(self, wallet, tx_type, amount, related_order, created_by, reason, when=None):
        previous = wallet.balance
        wallet.balance = previous + amount
        wallet.save(update_fields=["balance"])
        tx = VendorWalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=tx_type,
            amount=amount,
            previous_balance=previous,
            new_balance=wallet.balance,
            reason=reason,
            created_by=created_by,
            related_order=related_order,
        )
        if when:
            tx.created_at = when
            tx.save(update_fields=["created_at"])
        return tx


def vendor_users_business(profile):
    return profile.business_name
