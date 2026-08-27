from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

import django.db.models as dm

from apps.accounts.models import FalconUser
from apps.audit.services import log_action
from apps.core.mixins import (
    AgentRequiredMixin,
    CustomerRequiredMixin,
    ManagerOrSubManagerMixin,
    ManagerRequiredMixin,
    ReadOnlySubManagerMixin,
    RoleRequiredMixin,
    VendorRequiredMixin,
)
from apps.accounts.models import DeliveryAgentProfile
from apps.delivery.models import DeliveryAssignment

from .forms import (
    BankAccountForm,
    ManagerDeductWalletForm,
    ManagerDeliveryFeeForm,
    VendorOrderForm,
    VendorProductForm,
    WithdrawalForm,
)
from .models import (
    VendorFulfillmentOrder,
    VendorProduct,
    VendorWallet,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)
from .services import (
    approve_withdrawal,
    credit_wallet,
    debit_wallet,
    deduct_order_stock,
    get_or_create_wallet,
    request_withdrawal,
    settle_cod_delivery,
    transition_order,
)

ACTIVE_VENDOR_STATUSES = [
    VendorFulfillmentOrder.STATUS_PENDING,
    VendorFulfillmentOrder.STATUS_PROCESSING,
    VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT,
    VendorFulfillmentOrder.STATUS_ASSIGNED,
    VendorFulfillmentOrder.STATUS_APPROVED,
    VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY,
]


class VendorDashboardView(VendorRequiredMixin, TemplateView):
    template_name = "vendor/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        orders = VendorFulfillmentOrder.objects.filter(vendor=user)
        wallet = get_or_create_wallet(user)
        ctx["wallet"] = wallet
        ctx["active_orders"] = orders.filter(status__in=ACTIVE_VENDOR_STATUSES).count()
        ctx["delivered_orders"] = orders.filter(status="delivered").count()
        ctx["failed_orders"] = orders.filter(status="failed").count()
        cod_delivered = (
            orders.filter(status="delivered").aggregate(t=Sum("cod_amount"))["t"] or 0
        )
        ctx["cod_delivered"] = cod_delivered
        ctx["recent_orders"] = orders[:8]
        ctx["recent_transactions"] = wallet.transactions.all()[:6]
        ctx["pending_withdrawals"] = VendorWithdrawalRequest.objects.filter(
            vendor=user, status__in=["pending", "approved"]
        ).exists()
        return ctx


class VendorProductListView(VendorRequiredMixin, ListView):
    template_name = "vendor/inventory.html"
    context_object_name = "products"
    paginate_by = 15

    def get_queryset(self):
        qs = VendorProduct.objects.filter(vendor=self.request.user).select_related("warehouse")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(name__icontains=query)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class VendorProductCreateView(VendorRequiredMixin, FormView):
    template_name = "vendor/inventory_form.html"
    form_class = VendorProductForm
    success_url = reverse_lazy("vendor:inventory")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method == "POST":
            kwargs["files"] = self.request.FILES
        return kwargs

    def form_valid(self, form):
        product = form.save(commit=False)
        product.vendor = self.request.user
        product.save()
        log_action(
            self.request,
            "product_created",
            product,
            description=f"Vendor submitted '{product.name}' ({product.quantity_available} units) for warehousing",
        )
        messages.success(
            self.request,
            f"'{product.name}' registered. Falcon will confirm receipt at the warehouse.",
        )
        return redirect(self.success_url)


