from datetime import datetime, timedelta

from django.contrib import messages
from django.db.models import Count, Sum
from django.shortcuts import redirect
from django.utils.timezone import localdate
from django.views.generic import TemplateView

from apps.accounts.models import FalconUser
from apps.audit.models import AuditLog
from apps.core.mixins import (
    CustomerRequiredMixin,
    ManagerOrSubManagerMixin,
    ManagerRequiredMixin,
    ReadOnlySubManagerMixin,
    VendorRequiredMixin,
)
from apps.delivery.models import DeliveryAssignment
from apps.marketplace.models import MarketplaceOrder, MarketplaceOrderItem
from apps.parcel.models import ParcelRequest
from apps.vendor.models import (
    VendorFulfillmentOrder,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)

from .mixins import CSVExportMixin, PeriodMixin, revenue_breakdown


class ManagerDashboardStatsView(ManagerOrSubManagerMixin, TemplateView):
    template_name = "reports/manager_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        today = localdate()
        from django.utils import timezone as tz

        start_of_day = tz.make_aware(
            datetime(today.year, today.month, today.day)
        )
        ctx["stats"] = {
            "revenue_today": revenue_breakdown(start_of_day, start_of_day + timedelta(days=1))["total"],
            "pending_orders": VendorFulfillmentOrder.objects.filter(
                status__in=["pending", "processing"]
            ).count(),
            "awaiting_assignment": VendorFulfillmentOrder.objects.filter(
                status="awaiting_assignment"
            ).count(),
            "out_for_delivery": DeliveryAssignment.objects.filter(
                status__in=["assigned", "out_for_delivery"]
            ).count(),
            "parcels_to_quote": ParcelRequest.objects.filter(status="pending").count(),
            "pending_withdrawals": VendorWithdrawalRequest.objects.filter(
                status="pending"
            ).count(),
            "cod_today": (
                DeliveryAssignment.objects.filter(
                    delivered_at__range=(start_of_day, start_of_day + timedelta(days=1)),
                    status="delivered",
                    cod_confirmed=True,
                ).aggregate(t=Sum("cod_collected"))["t"]
                or 0
            ),
            "vendors": FalconUser.objects.filter(role=FalconUser.ROLE_VENDOR).count(),
            "customers": FalconUser.objects.filter(role=FalconUser.ROLE_CUSTOMER).count(),
        }
        ctx["recent_orders"] = VendorFulfillmentOrder.objects.select_related("vendor")[:8]
        ctx["recent_audit"] = AuditLog.objects.select_related("actor")[:10]
        ctx["is_manager"] = self.request.user.role == "manager"
        return ctx


class SubManagerDashboardView(ReadOnlySubManagerMixin, TemplateView):
    template_name = "reports/manager_dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        view = ManagerDashboardStatsView()
        view.request = self.request
        ctx.update(view.get_context_data())
        ctx["is_manager"] = False
        return ctx


class BaseReportView(PeriodMixin, TemplateView):
    default_period = "this_month"


class MarketplaceSalesReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/marketplace.html"
    csv_filename = "marketplace_sales"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = MarketplaceOrder.objects.filter(
            created_at__range=(ctx["start"], ctx["end"]),
            payment__status="success",
        ).select_related("customer", "payment")
        total = sum(o.total_amount for o in orders)
        ctx["orders"] = orders[:200]
        ctx["total_revenue"] = total
        ctx["order_count"] = orders.count()
        return ctx

    def csv_payload(self, ctx):
        return (
            ["reference", "customer", "created_at", "total"],
            [
                [o.order_reference, o.customer.email, o.created_at.isoformat(), str(o.total_amount)]
                for o in ctx["orders"]
            ],
        )


class VendorFulfillmentReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/fulfillment.html"
    csv_filename = "vendor_fulfilment"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = VendorFulfillmentOrder.objects.filter(
            created_at__range=(ctx["start"], ctx["end"])
        ).select_related("vendor")
        status_counts = dict(
            orders.values_list("status").annotate(c=Count("id")).values_list("status", "c")
        )
        delivered_fees = (
            VendorWalletTransaction.objects.filter(
                created_at__range=(ctx["start"], ctx["end"]),
                transaction_type="delivery_fee",
            ).aggregate(t=Sum("amount"))["t"]
            or 0
        )
        cod_volume = (
            orders.filter(status="delivered").aggregate(t=Sum("cod_amount"))["t"] or 0
        )
        ctx["orders"] = orders[:200]
        ctx["status_counts"] = status_counts
        ctx["fees_collected"] = delivered_fees
        ctx["cod_volume"] = cod_volume
        ctx["order_count"] = orders.count()
        return ctx

    def csv_payload(self, ctx):
        return (
            ["reference", "vendor", "cod_amount", "delivery_fee", "status", "created_at"],
            [
                [
                    o.order_reference,
                    o.vendor.email,
                    str(o.cod_amount),
                    str(o.delivery_fee or ""),
                    o.status,
                    o.created_at.isoformat(),
                ]
                for o in ctx["orders"]
            ],
        )


class RevenueReportView(ManagerOrSubManagerMixin, BaseReportView):
    template_name = "reports/revenue.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["breakdown"] = revenue_breakdown(ctx["start"], ctx["end"])
        return ctx


def bucket_rows(bucket_fn, start, end, step_days=None):
    buckets = {}
    cur = start
    while cur < end:
        key = bucket_fn(cur)
        if key not in buckets:
            buckets[key] = {
                "label": key,
                "marketplace": 0,
                "fulfilment_fees": 0,
                "parcel": 0,
                "withdrawal_charges": 0,
                "orders": 0,
                "deliveries": 0,
                "parcels": 0,
                "start": cur,
            }
        nxt = min(cur + step_days, end) if step_days else end
        b = buckets[key]
        b["marketplace"] += revenue_component_marketplace(cur, nxt)
        b["fulfilment_fees"] += revenue_component_fee_tx(cur, nxt, "delivery_fee")
        b["parcel"] += revenue_component_parcel(cur, nxt)
        b["withdrawal_charges"] += revenue_component_fee_tx(cur, nxt, "withdrawal_fee")
        b["orders"] += count_range(MarketplaceOrder.objects, cur, nxt, "payment__status", "success")
        b["deliveries"] += DeliveryAssignment.objects.filter(
            delivered_at__range=(cur, nxt), status="delivered"
        ).count()
        b["parcels"] += count_range(ParcelRequest.objects, cur, nxt, "payment_status", "paid")
        if step_days:
            cur = nxt
        else:
            break
    rows = []
    for key in sorted(buckets.keys(), reverse=True):
        row = buckets[key]
        row["total"] = (
            row["marketplace"]
            + row["fulfilment_fees"]
            + row["parcel"]
            + row["withdrawal_charges"]
        )
        rows.append(row)
    return rows


DATED_CSV_HEADERS = [
    "bucket",
    "marketplace",
    "fulfilment_fees",
    "parcel",
    "withdrawal_charges",
    "total",
    "orders",
    "deliveries",
    "parcels",
]


def dated_csv_payload(rows):
    return (
        DATED_CSV_HEADERS,
        [
            [
                r["label"],
                str(r["marketplace"]),
                str(r["fulfilment_fees"]),
                str(r["parcel"]),
                str(r["withdrawal_charges"]),
                str(r["total"]),
                str(r["orders"]),
                str(r["deliveries"]),
                str(r["parcels"]),
            ]
            for r in rows
        ],
    )


def revenue_component_marketplace(start, end):
    from django.db.models import F

    return (
        MarketplaceOrderItem.objects.filter(
            order__created_at__range=(start, end),
            order__payment__status="success",
        ).aggregate(total=Sum(F("unit_price") * F("quantity")))["total"]
    ) or 0


def revenue_component_fee_tx(start, end, tx_type):
    return (
        VendorWalletTransaction.objects.filter(
            created_at__range=(start, end), transaction_type=tx_type
        ).aggregate(t=Sum("amount"))["t"]
    ) or 0


