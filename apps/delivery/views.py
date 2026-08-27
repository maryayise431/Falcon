import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

import django.db.models as dm
from decimal import Decimal

from apps.audit.services import log_action
from apps.core.mixins import AgentRequiredMixin, ManagerRequiredMixin
from apps.marketplace.models import MarketplaceOrder
from apps.parcel.models import ParcelRequest
from apps.vendor.models import VendorFulfillmentOrder
from apps.vendor.services import settle_cod_delivery, transition_order

from apps.core.period import parse_period
from .forms import AgentDeliverForm, AgentFailForm, AgentPickupForm, ParcelDeliverForm
from .models import DeliveryAssignment

logger = logging.getLogger("falcon.delivery")


def build_timeline(entry):
    if hasattr(entry, "order_reference") and getattr(entry, "cod_amount", None) is not None and hasattr(entry, "vendor_id"):
        steps = ["pending", "processing", "awaiting_assignment", "assigned", "approved", "out_for_delivery", "delivered"]
        status = entry.status
    elif hasattr(entry, "parcel_reference"):
        steps = ["pending", "quoted", "processing", "in_transit", "delivered"]
        status = entry.status
    elif hasattr(entry, "delivery_method"):
        steps = ["pending", "processing", "out_for_delivery", "delivered"]
        status = entry.status
    else:
        steps = ["pending", "processing", "out_for_delivery", "delivered"]
        status = entry.status
    try:
        current_index = steps.index(status)
    except ValueError:
        if status in ("failed", "cancelled"):
            return {"steps": steps, "current_index": None, "terminal": status}
        current_index = 0
    return {"steps": steps, "current_index": current_index, "terminal": None}


def resolve_tracking(reference):
    reference = (reference or "").strip().upper()
    order = VendorFulfillmentOrder.objects.filter(order_reference=reference).first()
    if order:
        return {
            "kind": "Vendor Fulfilment",
            "reference": order.order_reference,
            "status": order.get_status_display(),
            "raw_status": order.status,
            "timeline": build_timeline(order),
            "receiver": order.customer_name,
            "destination_city": order.customer_address.split("\n")[0][-60:],
            "updated_at": order.updated_at,
            "created_at": order.created_at,
            "items": [],
            "agent": order.assigned_agent.full_name if order.assigned_agent else "",
        }
    parcel = ParcelRequest.objects.filter(parcel_reference=reference).first()
    if parcel:
        agent = ""
        assignment = parcel.assignments.select_related("agent").first()
        if assignment:
            agent = assignment.agent.full_name
        elif parcel.assigned_agent:
            agent = parcel.assigned_agent.full_name
        return {
            "kind": "Parcel Delivery",
            "reference": parcel.parcel_reference,
            "status": parcel.get_status_display(),
            "raw_status": parcel.status,
            "timeline": build_timeline(parcel),
            "receiver": parcel.receiver_name,
            "destination_city": parcel.receiver_address.split("\n")[0][-60:],
            "updated_at": parcel.updated_at if hasattr(parcel, "updated_at") else parcel.created_at,
            "created_at": parcel.created_at,
            "items": [],
            "agent": agent,
        }
    mk_order = (
        MarketplaceOrder.objects.filter(order_reference=reference)
        .select_related("customer")
        .first()
    )
    if mk_order:
        items = list(mk_order.items.values_list("product_name", flat=True)[:3])
        agent = ""
        assignment = mk_order.assignments.select_related("agent").first()
        if assignment:
            agent = assignment.agent.full_name
        return {
            "kind": "Marketplace Order",
            "reference": mk_order.order_reference,
            "status": mk_order.get_status_display(),
            "raw_status": mk_order.status,
            "timeline": build_timeline(mk_order),
            "receiver": mk_order.customer.email,
            "destination_city": mk_order.delivery_address.split("\n")[0][-60:] if mk_order.delivery_address else "",
            "updated_at": mk_order.updated_at,
            "created_at": mk_order.created_at,
            "items": items,
            "agent": agent,
        }
    return None


class PublicTrackingView(TemplateView):
    template_name = "delivery/track.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["reference"] = self.request.GET.get("ref", "").strip()
        return ctx


class PublicTrackingDetailView(TemplateView):
    template_name = "delivery/track_detail.html"

    def get(self, request, ref=None, *args, **kwargs):
        result = resolve_tracking(ref)
        if result is None:
            messages.error(request, f"No shipment found for reference '{ref}'.")
            return redirect("/track/")
        ctx = {"tracking": result}
        return render(request, self.template_name, ctx)


