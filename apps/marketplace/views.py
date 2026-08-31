import logging
from decimal import Decimal

import django.db.models as dm

logger = logging.getLogger("falcon.marketplace")

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView, TemplateView, View

from apps.accounts.views import role_home
from apps.audit.services import log_action
from apps.core.mixins import CustomerRequiredMixin, ManagerRequiredMixin
from apps.core.models import save_quantity_prices
from apps.core.paystack import (
    PaystackError,
    initialize_transaction,
    verify_transaction,
)
from apps.parcel.models import ParcelRequest

from .forms import CheckoutForm, MarketplaceProductForm
from .models import (
    MarketplaceOrder,
    MarketplacePayment,
    MarketplaceProduct,
    ProductCategory,
    ProductImage,
)
from .services import (
    add_to_cart,
    build_cart_context,
    cancel_order,
    clear_cart,
    fail_order_payment,
    finalize_paid_order,
    place_order,
    save_cart,
    set_cart_quantity,
)

STATUS_TRANSITIONS = {
    MarketplaceOrder.STATUS_PENDING: [
        MarketplaceOrder.STATUS_PROCESSING,
        MarketplaceOrder.STATUS_CANCELLED,
    ],
    MarketplaceOrder.STATUS_AWAITING_FEE: [
        MarketplaceOrder.STATUS_PROCESSING,
        MarketplaceOrder.STATUS_CANCELLED,
    ],
    MarketplaceOrder.STATUS_PROCESSING: [
        MarketplaceOrder.STATUS_OUT_FOR_DELIVERY,
        MarketplaceOrder.STATUS_CANCELLED,
    ],
    MarketplaceOrder.STATUS_OUT_FOR_DELIVERY: [
        MarketplaceOrder.STATUS_DELIVERED,
        MarketplaceOrder.STATUS_FAILED,
    ],
    MarketplaceOrder.STATUS_DELIVERED: [],
    MarketplaceOrder.STATUS_FAILED: [],
    MarketplaceOrder.STATUS_CANCELLED: [],
}

AGENT_MANAGED_STATUSES = {
    MarketplaceOrder.STATUS_PROCESSING,
    MarketplaceOrder.STATUS_OUT_FOR_DELIVERY,
    MarketplaceOrder.STATUS_DELIVERED,
    MarketplaceOrder.STATUS_FAILED,
}