def revenue_component_parcel(start, end):
    return (
        ParcelRequest.objects.filter(
            paid_at__range=(start, end), payment_status="paid"
        ).aggregate(t=Sum("delivery_fee"))["t"]
    ) or 0


def count_range(qs, start, end, field=None, value=None):
    f = {"created_at__range": (start, end)}
    if field and value is not None:
        f[field] = value
    return qs.filter(**f).count()


class DailyReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/dated.html"
    csv_filename = "daily_report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["rows"] = bucket_rows(lambda d: d.date().isoformat(), ctx["start"], ctx["end"], timedelta(days=1))
        ctx["granularity"] = "Daily"
        return ctx

    def csv_payload(self, ctx):
        return dated_csv_payload(ctx["rows"])


class WeeklyReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/dated.html"
    csv_filename = "weekly_report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["rows"] = bucket_rows(lambda d: f"Week of {(d - timedelta(days=d.weekday())).date().isoformat()}", ctx["start"], ctx["end"], timedelta(days=7))
        ctx["granularity"] = "Weekly"
        return ctx

    def csv_payload(self, ctx):
        return dated_csv_payload(ctx["rows"])


class MonthlyReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/dated.html"
    csv_filename = "monthly_report"

    def month_key(self, d):
        return d.strftime("%Y-%m")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["rows"] = bucket_rows(self.month_key, ctx["start"], ctx["end"], None)
        ctx["granularity"] = "Monthly"
        return ctx

    def csv_payload(self, ctx):
        return dated_csv_payload(ctx["rows"])


class CustomReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/dated.html"
    csv_filename = "custom_report"
    default_period = "custom"

    def get(self, request, *args, **kwargs):
        if not request.GET.get("start") and not request.GET.get("end"):
            messages.info(request, "Pick a start and end date for the custom report.")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["rows"] = bucket_rows(lambda d: d.date().isoformat(), ctx["start"], ctx["end"], timedelta(days=1))
        ctx["granularity"] = "Custom Range"
        return ctx

    def csv_payload(self, ctx):
        return dated_csv_payload(ctx["rows"])


class ParcelReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/parcel.html"
    csv_filename = "parcel_report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        parcels = ParcelRequest.objects.filter(created_at__range=(ctx["start"], ctx["end"]))
        status_counts = dict(
            parcels.values_list("status").annotate(c=Count("id")).values_list("status", "c")
        )
        fees = (
            parcels.filter(payment_status="paid").aggregate(t=Sum("delivery_fee"))["t"] or 0
        )
        ctx["parcels"] = parcels.select_related("requested_by")[:200]
        ctx["status_counts"] = status_counts
        ctx["fees_collected"] = fees
        return ctx

    def csv_payload(self, ctx):
        return (
            ["reference", "requester", "fee", "status", "created_at"],
            [
                [
                    p.parcel_reference,
                    p.requested_by.email if p.requested_by else "",
                    str(p.delivery_fee or ""),
                    p.status,
                    p.created_at.isoformat(),
                ]
                for p in ctx["parcels"]
            ],
        )


class CODReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/cod.html"
    csv_filename = "cod_report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        assignments = DeliveryAssignment.objects.filter(
            status="delivered",
            delivered_at__range=(ctx["start"], ctx["end"]),
        ).select_related("order", "order__vendor", "agent", "agent__user")
        collected = (
            assignments.aggregate(t=Sum("cod_collected"))["t"] or 0
        )
        confirmed = (
            assignments.filter(cod_confirmed=True).aggregate(t=Sum("cod_collected"))["t"]
            or 0
        )
        per_agent = (
            assignments.values("agent__full_name")
            .annotate(collected=Sum("cod_collected"), deliveries=Count("id"))
            .order_by("-collected")
        )
        ctx["assignments"] = assignments[:300]
        ctx["collected_total"] = collected
        ctx["confirmed_total"] = confirmed
        ctx["per_agent"] = per_agent
        return ctx

    def csv_payload(self, ctx):
        return (
            ["reference", "agent", "cod_collected", "delivered_at"],
            [
                [
                    a.reference,
                    a.agent.full_name if a.agent else "",
                    str(a.cod_collected),
                    a.delivered_at.isoformat() if a.delivered_at else "",
                ]
                for a in ctx["assignments"]
            ],
        )