class DeliveryAgentDashboardView(AgentRequiredMixin, TemplateView):
    template_name = "delivery/agent_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = self.request.user.deliveryagentprofile
        assignments = DeliveryAssignment.objects.filter(agent=profile).select_related(
            "order", "parcel", "marketplace_order",
        )
        ctx["profile"] = profile
        active = assignments.filter(status__in=["assigned", "out_for_delivery"])
        ctx["active_assignments"] = active
        ctx["out_for_delivery_count"] = assignments.filter(status="out_for_delivery").count()
        ctx["completed_count"] = assignments.filter(status="delivered").count()
        ctx["failed_count"] = assignments.filter(status="failed").count()
        cod_today = (
            assignments.filter(
                status="delivered",
                delivered_at__date=timezone.localdate(),
                cod_confirmed=True,
            ).aggregate(t=dm.Sum("cod_collected"))["t"]
            or 0
        )
        ctx["cod_today"] = cod_today
        from apps.vendor.models import VendorProduct
        ctx["assigned_products"] = VendorProduct.objects.filter(
            assigned_agent=profile
        ).select_related("vendor", "vendor__vendorprofile", "warehouse").order_by("-created_at")
        ctx["vendor_orders"] = VendorFulfillmentOrder.objects.filter(
            product__assigned_agent=profile
        ).select_related("product", "vendor", "vendor__vendorprofile", "assigned_agent").order_by("-created_at")[:5]
        return ctx


class AgentInventoryView(AgentRequiredMixin, TemplateView):
    template_name = "delivery/agent_inventory.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = self.request.user.deliveryagentprofile
        from apps.vendor.models import VendorProduct
        ctx["products"] = VendorProduct.objects.filter(
            assigned_agent=profile
        ).select_related("vendor", "vendor__vendorprofile", "warehouse").order_by("-created_at")
        ctx["profile"] = profile
        return ctx


class AgentDeliveryListView(AgentRequiredMixin, ListView):
    template_name = "delivery/agent_deliveries.html"
    context_object_name = "assignments"
    paginate_by = 15

    def get_queryset(self):
        profile = self.request.user.deliveryagentprofile
        qs = DeliveryAssignment.objects.filter(agent=profile).select_related(
            "order", "parcel", "marketplace_order",
        )
        state = self.request.GET.get("status", "")
        if state == "active":
            qs = qs.filter(status__in=["assigned", "out_for_delivery"])
        elif state:
            qs = qs.filter(status=state)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["state_filter"] = self.request.GET.get("status", "")
        return ctx


def _get_assignment(request, ref, require_agent=True):
    assignment = (
        DeliveryAssignment.objects.select_related(
            "order", "order__vendor", "order__product", "parcel",
            "marketplace_order", "agent",
        )
        .filter(
            dm.Q(order__order_reference=ref)
            | dm.Q(parcel__parcel_reference=ref)
            | dm.Q(marketplace_order__order_reference=ref)
        )
        .first()
    )
    if assignment is None:
        raise PermissionDenied("Assignment not found.")
    if require_agent and assignment.agent.user_id != request.user.id:
        raise PermissionDenied("This delivery is not assigned to you.")
    return assignment


class AgentDeliveryDetailView(AgentRequiredMixin, TemplateView):
    template_name = "delivery/agent_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assignment = _get_assignment(self.request, self.kwargs["ref"])
        ctx["assignment"] = assignment
        if assignment.order:
            ctx["deliver_form"] = AgentDeliverForm(
                initial={"cod_collected": assignment.order.cod_amount}
            )
        elif assignment.marketplace_order:
            ctx["parcel_deliver_form"] = ParcelDeliverForm()
        else:
            ctx["parcel_deliver_form"] = ParcelDeliverForm()
        ctx["fail_form"] = AgentFailForm()
        ctx["pickup_form"] = AgentPickupForm()
        return ctx


