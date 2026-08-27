import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from apps.audit.services import log_action
from apps.core.mixins import (
    CustomerOrVendorRequiredMixin,
    ManagerOrSubManagerMixin,
    ManagerRequiredMixin,
    ReadOnlySubManagerMixin,
)
from apps.core.paystack import PaystackError, initialize_transaction, verify_transaction
from apps.delivery.forms import AgentPickupForm
from apps.accounts.models import DeliveryAgentProfile
from apps.delivery.models import DeliveryAssignment

from .forms import ParcelQuoteForm, ParcelRequestForm
from .models import ParcelRequest

logger = logging.getLogger("falcon.parcel")


class ParcelRequestView(CustomerOrVendorRequiredMixin, FormView):
    template_name = "parcel/request.html"
    form_class = ParcelRequestForm

    def get_initial(self):
        initial = super().get_initial()
        user = self.request.user
        if user.role == "customer" and hasattr(user, "customerprofile"):
            initial["sender_name"] = user.customerprofile.full_name
            initial["sender_phone"] = user.customerprofile.phone_number
        elif user.role == "vendor" and hasattr(user, "vendorprofile"):
            initial["sender_name"] = user.vendorprofile.contact_name or user.vendorprofile.business_name
            initial["sender_phone"] = user.vendorprofile.phone_number
        return initial

    def form_valid(self, form):
        parcel = form.save(commit=False)
        parcel.requested_by = self.request.user
        lat = self.request.POST.get("pickup_address_lat") or None
        lng = self.request.POST.get("pickup_address_lng") or None
        rlat = self.request.POST.get("receiver_address_lat") or None
        rlng = self.request.POST.get("receiver_address_lng") or None
        parcel.pickup_address_lat = lat
        parcel.pickup_address_lng = lng
        parcel.receiver_address_lat = rlat
        parcel.receiver_address_lng = rlng
        parcel.save()
        log_action(
            self.request,
            "order_created",
            parcel,
            description=f"Parcel {parcel.parcel_reference} requested by {self.request.user.email}",
        )
        messages.success(
            self.request,
            f"Parcel {parcel.parcel_reference} submitted. Falcon will send you a quote shortly.",
        )
        return redirect("parcel:detail", ref=parcel.parcel_reference)


class ParcelListView(CustomerOrVendorRequiredMixin, ListView):
    template_name = "parcel/history.html"
    context_object_name = "parcels"
    paginate_by = 15

    def get_queryset(self):
        return ParcelRequest.objects.filter(requested_by=self.request.user)


class ParcelDetailView(CustomerOrVendorRequiredMixin, TemplateView):
    template_name = "parcel/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parcel = get_object_or_404(
            ParcelRequest, parcel_reference=self.kwargs["ref"],
            requested_by=self.request.user,
        )
        ctx["parcel"] = parcel
        return ctx


class ParcelAcceptQuoteView(CustomerOrVendorRequiredMixin, View):
    def post(self, request, ref):
        parcel = get_object_or_404(
            ParcelRequest, parcel_reference=ref, requested_by=request.user
        )
        if parcel.status != ParcelRequest.STATUS_QUOTED:
            messages.error(request, "This parcel has no open quote to accept.")
            return redirect("parcel:detail", ref=ref)
        reference = f"{parcel.parcel_reference}-{int(timezone.now().timestamp())}"
        callback_url = request.build_absolute_uri(reverse("parcel:paystack_callback"))
        try:
            result = initialize_transaction(
                email=request.user.email,
                amount_naira=float(parcel.delivery_fee),
                reference=reference,
                callback_url=callback_url,
                metadata={"parcel": parcel.parcel_reference},
            )
        except PaystackError as exc:
            logger.exception("Paystack init failed for %s", ref)
            messages.error(request, f"Payment could not be started ({exc}).")
            return redirect("parcel:detail", ref=ref)
        parcel.paystack_reference = result["reference"]
        parcel.save(update_fields=["paystack_reference"])
        if result["authorization_url"]:
            return redirect(result["authorization_url"])
        parcel.mark_paid(simulated=True)
        messages.success(
            request, "Payment confirmed (dev mode). Your parcel is being processed."
        )
        return redirect("parcel:detail", ref=ref)