class VendorOrderListView(VendorRequiredMixin, ListView):
    template_name = "vendor/orders.html"
    context_object_name = "orders"
    paginate_by = 15

    def get_queryset(self):
        qs = VendorFulfillmentOrder.objects.filter(vendor=self.request.user).select_related(
            "product", "assigned_agent"
        )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(dm.Q(order_reference__icontains=query) | dm.Q(customer_name__icontains=query))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class VendorOrderCreateView(VendorRequiredMixin, FormView):
    template_name = "vendor/order_form.html"
    form_class = VendorOrderForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["vendor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        product = form.cleaned_data["product"]
        quantity = form.cleaned_data["quantity"]
        if quantity > product.quantity_available:
            form.add_error(
                "quantity",
                f"Only {product.quantity_available} unit(s) available in the warehouse.",
            )
            return self.form_invalid(form)
        order = VendorFulfillmentOrder.objects.create(
            vendor=self.request.user,
            product=product,
            product_name=product.name,
            warehouse=product.warehouse,
            quantity=quantity,
            customer_name=form.cleaned_data["customer_name"],
            customer_phone=form.cleaned_data["customer_phone"],
            customer_whatsapp=form.cleaned_data.get("customer_whatsapp", ""),
            customer_address=form.cleaned_data["customer_address"],
            customer_address_lat=form.cleaned_data.get("customer_address_lat") or None,
            customer_address_lng=form.cleaned_data.get("customer_address_lng") or None,
            cod_amount=product.price * quantity,
            delivery_instructions=form.cleaned_data.get("delivery_instructions", ""),
        )
        deduct_order_stock(order)
        log_action(
            self.request,
            "order_created",
            order,
            description=f"Vendor order {order.order_reference}: {quantity} x {product.name}, COD \u20a6{order.cod_amount}",
            new_value={"status": order.status, "cod": str(order.cod_amount)},
        )
        messages.success(
            self.request,
            f"Order {order.order_reference} submitted! Track it publicly at /track/{order.order_reference}",
        )
        return redirect("vendor:order_detail", ref=order.order_reference)


class VendorOrderDetailView(VendorRequiredMixin, DetailView):
    template_name = "vendor/order_detail.html"
    context_object_name = "order"

    def get_object(self):
        return get_object_or_404(
            VendorFulfillmentOrder.objects.select_related(
                "product", "assigned_agent", "warehouse", "assigned_agent__user"
            ),
            order_reference=self.kwargs["ref"],
            vendor=self.request.user,
        )


class VendorWalletView(VendorRequiredMixin, TemplateView):
    template_name = "vendor/wallet.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        wallet = get_or_create_wallet(self.request.user)
        ctx["wallet"] = wallet
        ctx["transactions"] = wallet.transactions.select_related("related_order")[:50]
        credits = wallet.transactions.filter(transaction_type="credit").aggregate(
            t=Sum("amount")
        )["t"] or Decimal(0)
        fees = wallet.transactions.filter(
            transaction_type__in=["delivery_fee", "manual_deduction"]
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0)
        withdrawn = wallet.transactions.filter(
            transaction_type="withdrawal"
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0)
        charges = wallet.transactions.filter(
            transaction_type="withdrawal_fee"
        ).aggregate(t=Sum("amount"))["t"] or Decimal(0)
        ctx["summary"] = {
            "credits": credits,
            "fees": fees,
            "withdrawn": withdrawn,
            "charges": charges,
        }
        profile = getattr(self.request.user, "vendorprofile", None)
        ctx["bank_ready"] = bool(profile and profile.bank_verified)
        return ctx


class VendorWithdrawalRequestView(VendorRequiredMixin, View):
    template_name = "vendor/withdraw.html"

    def get(self, request):
        wallet = get_or_create_wallet(request.user)
        profile = request.user.vendorprofile
        form = WithdrawalForm()
        return render(
            request,
            self.template_name,
            {"form": form, "wallet": wallet, "profile": profile, "bank_ready": profile.bank_verified},
        )

    def post(self, request):
        wallet = get_or_create_wallet(request.user)
        profile = request.user.vendorprofile
        form = WithdrawalForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"form": form, "wallet": wallet, "profile": profile, "bank_ready": profile.bank_verified},
            )
        try:
            withdrawal = request_withdrawal(request.user, form.cleaned_data["amount"], profile)
        except ValueError as exc:
            form.add_error(None, str(exc))
            return render(
                request,
                self.template_name,
                {"form": form, "wallet": wallet, "profile": profile},
            )
        log_action(
            request,
            "withdrawal_requested",
            withdrawal,
            description=f"Withdrawal of \u20a6{withdrawal.amount_requested} requested",
        )
        messages.success(
            request,
            f"Withdrawal request for \u20a6{withdrawal.amount_transferred} (after \u20a6{withdrawal.withdrawal_charge} charge) submitted.",
        )
        return redirect("vendor:withdrawals")


class VendorWithdrawalHistoryView(VendorRequiredMixin, ListView):
    template_name = "vendor/withdrawals.html"
    context_object_name = "withdrawals"
    paginate_by = 15

    def get_queryset(self):
        return VendorWithdrawalRequest.objects.filter(vendor=self.request.user)