class WithdrawalReportView(ManagerOrSubManagerMixin, CSVExportMixin, BaseReportView):
    template_name = "reports/withdrawals.html"
    csv_filename = "withdrawal_report"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        withdrawals = VendorWithdrawalRequest.objects.filter(
            requested_at__range=(ctx["start"], ctx["end"])
        ).select_related("vendor")
        charges_revenue = (
            withdrawals.exclude(status="rejected").aggregate(t=Sum("withdrawal_charge"))["t"]
            or 0
        )
        transferred = (
            withdrawals.filter(status="completed").aggregate(t=Sum("amount_transferred"))["t"]
            or 0
        )
        ctx["withdrawals"] = withdrawals[:200]
        ctx["charges_revenue"] = charges_revenue
        ctx["transferred"] = transferred
        ctx["counts"] = dict(
            withdrawals.values_list("status").annotate(c=Count("id")).values_list("status", "c")
        )
        return ctx

    def csv_payload(self, ctx):
        return (
            ["date", "vendor", "amount_requested", "charge", "transferred", "status"],
            [
                [
                    w.requested_at.isoformat(),
                    w.vendor.email,
                    str(w.amount_requested),
                    str(w.withdrawal_charge),
                    str(w.amount_transferred),
                    w.status,
                ]
                for w in ctx["withdrawals"]
            ],
        )


class VendorOrdersReportView(VendorRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reports/vendor_orders.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = VendorFulfillmentOrder.objects.filter(
            vendor=self.request.user,
            created_at__range=(ctx["start"], ctx["end"]),
        )
        ctx["orders"] = orders[:200]
        ctx["counts"] = dict(
            orders.values_list("status").annotate(c=Count("id")).values_list("status", "c")
        )
        ctx["cod_delivered"] = (
            orders.filter(status="delivered").aggregate(t=Sum("cod_amount"))["t"] or 0
        )
        return ctx


class VendorWalletReportView(VendorRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reports/vendor_wallet.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        txs = VendorWalletTransaction.objects.filter(
            wallet__vendor=self.request.user,
            created_at__range=(ctx["start"], ctx["end"]),
        )
        credits = txs.filter(transaction_type="credit").aggregate(t=Sum("amount"))["t"] or 0
        debits = txs.exclude(transaction_type="credit").aggregate(t=Sum("amount"))["t"] or 0
        ctx["transactions"] = txs[:300]
        ctx["credits"] = credits
        ctx["debits"] = debits
        return ctx


class VendorSettlementReportView(VendorRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reports/vendor_settlements.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        orders = VendorFulfillmentOrder.objects.filter(
            vendor=self.request.user,
            status="delivered",
            delivered_at__range=(ctx["start"], ctx["end"]),
        ).select_related("assigned_agent")
        gross = orders.aggregate(t=Sum("cod_amount"))["t"] or 0
        fees = orders.aggregate(t=Sum("delivery_fee"))["t"] or 0
        ctx["orders"] = orders[:200]
        ctx["gross_cod"] = gross
        ctx["delivery_fees"] = fees or 0
        ctx["net_settlement"] = gross - (fees or 0)
        return ctx


class VendorWithdrawalReportView(VendorRequiredMixin, PeriodMixin, TemplateView):
    template_name = "reports/vendor_withdrawals.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        withdrawals = VendorWithdrawalRequest.objects.filter(
            vendor=self.request.user,
            requested_at__range=(ctx["start"], ctx["end"]),
        )
        ctx["withdrawals"] = withdrawals[:200]
        ctx["totals"] = dict(
            withdrawals.values_list("status").annotate(s=Sum("amount_transferred")).values_list("status", "s")
        )
        ctx["charges"] = withdrawals.aggregate(t=Sum("withdrawal_charge"))["t"] or 0
        return ctx