def parcel_paystack_callback(request):
    from django.contrib.auth.views import redirect_to_login

    reference = request.GET.get("reference", "")
    parcel = ParcelRequest.objects.filter(paystack_reference=reference).first()
    if parcel is None:
        messages.error(request, "Unknown payment reference.")
        return redirect("/")
    if not request.user.is_authenticated or parcel.requested_by_id != request.user.id:
        raise PermissionDenied("You cannot view this payment.")
    try:
        verification = verify_transaction(reference)
    except PaystackError as exc:
        logger.exception("Paystack verify failed for %s", reference)
        messages.error(request, f"We could not confirm your payment ({exc}).")
        return redirect("parcel:detail", ref=parcel.parcel_reference)
    expected_kobo = int(parcel.delivery_fee * 100)
    actual = verification.get("amount_kobo")
    if verification["success"] and (
        verification.get("simulated") or actual is None or int(actual) >= expected_kobo
    ):
        parcel.mark_paid(reference=reference, simulated=verification.get("simulated", False))
        messages.success(request, "Payment confirmed! Your parcel is being processed.")
    else:
        parcel.payment_status = "failed"
        parcel.save(update_fields=["payment_status"])
        messages.error(request, "Payment was not successful.")
    return redirect("parcel:detail", ref=parcel.parcel_reference)


class ParcelCancelView(CustomerOrVendorRequiredMixin, View):
    def post(self, request, ref):
        parcel = get_object_or_404(
            ParcelRequest, parcel_reference=ref, requested_by=request.user
        )
        if parcel.status not in ("pending", "quoted"):
            messages.error(request, "This parcel can no longer be cancelled.")
            return redirect("parcel:detail", ref=ref)
        parcel.status = ParcelRequest.STATUS_CANCELLED
        parcel.save(update_fields=["status", "updated_at"])
        messages.info(request, "Parcel cancelled.")
        return redirect("parcel:history")


class ManagerParcelListView(ManagerOrSubManagerMixin, ListView):
    template_name = "manager/parcels.html"
    context_object_name = "parcels"
    paginate_by = 20

    def get_queryset(self):
        qs = ParcelRequest.objects.select_related("requested_by")
        status = self.request.GET.get("status", "")
        if status:
            qs = qs.filter(status=status)
        query = self.request.GET.get("q", "").strip()
        if query:
            from django.db.models import Q

            qs = qs.filter(
                Q(parcel_reference__icontains=query) | Q(receiver_name__icontains=query)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_filter"] = self.request.GET.get("status", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class ManagerParcelDetailView(ReadOnlySubManagerMixin, TemplateView):
    template_name = "manager/parcel_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parcel = get_object_or_404(
            ParcelRequest.objects.select_related("requested_by", "dropoff_warehouse"),
            parcel_reference=self.kwargs["ref"],
        )
        ctx["parcel"] = parcel
        ctx["quote_form"] = ParcelQuoteForm(
            initial={
                "delivery_fee": parcel.delivery_fee,
                "quote_note": parcel.quote_note,
            }
        )
        ctx["agents"] = DeliveryAgentProfile.objects.select_related("user").filter(
            user__is_active=True
        )
        ctx["assignment"] = DeliveryAssignment.objects.filter(parcel=parcel).first()
        ctx["can_act"] = self.request.user.role == "manager"
        return ctx


class ManagerQuoteParcelView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        parcel = get_object_or_404(ParcelRequest, parcel_reference=ref)
        form = ParcelQuoteForm(request.POST)
        if not form.is_valid():
            for errors in form.errors.values():
                for err in errors:
                    messages.error(request, err)
            return redirect("parcel:manager_detail", ref=ref)
        if parcel.status != ParcelRequest.STATUS_PENDING:
            messages.error(request, f"Cannot quote a '{parcel.status}' parcel.")
            return redirect("parcel:manager_detail", ref=ref)
        parcel.delivery_fee = form.cleaned_data["delivery_fee"]
        parcel.quote_note = form.cleaned_data.get("quote_note", "")
        parcel.quoted_by = request.user
        parcel.quoted_at = timezone.now()
        parcel.status = ParcelRequest.STATUS_QUOTED
        parcel.save()
        log_action(
            request,
            "parcel_quoted",
            parcel,
            description=f"{ref} quoted at \u20a6{parcel.delivery_fee}",
            new_value={"fee": str(parcel.delivery_fee)},
        )
        messages.success(
            request, f"Quote of \u20a6{parcel.delivery_fee} sent to the customer."
        )
        return redirect("parcel:manager_detail", ref=ref)