class MarketplaceHomeView(ListView):
    template_name = "marketplace/home.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        qs = MarketplaceProduct.objects.filter(is_published=True).select_related(
            "category"
        )
        query = self.request.GET.get("q", "").strip()
        category_slug = self.request.GET.get("category", "").strip()
        if query:
            qs = qs.filter(dm.Q(name__icontains=query) | dm.Q(description__icontains=query))
        if category_slug:
            qs = qs.filter(category__slug=category_slug)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categories"] = ProductCategory.objects.all()
        ctx["active_category"] = self.request.GET.get("category", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class ProductDetailView(DetailView):
    template_name = "marketplace/product_detail.html"
    context_object_name = "product"
    slug_url_kwarg = "slug"

    def get_queryset(self):
        return MarketplaceProduct.objects.filter(is_published=True)


class CartView(View):
    def get(self, request):
        cart = build_cart_context(request.session)
        return render(request, "marketplace/cart.html", {"cart": cart})

    def post(self, request):
        action = request.POST.get("action", "add")
        if action == "add":
            try:
                product_id = int(request.POST.get("product_id"))
                quantity = max(1, int(request.POST.get("quantity", 1)))
            except (TypeError, ValueError):
                messages.error(request, "Invalid product selection.")
                return redirect("marketplace:home")
            product = MarketplaceProduct.objects.filter(
                id=product_id, is_published=True
            ).first()
            if not product or product.stock < 1:
                messages.error(request, "That product is unavailable.")
                return redirect("marketplace:home")
            quantity = min(quantity, product.stock)
            add_to_cart(request.session, product_id, quantity)
            messages.success(request, f"{product.name} added to your cart.")
            source = request.POST.get("next")
            if source == "cart":
                return redirect("marketplace:cart")
            if source == "home":
                return redirect("marketplace:home")
            return redirect("marketplace:cart")
        if action == "update":
            try:
                product_id = str(int(request.POST.get("product_id")))
                quantity = int(request.POST.get("quantity", 1))
            except (TypeError, ValueError):
                quantity = 0
                product_id = ""
            if product_id:
                set_cart_quantity(request.session, product_id, quantity)
            return redirect("marketplace:cart")
        if action == "remove":
            product_id = request.POST.get("product_id", "")
            if product_id:
                set_cart_quantity(request.session, product_id, 0)
            return redirect("marketplace:cart")
        if action == "clear":
            clear_cart(request.session)
            return redirect("marketplace:cart")
        return redirect("marketplace:cart")


class CheckoutView(CustomerRequiredMixin, FormView):
    template_name = "marketplace/checkout.html"
    form_class = CheckoutForm

    def get_initial(self):
        initial = super().get_initial()
        profile = getattr(self.request.user, "customerprofile", None)
        if profile:
            initial["receiver_phone"] = profile.phone_number
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["cart"] = build_cart_context(self.request.session)
        from apps.core.models import Warehouse
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx

    def post(self, request, *args, **kwargs):
        cart = build_cart_context(request.session)
        if not cart["entries"]:
            messages.warning(request, "Your cart is empty.")
            return redirect("marketplace:home")
        form = self.form_class(request.POST)
        if not form.is_valid():
            ctx = self.get_context_data(form=form)
            ctx["cart"] = cart
            return self.render_to_response(ctx)
        method = form.cleaned_data["delivery_method"]
        lat = form.cleaned_data.get("delivery_address_lat")
        lng = form.cleaned_data.get("delivery_address_lng")
        order, payment = place_order(
            customer=request.user,
            cart_data=cart,
            delivery_address=form.cleaned_data.get("delivery_address", ""),
            receiver_phone=form.cleaned_data.get("receiver_phone", ""),
            lat=lat,
            lng=lng,
            delivery_method=method,
            pickup_warehouse=form.cleaned_data.get("pickup_warehouse"),
        )
        clear_cart(request.session)
        if method == "pickup":
            callback_url = request.build_absolute_uri(reverse("marketplace:paystack_callback"))
            try:
                result = initialize_transaction(
                    email=order.customer.email,
                    amount_naira=float(order.total_amount),
                    reference=f"{order.order_reference}-{int(timezone.now().timestamp())}",
                    callback_url=callback_url,
                    metadata={"order_reference": order.order_reference},
                )
            except PaystackError as exc:
                logger.exception("Paystack init failed for %s", order.order_reference)
                fail_order_payment(order)
                messages.error(request, f"Payment could not be started ({exc}). Please try again.")
                return redirect("marketplace:cart")
            payment.paystack_reference = result["reference"]
            if result["authorization_url"]:
                payment.save(update_fields=["paystack_reference"])
                return redirect(result["authorization_url"])
            payment.save(update_fields=["paystack_reference"])
            finalize_paid_order(order, simulated=True)
            messages.success(request, "Order placed! Payment confirmed in dev mode.")
            return redirect("marketplace:order_confirmation", ref=order.order_reference)
        else:
            order.status = MarketplaceOrder.STATUS_AWAITING_FEE
            order.save(update_fields=["status", "updated_at"])
            messages.success(
                request,
                f"Order {order.order_reference} created. A manager will add the delivery fee shortly. "
                f"You can pay once the fee is set.",
            )
            return redirect("marketplace:order_confirmation", ref=order.order_reference)


def paystack_callback(request):
    reference = request.GET.get("reference", "")
    payment = MarketplacePayment.objects.filter(paystack_reference=reference).first()
    if payment is None:
        messages.error(request, "Unknown payment reference.")
        return redirect("marketplace:home")
    order = payment.order
    if order.customer_id != request.user.id:
        raise PermissionDenied("You cannot view this order.")
    try:
        verification = verify_transaction(reference)
    except PaystackError as exc:
        logger.exception("Paystack verify failed for %s", reference)
        messages.error(request, f"We could not confirm your payment ({exc}).")
        return redirect("marketplace:order_confirmation", ref=order.order_reference)
    if verification["success"]:
        expected_kobo = int(order.total_amount * 100)
        actual = verification.get("amount_kobo")
        if not verification.get("simulated") and actual is not None and int(actual) < expected_kobo:
            fail_order_payment(order)
            messages.error(request, "Payment amount mismatch. Contact support.")
        else:
            finalize_paid_order(
                order, paystack_reference=reference, simulated=verification.get("simulated", False)
            )
            messages.success(request, "Payment confirmed! Your order is being processed.")
    else:
        fail_order_payment(order)
        messages.error(request, "Payment was not successful. You can retry checkout.")
    return redirect("marketplace:order_confirmation", ref=order.order_reference)


class OrderConfirmationView(CustomerRequiredMixin, TemplateView):
    template_name = "marketplace/order_confirmation.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = get_object_or_404(
            MarketplaceOrder.objects.select_related("payment"),
            order_reference=self.kwargs["ref"],
            customer=self.request.user,
        )
        ctx["order"] = order
        return ctx