class VendorProfileView(VendorRequiredMixin, TemplateView):
    template_name = "vendor/profile.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = self.request.user
        profile = user.vendorprofile
        wallet = get_or_create_wallet(user)
        orders = VendorFulfillmentOrder.objects.filter(vendor=user)
        ctx["profile"] = profile
        ctx["wallet_balance"] = wallet.balance
        ctx["total_orders"] = orders.count()
        ctx["delivered_orders"] = orders.filter(status="delivered").count()
        return ctx


class VendorBankAccountView(VendorRequiredMixin, View):
    template_name = "vendor/bank_account.html"

    def get(self, request):
        profile = request.user.vendorprofile
        form = BankAccountForm(
            initial={
                "bank_name": profile.bank_name,
                "bank_code": profile.bank_code,
                "account_number": profile.bank_account_number,
                "account_name": profile.account_name,
            }
        )
        from apps.core.paystack import list_banks

        return render(
            request,
            self.template_name,
            {"form": form, "profile": profile, "banks": list_banks()},
        )

    def post(self, request):
        profile = request.user.vendorprofile
        form = BankAccountForm(request.POST)
        if form.is_valid():
            previous = {
                "bank_name": profile.bank_name,
                "account_number": profile.bank_account_number,
                "verified": profile.bank_verified,
            }
            form.save(profile)
            log_action(
                request,
                "bank_details_updated",
                profile,
                description=f"Bank account updated ({profile.bank_name} {profile.bank_account_number})",
                previous_value=previous,
                new_value={"bank_name": profile.bank_name, "verified": True},
            )
            messages.success(request, "Bank account saved and verified.")
            return redirect("vendor:bank")
        from apps.core.paystack import list_banks

        return render(
            request,
            self.template_name,
            {"form": form, "profile": profile, "banks": list_banks()},
        )


def api_banks(request):
    if not request.user.is_authenticated:
        return JsonResponse({"banks": []}, status=403)
    from apps.core.paystack import list_banks

    return JsonResponse({"banks": list_banks()})


def api_verify_bank(request):
    if not request.user.is_authenticated or request.user.role != FalconUser.ROLE_VENDOR:
        return JsonResponse(
            {"verified": False, "error": "Vendor authentication required."}, status=403
        )
    account_number = (request.GET.get("account_number") or "").strip()
    bank_code = (request.GET.get("bank_code") or "").strip()
    if not account_number or not bank_code:
        return JsonResponse(
            {"verified": False, "error": "account_number and bank_code are required."},
            status=400,
        )
    from apps.core.paystack import resolve_bank_account

    result = resolve_bank_account(account_number, bank_code)
    return JsonResponse(result)