class ManagerAssignParcelAgentView(ManagerRequiredMixin, View):
    def post(self, request, ref):
        parcel = get_object_or_404(ParcelRequest, parcel_reference=ref)
        if parcel.status != ParcelRequest.STATUS_PROCESSING:
            messages.error(
                request, "Agents can only be assigned after payment is confirmed."
            )
            return redirect("parcel:manager_detail", ref=ref)
        agent = get_object_or_404(
            DeliveryAgentProfile, id=request.POST.get("agent_id")
        )
        parcel.assigned_agent = agent
        parcel.save(update_fields=["assigned_agent", "updated_at"])
        assignment, _ = DeliveryAssignment.objects.get_or_create(
            parcel=parcel,
            defaults={"agent": agent, "assigned_by": request.user},
        )
        if assignment.agent_id != agent.id:
            assignment.agent = agent
            assignment.save(update_fields=["agent"])
        log_action(
            request,
            "agent_assigned",
            parcel,
            description=f"{ref}: assigned {agent.full_name}",
            new_value={"agent": agent.full_name},
        )
        messages.success(request, f"{agent.full_name} assigned to {ref}.")
        return redirect("parcel:manager_detail", ref=ref)


class ManagerParcelOverrideView(ManagerRequiredMixin, View):
    action_type = "delivered"

    def post(self, request, ref):
        parcel = get_object_or_404(ParcelRequest, parcel_reference=ref)
        if parcel.status in ("delivered", "cancelled"):
            messages.error(request, f"Parcel already '{parcel.status}' — no further changes allowed.")
            return redirect("parcel:manager_detail", ref=ref)
        assignment = DeliveryAssignment.objects.filter(parcel=parcel).first()
        now = timezone.now()
        delivery_notes = (request.POST.get("delivery_notes") or "").strip()
        try:
            if self.action_type == "delivered":
                if parcel.status == "quoted":
                    raise ValueError("Customer has not paid yet.")
                if parcel.status != ParcelRequest.STATUS_IN_TRANSIT and assignment:
                    assignment.status = DeliveryAssignment.STATUS_OUT_FOR_DELIVERY
                    assignment.save(update_fields=["status"])
                    parcel.status = ParcelRequest.STATUS_IN_TRANSIT
                if parcel.status != ParcelRequest.STATUS_IN_TRANSIT:
                    parcel.status = ParcelRequest.STATUS_IN_TRANSIT
                parcel.status = ParcelRequest.STATUS_DELIVERED
                parcel.delivered_at = now
                parcel.save(update_fields=["status", "delivered_at", "updated_at"])
                if assignment:
                    assignment.status = DeliveryAssignment.STATUS_DELIVERED
                    assignment.delivered_at = now
                    if delivery_notes:
                        assignment.delivery_notes = delivery_notes
                    assignment.save(update_fields=["status", "delivered_at"] + (["delivery_notes"] if delivery_notes else []))
                log_action(
                    request,
                    "delivery_completed",
                    parcel,
                    description=f"{ref} delivered (manager override)",
                    new_value={"status": "delivered"},
                )
                messages.success(request, f"{ref} marked delivered.")
            else:
                reason = delivery_notes or "Marked failed by manager"
                previous = parcel.status
                parcel.status = ParcelRequest.STATUS_FAILED
                parcel.save(update_fields=["status", "updated_at"])
                if assignment:
                    assignment.status = DeliveryAssignment.STATUS_FAILED
                    assignment.delivery_notes = reason
                    assignment.save(update_fields=["status", "delivery_notes"])
                log_action(
                    request,
                    "delivery_failed",
                    parcel,
                    description=f"{ref} failed ({previous}): {reason}",
                    previous_value={"status": previous},
                    new_value={"status": "failed"},
                    reason=reason,
                )
                messages.info(request, f"{ref} marked failed.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("parcel:manager_detail", ref=ref)