class CancelOrderView(CustomerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(
            MarketplaceOrder, order_reference=ref, customer=request.user
        )
        try:
            cancel_order(order)
            log_action(
                request,
                "order_status_changed",
                order,
                description=f"Customer cancelled order {order.order_reference}",
                new_value={"status": order.status},
            )
            messages.success(request, "Order cancelled.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("marketplace:order_confirmation", ref=ref)


class CustomerDashboardView(CustomerRequiredMixin, TemplateView):
    template_name = "marketplace/customer_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        orders = MarketplaceOrder.objects.filter(customer=user)
        ctx["total_orders"] = orders.count()
        ctx["delivered_orders"] = orders.filter(status="delivered").count()
        ctx["active_orders"] = orders.exclude(
            status__in=["delivered", "failed", "cancelled"]
        ).count()
        ctx["parcels_sent"] = ParcelRequest.objects.filter(requested_by=user).count()
        ctx["recent_orders"] = orders[:6]
        return ctx


class CustomerOrderListView(CustomerRequiredMixin, ListView):
    template_name = "marketplace/customer_orders.html"
    context_object_name = "orders"
    paginate_by = 15

    def get_queryset(self):
        qs = MarketplaceOrder.objects.filter(customer=self.request.user).select_related("pickup_warehouse")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["status_choices"] = MarketplaceOrder.STATUS_CHOICES
        return ctx


class CustomerHistoryView(CustomerRequiredMixin, TemplateView):
    template_name = "marketplace/customer_history.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        ctx["orders"] = MarketplaceOrder.objects.filter(customer=user)[:50]
        ctx["parcels"] = ParcelRequest.objects.filter(requested_by=user)[:50]
        return ctx


class CustomerParcelRedirectView(CustomerRequiredMixin, View):
    def get(self, request):
        return redirect("parcel:history")


class ManagerProductListView(ManagerRequiredMixin, ListView):
    template_name = "marketplace/manager_products.html"
    context_object_name = "products"
    paginate_by = 20

    def get_queryset(self):
        qs = MarketplaceProduct.objects.all().select_related("category")
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(name__icontains=query)
        state = self.request.GET.get("state", "")
        if state == "published":
            qs = qs.filter(is_published=True)
        elif state == "draft":
            qs = qs.filter(is_published=False)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class ManagerProductCreateView(ManagerRequiredMixin, FormView):
    template_name = "marketplace/manager_product_form.html"
    form_class = MarketplaceProductForm
    success_url = reverse_lazy("marketplace:manager_products")

    def get(self, request, *args, **kwargs):
        self._ensure_default_categories()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        self._ensure_default_categories()
        form = self.form_class(request.POST)
        files = request.FILES.getlist("images")
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.save()
            save_quantity_prices(
                product,
                request.POST.getlist("qp_qty"),
                request.POST.getlist("qp_price"),
            )
            for f in files[:8]:
                img = ProductImage.objects.create(image=f, alt=product.name)
                product.images.add(img)
            log_action(
                request,
                "product_created",
                product,
                description=f"Created product {product.name}",
                new_value={"name": product.name, "price": str(product.price), "stock": product.stock},
            )
            messages.success(request, f"Product '{product.name}' created.")
            return redirect(self.success_url)
        return self.render_to_response(self.get_context_data(form=form))

    @staticmethod
    def _ensure_default_categories():
        from .models import ProductCategory
        DEFAULT_CATEGORIES = [
            ("Fashion", "ri-shirt-line"),
            ("Gadgets", "ri-smartphone-line"),
            ("Electronics", "ri-computer-line"),
            ("Home & Kitchen", "ri-home-heart-line"),
            ("Beauty & Health", "ri-heart-pulse-line"),
            ("Sports & Outdoors", "ri-basketball-line"),
            ("Books & Stationery", "ri-book-open-line"),
            ("Food & Groceries", "ri-restaurant-line"),
            ("Automotive", "ri-car-line"),
            ("Agriculture", "ri-plant-line"),
        ]
        for name, icon in DEFAULT_CATEGORIES:
            ProductCategory.objects.get_or_create(name=name, defaults={"icon": icon})


class ManagerProductUpdateView(ManagerRequiredMixin, View):
    template_name = "marketplace/manager_product_form.html"

    def get(self, request, pk):
        product = get_object_or_404(
            MarketplaceProduct.objects.prefetch_related("quantity_prices"), pk=pk
        )
        form = MarketplaceProductForm(instance=product)
        return render(
            request, self.template_name, {"form": form, "product": product}
        )

    def post(self, request, pk):
        product = get_object_or_404(MarketplaceProduct, pk=pk)
        previous = {"price": str(product.price), "stock": product.stock}
        form = MarketplaceProductForm(request.POST, instance=product)
        files = request.FILES.getlist("images")
        if form.is_valid():
            product = form.save(commit=False)
            product.save()
            save_quantity_prices(
                product,
                request.POST.getlist("qp_qty"),
                request.POST.getlist("qp_price"),
            )
            for f in files[:8]:
                img = ProductImage.objects.create(image=f, alt=product.name)
                product.images.add(img)
            log_action(
                request,
                "product_updated",
                product,
                description=f"Updated product {product.name}",
                previous_value=previous,
                new_value={"is_published": product.is_published, "price": str(product.price), "stock": product.stock},
            )
            messages.success(request, "Product updated.")
            return redirect("marketplace:manager_products")
        return render(request, self.template_name, {"form": form, "product": product})


class ManagerProductDeleteView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(MarketplaceProduct, pk=pk)
        name = product.name
        pid = product.id
        product.delete()
        log_action(
            request,
            "product_deleted",
            None,
            description=f"Deleted product '{name}' (#{pid})",
        )
        messages.success(request, f"Product '{name}' deleted.")
        return redirect("marketplace:manager_products")


class ManagerProductPublishView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(MarketplaceProduct, pk=pk)
        product.is_published = not product.is_published
        product.save(update_fields=["is_published"])
        action = "product_published" if product.is_published else "product_unpublished"
        log_action(
            request,
            action,
            product,
            description=f"'{product.name}' {'published' if product.is_published else 'unpublished'}",
        )
        state = "published" if product.is_published else "unpublished"
        messages.success(request, f"'{product.name}' is now {state}.")
        return redirect("marketplace:manager_products")


class ManagerOrdersView(ManagerRequiredMixin, ListView):
    template_name = "marketplace/manager_orders.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = MarketplaceOrder.objects.select_related("payment").order_by("-created_at")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(order_reference__icontains=query)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class ManagerOrderDetailView(ManagerRequiredMixin, DetailView):
    template_name = "marketplace/manager_order_detail.html"
    context_object_name = "order"

    def get_object(self):
        return get_object_or_404(
            MarketplaceOrder.objects.select_related(
                "payment", "customer", "pickup_warehouse",
            ).prefetch_related("assignments__agent"),
            order_reference=self.kwargs["ref"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        from apps.delivery.models import DeliveryAssignment
        from apps.accounts.models import DeliveryAgentProfile
        assignment = order.assignments.select_related("agent").first()
        ctx["assignment"] = assignment
        ctx["agents"] = DeliveryAgentProfile.objects.select_related("user").filter(
            user__is_active=True,
        )
        allowed = STATUS_TRANSITIONS.get(order.status, [])
        ctx["allowed_transitions"] = MarketplaceOrder.STATUS_CHOICES
        ctx["allowed_statuses"] = [
            (value, label)
            for value, label in MarketplaceOrder.STATUS_CHOICES
            if value in allowed
        ]
        ctx["items"] = order.items.all()
        return ctx


class ManagerOrderStatusView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(
            MarketplaceOrder.objects.prefetch_related("assignments__agent"),
            order_reference=ref,
        )
        new_status = request.POST.get("status", "")
        reason = request.POST.get("reason", "").strip()
        allowed = STATUS_TRANSITIONS.get(order.status, [])
        from apps.core.utils import is_final_status

        if is_final_status(order.status) and not request.user.is_superuser:
            messages.error(
                request, "Delivered and failed orders are locked and cannot change."
            )
            return redirect("marketplace:manager_order_detail", ref=ref)
        if new_status not in allowed:
            messages.error(
                request, f"Cannot move an order from '{order.status}' to '{new_status}'."
            )
            return redirect("marketplace:manager_order_detail", ref=ref)
        previous = {"status": order.status}
        order.status = new_status
        order.updated_at = timezone.now()
        save_fields = ["status", "updated_at"]
        if new_status == MarketplaceOrder.STATUS_DELIVERED:
            order.delivered_at = timezone.now()
            save_fields.append("delivered_at")
        order.save(update_fields=save_fields)
        if new_status in (MarketplaceOrder.STATUS_OUT_FOR_DELIVERY, MarketplaceOrder.STATUS_DELIVERED, MarketplaceOrder.STATUS_FAILED):
            from apps.delivery.models import DeliveryAssignment
            assignment = order.assignments.first()
            if assignment:
                status_map = {
                    MarketplaceOrder.STATUS_OUT_FOR_DELIVERY: DeliveryAssignment.STATUS_OUT_FOR_DELIVERY,
                    MarketplaceOrder.STATUS_DELIVERED: DeliveryAssignment.STATUS_DELIVERED,
                    MarketplaceOrder.STATUS_FAILED: DeliveryAssignment.STATUS_FAILED,
                }
                assignment.status = status_map[new_status]
                assign_fields = ["status"]
                if new_status == MarketplaceOrder.STATUS_DELIVERED:
                    assignment.delivered_at = timezone.now()
                    assign_fields.append("delivered_at")
                if reason:
                    assignment.delivery_notes = reason
                    assign_fields.append("delivery_notes")
                assignment.save(update_fields=assign_fields)
        log_action(
            request,
            "order_status_changed",
            order,
            description=f"Marketplace order {order.order_reference}: {previous['status']} -> {new_status}",
            previous_value=previous,
            new_value={"status": new_status},
            reason=reason,
        )
        messages.success(request, f"Order marked as {order.get_status_display()}.")
        return redirect("marketplace:manager_order_detail", ref=ref)


class ManagerSetDeliveryFeeView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(MarketplaceOrder, order_reference=ref)
        if order.status != MarketplaceOrder.STATUS_AWAITING_FEE:
            messages.error(request, "This order is not awaiting a delivery fee.")
            return redirect("marketplace:manager_order_detail", ref=ref)
        fee_str = request.POST.get("delivery_fee", "").strip()
        try:
            fee = Decimal(fee_str)
            if fee < 0:
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, "Please enter a valid delivery fee (>= 0).")
            return redirect("marketplace:manager_order_detail", ref=ref)
        order.delivery_fee = fee
        order.delivery_fee_set_at = timezone.now()
        order.total_amount = order.items.aggregate(
            total=dm.Sum(dm.Coalesce(dm.F("line_total"), dm.F("unit_price") * dm.F("quantity")))
        )["total"] + fee
        order.save(update_fields=["delivery_fee", "delivery_fee_set_at", "total_amount", "updated_at"])
        log_action(
            request,
            "order_delivery_fee_set",
            order,
            description=f"Delivery fee ₦{fee:.2f} set on {order.order_reference}",
            new_value={"delivery_fee": str(fee), "total_amount": str(order.total_amount)},
        )
        messages.success(request, f"Delivery fee ₦{fee:.2f} set. Total is now ₦{order.total_amount:.2f}.")
        return redirect("marketplace:manager_order_detail", ref=ref)


class CustomerPayOrderView(CustomerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(
            MarketplaceOrder, order_reference=ref, customer=request.user,
        )
        if order.status != MarketplaceOrder.STATUS_AWAITING_FEE:
            messages.error(request, "This order is not awaiting payment.")
            return redirect("marketplace:order_confirmation", ref=ref)
        if not order.delivery_fee_set_at:
            messages.error(request, "Please wait for a manager to set the delivery fee.")
            return redirect("marketplace:order_confirmation", ref=ref)
        payment = MarketplacePayment.objects.filter(order=order).first()
        if not payment:
            payment = MarketplacePayment.objects.create(order=order, amount=order.total_amount)
        else:
            payment.amount = order.total_amount
            payment.status = MarketplacePayment.STATUS_PENDING
            payment.save(update_fields=["amount", "status"])
        callback_url = request.build_absolute_uri(reverse("marketplace:paystack_callback"))
        try:
            result = initialize_transaction(
                email=order.customer.email,
                amount_naira=float(order.total_amount),
                reference=f"{order.order_reference}-{int(timezone.now().timestamp())}",
                callback_url=callback_url,
                metadata={"order_reference": order.order_reference},
            )
        except PaystackError as exc:
            logger.exception("Paystack init failed for %s", order.order_reference)
            fail_order_payment(order)
            messages.error(request, f"Payment could not be started ({exc}). Please try again.")
            return redirect("marketplace:order_confirmation", ref=ref)
        payment.paystack_reference = result["reference"]
        if result["authorization_url"]:
            payment.save(update_fields=["paystack_reference"])
            return redirect(result["authorization_url"])
        payment.save(update_fields=["paystack_reference"])
        finalize_paid_order(order, simulated=True)
        messages.success(request, "Payment confirmed in dev mode.")
        return redirect("marketplace:order_confirmation", ref=order.order_reference)


class ManagerAssignMarketplaceAgentView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(MarketplaceOrder, order_reference=ref)
        if order.status not in ("processing", "awaiting_assignment"):
            messages.error(request, f"Cannot assign agent to a '{order.status}' order.")
            return redirect("marketplace:manager_order_detail", ref=ref)
        agent_id = request.POST.get("agent_id", "").strip()
        if not agent_id:
            messages.error(request, "Please select a delivery agent.")
            return redirect("marketplace:manager_order_detail", ref=ref)
        from apps.accounts.models import DeliveryAgentProfile
        from apps.delivery.models import DeliveryAssignment
        agent = DeliveryAgentProfile.objects.filter(id=agent_id, user__is_active=True).first()
        if not agent:
            messages.error(request, "Invalid agent selected.")
            return redirect("marketplace:manager_order_detail", ref=ref)
        assignment, _ = DeliveryAssignment.objects.update_or_create(
            marketplace_order=order,
            defaults={
                "agent": agent,
                "assigned_by": request.user,
                "status": DeliveryAssignment.STATUS_ASSIGNED,
            },
        )
        order.status = "processing"
        order.save(update_fields=["status", "updated_at"])
        log_action(
            request,
            "order_agent_assigned",
            order,
            description=f"Agent {agent.full_name} assigned to {order.order_reference}",
            new_value={"agent": agent.full_name, "assignment_id": assignment.id},
        )
        messages.success(request, f"{agent.full_name} assigned to {order.order_reference}.")
        return redirect("marketplace:manager_order_detail", ref=ref)


class ManagerDispatchMarketplaceView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(MarketplaceOrder, order_reference=ref)
        from apps.delivery.models import DeliveryAssignment
        assignment = DeliveryAssignment.objects.filter(marketplace_order=order).first()
        if not assignment:
            messages.error(request, "No agent assigned to this order.")
            return redirect("marketplace:manager_order_detail", ref=ref)
        assignment.status = DeliveryAssignment.STATUS_ASSIGNED
        assignment.save(update_fields=["status"])
        log_action(
            request,
            "order_dispatched",
            order,
            description=f"Dispatch approved for {order.order_reference}",
            new_value={"status": "dispatched"},
        )
        messages.success(request, f"{order.order_reference} dispatched. Agent can now pick up.")
        return redirect("marketplace:manager_order_detail", ref=ref)