def _mark_out_for_delivery(request, assignment, notes=""):
    now = timezone.now()
    if assignment.order:
        transition_order(assignment.order, VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY)
        assignment.status = DeliveryAssignment.STATUS_OUT_FOR_DELIVERY
        assignment.delivery_notes = notes or assignment.delivery_notes
        assignment.save(update_fields=["status", "delivery_notes"])
    elif assignment.marketplace_order:
        mko = assignment.marketplace_order
        if mko.status not in ("processing", "assigned"):
            raise ValueError(f"Cannot dispatch a '{mko.status}' marketplace order.")
        mko.status = MarketplaceOrder.STATUS_OUT_FOR_DELIVERY
        mko.save(update_fields=["status", "updated_at"])
        assignment.status = DeliveryAssignment.STATUS_OUT_FOR_DELIVERY
        assignment.delivery_notes = notes or assignment.delivery_notes
        assignment.save(update_fields=["status", "delivery_notes"])
    else:
        parcel = assignment.parcel
        if parcel.status not in ("processing", "quoted"):
            raise ValueError(f"Cannot dispatch a '{parcel.status}' parcel.")
        parcel.status = ParcelRequest.STATUS_IN_TRANSIT
        parcel.save(update_fields=["status"])
        assignment.status = DeliveryAssignment.STATUS_OUT_FOR_DELIVERY
        assignment.save(update_fields=["status"])
    log_action(
        request,
        "order_status_changed",
        assignment.order or assignment.parcel or assignment.marketplace_order,
        description=f"{assignment.reference}: picked up by {assignment.agent.full_name}",
        new_value={"status": "out_for_delivery"},
    )


def _mark_delivered(request, assignment, cod_collected=None, notes=""):
    now = timezone.now()
    if assignment.order:
        order = assignment.order
        collected = cod_collected if cod_collected is not None else order.cod_amount
        transition_order(order, VendorFulfillmentOrder.STATUS_DELIVERED)
        settle_cod_delivery(order, collected)
        assignment.status = DeliveryAssignment.STATUS_DELIVERED
        assignment.cod_collected = collected
        assignment.cod_confirmed = True
        assignment.delivered_at = now
        assignment.delivery_notes = notes or assignment.delivery_notes
        assignment.save(
            update_fields=[
                "status",
                "cod_collected",
                "cod_confirmed",
                "delivered_at",
                "delivery_notes",
            ]
        )
        log_action(
            request,
            "delivery_completed",
            order,
            description=(
                f"{order.order_reference} delivered by {assignment.agent.full_name}. "
                f"COD \u20a6{collected} collected; wallet credited."
            ),
            new_value={"status": "delivered", "cod_collected": str(collected)},
        )
    elif assignment.marketplace_order:
        mko = assignment.marketplace_order
        if mko.status != MarketplaceOrder.STATUS_OUT_FOR_DELIVERY:
            raise ValueError(f"Cannot complete a '{mko.status}' marketplace order.")
        mko.status = MarketplaceOrder.STATUS_DELIVERED
        mko.delivered_at = now
        mko.save(update_fields=["status", "delivered_at", "updated_at"])
        assignment.status = DeliveryAssignment.STATUS_DELIVERED
        assignment.delivered_at = now
        assignment.delivery_notes = notes or assignment.delivery_notes
        assignment.save(update_fields=["status", "delivered_at", "delivery_notes"])
        log_action(
            request,
            "delivery_completed",
            mko,
            description=f"{mko.order_reference} delivered by {assignment.agent.full_name}",
            new_value={"status": "delivered"},
        )
    else:
        parcel = assignment.parcel
        if parcel.status != ParcelRequest.STATUS_IN_TRANSIT:
            raise ValueError(f"Cannot complete a '{parcel.status}' parcel.")
        parcel.status = ParcelRequest.STATUS_DELIVERED
        parcel.delivered_at = now
        parcel.save(update_fields=["status", "delivered_at"])
        assignment.status = DeliveryAssignment.STATUS_DELIVERED
        assignment.delivered_at = now
        assignment.delivery_notes = notes or assignment.delivery_notes
        assignment.save(update_fields=["status", "delivered_at", "delivery_notes"])
        log_action(
            request,
            "delivery_completed",
            parcel,
            description=f"{parcel.parcel_reference} delivered by {assignment.agent.full_name}",
            new_value={"status": "delivered"},
        )