class ManagerVendorListView(ManagerOrSubManagerMixin, ListView):
    template_name = "manager/vendor_list.html"
    context_object_name = "vendors"
    paginate_by = 20

    def get_queryset(self):
        return (
            FalconUser.objects.filter(role=FalconUser.ROLE_VENDOR)
            .select_related("vendorprofile", "wallet")
            .order_by("-date_joined")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        query = self.request.GET.get("q", "").strip()
        products = VendorProduct.objects.select_related(
            "vendor", "vendor__vendorprofile", "warehouse", "assigned_agent__user"
        ).order_by("-created_at")
        if query:
            products = products.filter(
                dm.Q(name__icontains=query)
                | dm.Q(vendor__email__icontains=query)
                | dm.Q(vendor__vendorprofile__business_name__icontains=query)
            )
        ctx["search_query"] = query
        ctx["products"] = products
        from apps.accounts.models import DeliveryAgentProfile
        ctx["agents"] = DeliveryAgentProfile.objects.select_related("user").filter(user__is_active=True)
        from apps.core.models import Warehouse
        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        return ctx

    def post(self, request):
        action = request.POST.get("action")
        product_id = request.POST.get("product_id")
        product = get_object_or_404(VendorProduct, id=product_id)

        if action == "assign_agent" and request.user.role in ("manager", "sub_manager"):
            from apps.accounts.models import DeliveryAgentProfile
            agent_id = request.POST.get("agent_id")
            agent = DeliveryAgentProfile.objects.filter(id=agent_id).select_related("warehouse", "user").first() if agent_id else None
            product.assigned_agent = agent
            if agent and agent.warehouse:
                product.warehouse = agent.warehouse
            elif agent is None:
                product.warehouse = None
            product.save(update_fields=["assigned_agent", "warehouse"])
            label = (agent.full_name or agent.user.email) if agent else "unassigned"
            wh_label = agent.warehouse.name if agent and agent.warehouse else "cleared"
            messages.success(request, f"'{product.name}' → Agent: {label}, Warehouse: {wh_label}.")
            return redirect("vendor:manager_vendors")

        if request.user.role != FalconUser.ROLE_MANAGER:
            raise PermissionDenied("Only Managers can confirm stock receipt.")
        warehouse_id = request.POST.get("warehouse")
        from apps.core.models import Warehouse
        warehouse = Warehouse.objects.filter(id=warehouse_id).first()
        if not warehouse:
            messages.error(request, "Choose a warehouse to receive the stock into.")
            return redirect("vendor:manager_vendors")
        product.warehouse = warehouse
        product.status = VendorProduct.STATUS_RECEIVED
        product.quantity_received = product.quantity_available
        product.received_at = timezone.now()
        product.save(update_fields=["warehouse", "status", "quantity_received", "received_at"])
        log_action(
            request,
            "order_status_changed",
            product,
            description=f"Stock received: {product.quantity_available} x '{product.name}' at {warehouse.name}",
            new_value={"status": "received", "warehouse": warehouse.code},
        )
        messages.success(request, f"'{product.name}' received at {warehouse.name}.")
        return redirect("vendor:manager_vendors")


class ManagerProductDetailView(ManagerOrSubManagerMixin, View):
    template_name = "manager/vendor_product_detail.html"

    def get(self, request, product_id):
        product = get_object_or_404(
            VendorProduct.objects.select_related(
                "vendor", "vendor__vendorprofile", "warehouse",
                "assigned_agent__user", "assigned_agent__warehouse",
            ),
            id=product_id,
        )
        from apps.accounts.models import DeliveryAgentProfile
        agents = DeliveryAgentProfile.objects.select_related("user", "warehouse").filter(user__is_active=True)
        from apps.core.models import Warehouse
        warehouses = Warehouse.objects.filter(is_active=True)
        return render(request, self.template_name, {
            "product": product,
            "agents": agents,
            "warehouses": warehouses,
        })

    def post(self, request, product_id):
        product = get_object_or_404(VendorProduct, id=product_id)
        action = request.POST.get("action")

        if action == "assign_agent" and request.user.role in ("manager", "sub_manager"):
            from apps.accounts.models import DeliveryAgentProfile
            agent_id = request.POST.get("agent_id")
            agent = DeliveryAgentProfile.objects.filter(id=agent_id).select_related("warehouse", "user").first() if agent_id else None
            product.assigned_agent = agent
            if agent and agent.warehouse:
                product.warehouse = agent.warehouse
            elif agent is None:
                product.warehouse = None
            product.save(update_fields=["assigned_agent", "warehouse"])
            label = (agent.full_name or agent.user.email) if agent else "unassigned"
            wh_label = agent.warehouse.name if agent and agent.warehouse else "cleared"
            messages.success(request, f"'{product.name}' → Agent: {label}, Warehouse: {wh_label}.")
            return redirect("vendor:manager_vendors")

        if action == "receive_stock" and request.user.role == "manager":
            from apps.core.models import Warehouse
            warehouse_id = request.POST.get("warehouse")
            warehouse = Warehouse.objects.filter(id=warehouse_id).first()
            if not warehouse:
                messages.error(request, "Choose a warehouse to receive the stock into.")
                return redirect("vendor:manager_product_detail", product_id=product.id)
            product.warehouse = warehouse
            product.status = VendorProduct.STATUS_RECEIVED
            product.quantity_received = product.quantity_available
            product.received_at = timezone.now()
            product.save(update_fields=["warehouse", "status", "quantity_received", "received_at"])
            log_action(
                request,
                "order_status_changed",
                product,
                description=f"Stock received: {product.quantity_available} x '{product.name}' at {warehouse.name}",
                new_value={"status": "received", "warehouse": warehouse.code},
            )
            messages.success(request, f"'{product.name}' received at {warehouse.name}.")
            return redirect("vendor:manager_vendors")

        return redirect("vendor:manager_product_detail", product_id=product.id)


class ManagerProductDeleteView(ManagerOrSubManagerMixin, View):
    def post(self, request, product_id):
        product = get_object_or_404(VendorProduct, id=product_id)
        name = product.name
        product.delete()
        messages.success(request, f"'{name}' deleted.")
        return redirect("vendor:manager_vendors")


class ManagerVendorProductsView(ManagerOrSubManagerMixin, TemplateView):
    template_name = "manager/vendor_inventory.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        vendor = get_object_or_404(
            FalconUser, id=self.kwargs["vendor_id"], role=FalconUser.ROLE_VENDOR
        )
        ctx["vendor"] = vendor
        products = VendorProduct.objects.filter(vendor=vendor).select_related("warehouse", "assigned_agent__user")
        ctx["products"] = products
        from apps.core.models import Warehouse
        from apps.accounts.models import DeliveryAgentProfile

        ctx["warehouses"] = Warehouse.objects.filter(is_active=True)
        ctx["agents"] = DeliveryAgentProfile.objects.select_related("user").filter(user__is_active=True)
        return ctx

    def post(self, request, vendor_id):
        action = request.POST.get("action")
        product = get_object_or_404(VendorProduct, id=request.POST.get("product_id"))

        if action == "assign_agent" and request.user.role in ("manager", "sub_manager"):
            from apps.accounts.models import DeliveryAgentProfile

            agent_id = request.POST.get("agent_id")
            agent = DeliveryAgentProfile.objects.filter(id=agent_id).select_related("warehouse", "user").first() if agent_id else None
            product.assigned_agent = agent
            if agent and agent.warehouse:
                product.warehouse = agent.warehouse
            elif agent is None:
                product.warehouse = None
            product.save(update_fields=["assigned_agent", "warehouse"])
            label = (agent.full_name or agent.user.email) if agent else "unassigned"
            wh_label = agent.warehouse.name if agent and agent.warehouse else "cleared"
            messages.success(request, f"'{product.name}' → Agent: {label}, Warehouse: {wh_label}.")
            return redirect("vendor:manager_vendor_inventory", vendor_id=vendor_id)

        if request.user.role != FalconUser.ROLE_MANAGER:
            raise PermissionDenied("Only Managers can confirm stock receipt.")
        warehouse_id = request.POST.get("warehouse")
        from apps.core.models import Warehouse

        warehouse = Warehouse.objects.filter(id=warehouse_id).first()
        if not warehouse:
            messages.error(request, "Choose a warehouse to receive the stock into.")
            return redirect("vendor:manager_vendor_inventory", vendor_id=product.vendor_id)
        product.warehouse = warehouse
        product.status = VendorProduct.STATUS_RECEIVED
        product.quantity_received = product.quantity_available
        product.received_at = timezone.now()
        product.save(update_fields=["warehouse", "status", "quantity_received", "received_at"])
        log_action(
            request,
            "order_status_changed",
            product,
            description=f"Stock received: {product.quantity_available} x '{product.name}' at {warehouse.name}",
            new_value={"status": "received", "warehouse": warehouse.code},
        )
        messages.success(request, f"'{product.name}' received at {warehouse.name}.")
        return redirect("vendor:manager_vendor_inventory", vendor_id=product.vendor_id)