def _mark_failed(request, assignment, reason):
    if assignment.order:
        order = assignment.order
        from_status = order.status
        transition_order(order, VendorFulfillmentOrder.STATUS_FAILED)
        assignment.status = DeliveryAssignment.STATUS_FAILED
        assignment.delivery_notes = reason
        assignment.save(update_fields=["status", "delivery_notes"])
        log_action(
            request,
            "delivery_failed",
            order,
            description=f"{order.order_reference} marked failed ({from_status}) by {assignment.agent.full_name}: {reason}",
            previous_value={"status": from_status},
            new_value={"status": "failed"},
            reason=reason,
        )
    elif assignment.marketplace_order:
        mko = assignment.marketplace_order
        from_status = mko.status
        if mko.status in ("delivered", "cancelled"):
            raise ValueError("Marketplace order is already closed.")
        mko.status = MarketplaceOrder.STATUS_FAILED
        mko.save(update_fields=["status", "updated_at"])
        assignment.status = DeliveryAssignment.STATUS_FAILED
        assignment.delivery_notes = reason
        assignment.save(update_fields=["status", "delivery_notes"])
        log_action(
            request,
            "delivery_failed",
            mko,
            description=f"{mko.order_reference} failed ({from_status}): {reason}",
            previous_value={"status": from_status},
            new_value={"status": "failed"},
            reason=reason,
        )
    else:
        parcel = assignment.parcel
        if parcel.status in ("delivered", "cancelled"):
            raise ValueError("Parcel is already closed.")
        parcel.status = ParcelRequest.STATUS_FAILED
        parcel.save(update_fields=["status"])
        assignment.status = DeliveryAssignment.STATUS_FAILED
        assignment.delivery_notes = reason
        assignment.save(update_fields=["status", "delivery_notes"])
        log_action(
            request,
            "delivery_failed",
            parcel,
            description=f"{parcel.parcel_reference} failed: {reason}",
            new_value={"status": "failed"},
            reason=reason,
        )