class ManagerVendorOrderListView(ManagerOrSubManagerMixin, ListView):
    template_name = "manager/vendor_orders.html"
    context_object_name = "orders"
    paginate_by = 20

    def get_queryset(self):
        qs = VendorFulfillmentOrder.objects.select_related(
            "vendor", "product", "assigned_agent"
        )
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                dm.Q(order_reference__icontains=query)
                | dm.Q(customer_name__icontains=query)
                | dm.Q(vendor__email__icontains=query)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["status_choices"] = VendorFulfillmentOrder.STATUS_CHOICES
        return ctx


class ManagerVendorOrderDetailView(ReadOnlySubManagerMixin, DetailView):
    template_name = "manager/vendor_order_detail.html"
    context_object_name = "order"

    def get_object(self):
        return get_object_or_404(
            VendorFulfillmentOrder.objects.select_related(
                "vendor",
                "vendor__wallet",
                "product",
                "warehouse",
                "assigned_agent",
                "assigned_agent__user",
                "approved_by",
            ),
            order_reference=self.kwargs["ref"],
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        from apps.accounts.models import DeliveryAgentProfile

        ctx["agents"] = DeliveryAgentProfile.objects.select_related("user").filter(
            user__is_active=True
        )
        ctx["fee_form"] = ManagerDeliveryFeeForm(
            initial={"delivery_fee": order.delivery_fee}
        )
        ctx["is_manager"] = self.request.user.role == FalconUser.ROLE_MANAGER
        ctx["assignment"] = DeliveryAssignment.objects.filter(order=order).first()
        return ctx


def _manager_guard(request):
    if request.user.role != FalconUser.ROLE_MANAGER:
        raise PermissionDenied("Only Managers can perform this action.")


class ManagerProcessOrderView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(VendorFulfillmentOrder, order_reference=ref)
        try:
            previous = order.status
            transition_order(order, VendorFulfillmentOrder.STATUS_PROCESSING)
            log_action(request, "order_status_changed", order,
                       description=f"{ref}: {previous} -> processing",
                       previous_value={"status": previous}, new_value={"status": order.status})
            messages.success(request, "Order marked as processing.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerApproveOrderView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(VendorFulfillmentOrder, order_reference=ref)
        form = ManagerDeliveryFeeForm(request.POST)
        if not form.is_valid():
            messages.error(request, "; ".join(form.errors.get("delivery_fee", ["Invalid fee."])))
            return redirect("vendor:manager_vendor_order_detail", ref=ref)
        fee = form.cleaned_data["delivery_fee"]
        previous = {"status": order.status, "delivery_fee": str(order.delivery_fee)}
        try:
            if order.status != VendorFulfillmentOrder.STATUS_PROCESSING:
                raise ValueError(f"Cannot approve an order in '{order.status}' state.")
            order.delivery_fee = fee
            order.approved_by = request.user
            order.approved_at = timezone.now()
            if order.product and order.product.assigned_agent:
                order.assigned_agent = order.product.assigned_agent
                order.status = VendorFulfillmentOrder.STATUS_APPROVED
                order.save(update_fields=["delivery_fee", "approved_by", "approved_at", "status", "assigned_agent", "updated_at"])
                DeliveryAssignment.objects.get_or_create(
                    order=order,
                    defaults={
                        "agent": order.product.assigned_agent,
                        "assigned_by": request.user,
                        "status": DeliveryAssignment.STATUS_ASSIGNED,
                    },
                )
            else:
                order.status = VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT
                order.save(update_fields=["delivery_fee", "approved_by", "approved_at", "status", "updated_at"])
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("vendor:manager_vendor_order_detail", ref=ref)
        log_action(
            request,
            "order_approved",
            order,
            description=f"Approved with delivery fee \u20a6{fee}",
            previous_value=previous,
            new_value={"status": order.status, "delivery_fee": str(fee)},
        )
        if order.assigned_agent:
            messages.success(request, f"Order approved and auto-assigned to {order.assigned_agent.full_name}. Delivery fee \u20a6{fee}.")
        else:
            messages.success(request, f"Order approved. Delivery fee set to \u20a6{fee}. Assign an agent manually.")
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerAssignAgentView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(VendorFulfillmentOrder, order_reference=ref)
        agent_id = request.POST.get("agent_id")
        agent = get_object_or_404(DeliveryAgentProfile, id=agent_id)
        allowed_from = [
            VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT,
            VendorFulfillmentOrder.STATUS_ASSIGNED,
        ]
        if order.status not in allowed_from:
            messages.error(request, f"Cannot assign an agent to a '{order.status}' order.")
            return redirect("vendor:manager_vendor_order_detail", ref=ref)
        previous_agent = order.assigned_agent
        order.assigned_agent = agent
        if order.status == VendorFulfillmentOrder.STATUS_AWAITING_ASSIGNMENT:
            order.status = VendorFulfillmentOrder.STATUS_APPROVED
        order.save(update_fields=["assigned_agent", "status", "updated_at"])
        assignment, _ = DeliveryAssignment.objects.get_or_create(
            order=order,
            defaults={
                "agent": agent,
                "assigned_by": request.user,
                "status": DeliveryAssignment.STATUS_ASSIGNED,
            },
        )
        if assignment.agent_id != agent.id:
            assignment.agent = agent
            assignment.assigned_by = request.user
            assignment.status = DeliveryAssignment.STATUS_ASSIGNED
            assignment.save(update_fields=["agent", "assigned_by", "status"])
        log_action(
            request,
            "agent_assigned",
            order,
            description=f"{ref}: assigned {agent.full_name} (was {previous_agent or 'unassigned'})",
            previous_value={"agent": str(previous_agent)},
            new_value={"agent": agent.full_name, "status": order.status},
        )
        messages.success(request, f"Assigned to {agent.full_name}.")
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerDispatchOrderView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(VendorFulfillmentOrder, order_reference=ref)
        if not order.assigned_agent:
            messages.error(request, "Assign an agent before dispatch approval.")
            return redirect("vendor:manager_vendor_order_detail", ref=ref)
        try:
            previous = order.status
            transition_order(order, VendorFulfillmentOrder.STATUS_APPROVED)
            DeliveryAssignment.objects.filter(order=order).update(
                status=DeliveryAssignment.STATUS_ASSIGNED
            )
            log_action(request, "order_approved", order,
                       description=f"{ref}: dispatch approved ({previous} -> approved)",
                       previous_value={"status": previous}, new_value={"status": order.status})
            messages.success(request, "Dispatch approved. The agent can now pick up the parcel.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerCancelOrderView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        order = get_object_or_404(VendorFulfillmentOrder, order_reference=ref)
        reason = request.POST.get("reason", "").strip() or "Cancelled by manager"
        try:
            previous = order.status
            transition_order(order, VendorFulfillmentOrder.STATUS_CANCELLED)
            if order.product is not None:
                product = order.product
                product.quantity_available += order.quantity
                if product.status == VendorProduct.STATUS_DEPLETED:
                    product.status = VendorProduct.STATUS_RECEIVED
                product.save(update_fields=["quantity_available", "status"])
            DeliveryAssignment.objects.filter(order=order).update(
                status="failed", delivery_notes=reason
            )
            log_action(request, "order_status_changed", order,
                       description=f"{ref}: cancelled - {reason}",
                       previous_value={"status": previous}, new_value={"status": "cancelled"}, reason=reason)
            messages.success(request, "Order cancelled and stock restored.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerCreateVendorOrderView(ManagerRequiredMixin, FormView):
    template_name = "manager/vendor_order_form.html"
    form_class = VendorOrderForm
    success_url = reverse_lazy("vendor:manager_vendor_orders")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        vendor_id = self.request.GET.get("vendor") or self.request.POST.get("vendor_hidden")
        vendor = None
        if vendor_id:
            vendor = FalconUser.objects.filter(id=vendor_id, role=FalconUser.ROLE_VENDOR).first()
        kwargs["vendor"] = vendor
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendors"] = FalconUser.objects.filter(role=FalconUser.ROLE_VENDOR)
        ctx["selected_vendor"] = self.request.GET.get("vendor", "")
        return ctx

    def form_valid(self, form):
        product = form.cleaned_data["product"]
        vendor = product.vendor
        quantity = form.cleaned_data["quantity"]
        if quantity > product.quantity_available:
            form.add_error("quantity", f"Only {product.quantity_available} unit(s) available.")
            return self.form_invalid(form)
        order = VendorFulfillmentOrder.objects.create(
            vendor=vendor,
            product=product,
            product_name=product.name,
            warehouse=product.warehouse,
            quantity=quantity,
            customer_name=form.cleaned_data["customer_name"],
            customer_phone=form.cleaned_data["customer_phone"],
            customer_whatsapp=form.cleaned_data.get("customer_whatsapp", ""),
            customer_address=form.cleaned_data["customer_address"],
            customer_address_lat=form.cleaned_data.get("customer_address_lat") or None,
            customer_address_lng=form.cleaned_data.get("customer_address_lng") or None,
            cod_amount=product.price * quantity,
            delivery_instructions=form.cleaned_data.get("delivery_instructions", ""),
            created_by_manager=True,
            status=VendorFulfillmentOrder.STATUS_PROCESSING,
        )
        deduct_order_stock(order)
        log_action(
            self.request,
            "order_created",
            order,
            description=f"Manager created order {order.order_reference} for {vendor.email}",
            new_value={"status": order.status},
        )
        messages.success(self.request, f"Order {order.order_reference} created.")
        return redirect(self.success_url)


class ManagerVendorWalletView(ReadOnlySubManagerMixin, TemplateView):
    template_name = "manager/vendor_wallet.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        user = get_object_or_404(
            FalconUser, id=self.kwargs["vendor_id"], role=FalconUser.ROLE_VENDOR
        )
        wallet = get_or_create_wallet(user)
        ctx["wallet_user"] = user
        ctx["wallet"] = wallet
        ctx["transactions"] = wallet.transactions.select_related(
            "related_order", "created_by"
        )[:100]
        ctx["withdrawals"] = VendorWithdrawalRequest.objects.filter(vendor=user)[:20]
        ctx["deduct_form"] = ManagerDeductWalletForm()
        ctx["can_act"] = self.request.user.role == FalconUser.ROLE_MANAGER
        return ctx


class ManagerDeductWalletView(ManagerRequiredMixin, View):
    def post(self, request, vendor_id):
        vendor = get_object_or_404(FalconUser, id=vendor_id, role=FalconUser.ROLE_VENDOR)
        form = ManagerDeductWalletForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for err in errors:
                    messages.error(request, err)
            return redirect("vendor:manager_vendor_wallet", vendor_id=vendor_id)
        wallet = get_or_create_wallet(vendor)
        amount = form.cleaned_data["amount"]
        reason = form.cleaned_data["reason"].strip()
        try:
            tx = debit_wallet(
                wallet,
                VendorWalletTransaction.TYPE_MANUAL_DEDUCTION,
                amount,
                reason=reason,
                created_by=request.user,
            )
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("vendor:manager_vendor_wallet", vendor_id=vendor_id)
        log_action(
            request,
            "wallet_deduction",
            tx,
            description=f"Deducted \u20a6{amount} from {vendor.email}'s wallet",
            new_value={"amount": str(amount), "balance": str(tx.new_balance)},
            reason=reason,
        )
        messages.success(request, f"\u20a6{amount} deducted. New balance \u20a6{tx.new_balance}.")
        return redirect("vendor:manager_vendor_wallet", vendor_id=vendor_id)


class ManagerWithdrawalListView(ManagerOrSubManagerMixin, ListView):
    template_name = "manager/withdrawals.html"
    context_object_name = "withdrawals"
    paginate_by = 20

    def get_queryset(self):
        qs = VendorWithdrawalRequest.objects.select_related("vendor").order_by("-requested_at")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        return ctx


class ManagerApproveWithdrawalView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        withdrawal = get_object_or_404(VendorWithdrawalRequest, id=pk)
        try:
            withdrawal, note = approve_withdrawal(withdrawal, processed_by=request.user)
            log_action(
                request,
                "withdrawal_approved",
                withdrawal,
                description=f"Withdrawal #{withdrawal.id} of \u20a6{withdrawal.amount_transferred} approved",
                new_value={"status": withdrawal.status},
            )
            messages.success(request, note)
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("vendor:manager_withdrawals")


class ManagerRejectWithdrawalView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        withdrawal = get_object_or_404(VendorWithdrawalRequest, id=pk)
        reason = request.POST.get("reason", "").strip()
        if withdrawal.status != VendorWithdrawalRequest.STATUS_PENDING:
            messages.error(request, "Only pending withdrawals can be rejected.")
            return redirect("vendor:manager_withdrawals")
        withdrawal.status = VendorWithdrawalRequest.STATUS_REJECTED
        withdrawal.rejection_reason = reason
        withdrawal.processed_at = timezone.now()
        withdrawal.processed_by = request.user
        withdrawal.save(update_fields=["status", "rejection_reason", "processed_at", "processed_by"])
        log_action(
            request,
            "withdrawal_rejected",
            withdrawal,
            description=f"Withdrawal #{withdrawal.id} rejected: {reason}",
            new_value={"status": "rejected"},
            reason=reason,
        )
        messages.success(request, "Withdrawal rejected.")
        return redirect("vendor:manager_withdrawals")