class AgentPickupView(AgentRequiredMixin, View):
    def post(self, request, ref):
        assignment = _get_assignment(request, ref)
        form = AgentPickupForm(request.POST)
        notes = form.data.get("pickup_notes", "")
        try:
            if assignment.order:
                if assignment.order.status not in (
                    VendorFulfillmentOrder.STATUS_APPROVED,
                    VendorFulfillmentOrder.STATUS_ASSIGNED,
                ):
                    raise ValueError(
                        f"Pickup requires manager dispatch approval (current: {assignment.order.status})."
                    )
            elif assignment.marketplace_order:
                if assignment.marketplace_order.status not in ("processing", "assigned"):
                    raise ValueError(
                        f"Pickup requires a processing order (current: {assignment.marketplace_order.status})."
                    )
            elif assignment.parcel.status != ParcelRequest.STATUS_PROCESSING:
                raise ValueError(
                    f"Pickup requires a paid parcel (current: {assignment.parcel.status})."
                )
            _mark_out_for_delivery(request, assignment, notes)
            messages.success(request, f"{assignment.reference} is now out for delivery.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("agent:agent_detail", ref=assignment.reference)


class AgentMarkDeliveredView(AgentRequiredMixin, View):
    def post(self, request, ref):
        assignment = _get_assignment(request, ref)
        try:
            if assignment.order:
                form = AgentDeliverForm(request.POST)
                if not form.is_valid():
                    messages.error(request, "; ".join(sum(form.errors.values(), [])))
                    return redirect("agent:agent_detail", ref=assignment.reference)
                if assignment.order.status != VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY:
                    raise ValueError(
                        f"You must pick this delivery up first (current: {assignment.order.status})."
                    )
                cod = form.cleaned_data["cod_collected"]
                expected = assignment.order.cod_amount
                if cod < expected * Decimal("0.5"):
                    raise ValueError(
                        "COD collected looks too low. Record the full amount collected."
                    )
                _mark_delivered(
                    request,
                    assignment,
                    cod_collected=form.cleaned_data["cod_collected"],
                    notes=form.cleaned_data.get("delivery_notes", ""),
                )
                messages.success(
                    request, f"{assignment.reference} delivered. Wallet settlement processed."
                )
            elif assignment.marketplace_order:
                form = ParcelDeliverForm(request.POST)
                if not form.is_valid():
                    messages.error(request, "; ".join(sum(form.errors.values(), [])))
                    return redirect("agent:agent_detail", ref=assignment.reference)
                if assignment.marketplace_order.status != MarketplaceOrder.STATUS_OUT_FOR_DELIVERY:
                    raise ValueError(
                        f"You must pick this delivery up first (current: {assignment.marketplace_order.status})."
                    )
                notes = form.cleaned_data.get("delivery_notes", "")
                _mark_delivered(request, assignment, notes=notes)
                messages.success(request, f"{assignment.reference} marked as delivered.")
            else:
                form = ParcelDeliverForm(request.POST)
                if not form.is_valid():
                    messages.error(request, "; ".join(sum(form.errors.values(), [])))
                    return redirect("agent:agent_detail", ref=assignment.reference)
                notes = form.cleaned_data.get("delivery_notes", "")
                _mark_delivered(request, assignment, notes=notes)
                messages.success(request, f"{assignment.reference} marked as delivered.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("agent:agent_detail", ref=assignment.reference)


def Decimal_guard(value):
    return Decimal(str(value))


class AgentMarkFailedView(AgentRequiredMixin, View):
    def post(self, request, ref):
        assignment = _get_assignment(request, ref)
        form = AgentFailForm(request.POST)
        if not form.is_valid():
            messages.error(request, "A failure reason is required.")
            return redirect("agent:agent_detail", ref=assignment.reference)
        try:
            if assignment.order and assignment.order.status in ("delivered", "failed", "cancelled"):
                raise ValueError(f"This order is already '{assignment.order.status}'.")
            if assignment.marketplace_order and assignment.marketplace_order.status in ("delivered", "failed", "cancelled"):
                raise ValueError(f"This order is already '{assignment.marketplace_order.status}'.")
            _mark_failed(request, assignment, form.cleaned_data["failure_reason"])
            messages.info(request, f"{assignment.reference} marked as failed.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("agent:agent_detail", ref=assignment.reference)


class ManagerDeliveryOverrideView(ManagerRequiredMixin, View):
    action_type = "delivered"

    def post(self, request, ref):
        assignment = (
            DeliveryAssignment.objects.filter(
                dm.Q(order__order_reference=ref)
                | dm.Q(parcel__parcel_reference=ref)
                | dm.Q(marketplace_order__order_reference=ref)
            )
            .first()
        )
        if assignment is None:
            messages.error(request, "No active assignment found for that reference.")
            return redirect("vendor:manager_vendor_orders")
        if self.action_type == "delivered":
            form = AgentDeliverForm(request.POST)
            cod = None
            notes = ""
            if assignment.order:
                if form.is_valid():
                    cod = form.cleaned_data["cod_collected"]
                    notes = form.cleaned_data.get("delivery_notes", "")
                else:
                    cod = assignment.order.cod_amount
            elif assignment.marketplace_order:
                parcel_form = ParcelDeliverForm(request.POST)
                if parcel_form.is_valid():
                    notes = parcel_form.cleaned_data.get("delivery_notes", "")
            try:
                if assignment.order and assignment.status not in ("assigned", "out_for_delivery"):
                    transition_order(assignment.order, VendorFulfillmentOrder.STATUS_OUT_FOR_DELIVERY)
                _mark_delivered(request, assignment, cod_collected=cod, notes=notes)
                messages.success(request, f"{assignment.reference} delivered (manager override).")
            except ValueError as exc:
                messages.error(request, str(exc))
        else:
            reason = request.POST.get("failure_reason", "") or "Marked failed by manager"
            try:
                _mark_failed(request, assignment, reason)
                messages.info(request, f"{assignment.reference} marked failed (manager override).")
            except ValueError as exc:
                messages.error(request, str(exc))
        if assignment.marketplace_order:
            return redirect("marketplace:manager_order_detail", ref=ref)
        return redirect("vendor:manager_vendor_order_detail", ref=ref)


class ManagerReportsRedirectView(ManagerRequiredMixin, View):
    def get(self, request):
        return redirect("reports:manager_dashboard")


class AgentVendorOrdersView(AgentRequiredMixin, ListView):
    template_name = "delivery/agent_vendor_orders.html"
    context_object_name = "orders"
    paginate_by = 15

    def get_queryset(self):
        profile = self.request.user.deliveryagentprofile
        return VendorFulfillmentOrder.objects.filter(
            product__assigned_agent=profile
        ).select_related("product", "vendor", "vendor__vendorprofile", "assigned_agent").order_by("-created_at")


class AgentReportsView(AgentRequiredMixin, TemplateView):
    template_name = "delivery/agent_reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        profile = self.request.user.deliveryagentprofile
        assignments = DeliveryAssignment.objects.filter(agent=profile).select_related(
            "order", "parcel"
        )
        period = self.request.GET.get("period", "this_month")
        start, end = parse_period(period, self.request)
        scoped = assignments.filter(assigned_at__range=(start, end))
        delivered = scoped.filter(status="delivered")
        failed = scoped.filter(status="failed")
        active = scoped.filter(status__in=["assigned", "out_for_delivery"])
        ctx["period"] = period
        ctx["start"] = start
        ctx["end"] = end
        ctx["assignments"] = scoped[:100]
        ctx["counts"] = {
            "delivered": delivered.count(),
            "failed": failed.count(),
            "active": active.count(),
            "total": scoped.count(),
        }
        cod_total = (
            delivered.filter(cod_confirmed=True).aggregate(t=dm.Sum("cod_collected"))["t"]
            or 0
        )
        ctx["cod_total"] = cod_total
        return ctx

