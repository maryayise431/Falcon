import csv
from datetime import timedelta

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.utils.timezone import localdate
from django.views.generic import TemplateView

from apps.accounts.models import FalconUser
from apps.core.period import PERIOD_CHOICES, parse_period_from_request
from apps.delivery.models import DeliveryAssignment
from apps.marketplace.models import MarketplaceOrder, MarketplaceOrderItem
from apps.parcel.models import ParcelRequest
from apps.vendor.models import (
    VendorFulfillmentOrder,
    VendorWalletTransaction,
    VendorWithdrawalRequest,
)


class PeriodMixin:
    default_period = "this_month"

    def get_period_context(self, default=None):
        period, start, end = parse_period_from_request(
            self.request, default or self.default_period
        )
        return {
            "period": period,
            "period_choices": PERIOD_CHOICES,
            "start": start,
            "end": end,
            "start_date": start.date(),
            "end_date": end.date() - timedelta(days=1),
            "querystring": self.request.GET.urlencode(),
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self.get_period_context())
        return ctx


class CSVExportMixin:
    csv_filename = "falcon_report"

    def get(self, request, *args, **kwargs):
        if request.GET.get("export") == "csv":
            ctx = self.get_context_data(**kwargs)
            payload = self.csv_payload(ctx)
            if payload is not None:
                headers, rows = payload
                return self.render_csv_response(headers, rows)
        return super().get(request, *args, **kwargs)

    def csv_payload(self, ctx):
        return None

    def render_csv_response(self, headers, rows):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{self.csv_filename}.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return response


def revenue_breakdown(start, end):
    from django.db.models import F

    marketplace_revenue = (
        MarketplaceOrderItem.objects.filter(
            order__created_at__range=(start, end),
            order__payment__status="success",
        ).aggregate(
            total=Sum(Coalesce(F("line_total"), F("unit_price") * F("quantity")))
        )["total"]
    ) or 0
    delivery_fees = (
        VendorWalletTransaction.objects.filter(
            created_at__range=(start, end),
            transaction_type=VendorWalletTransaction.TYPE_DELIVERY_FEE,
        ).aggregate(t=Sum("amount"))["t"]
    ) or 0
    parcel_revenue = (
        ParcelRequest.objects.filter(
            paid_at__range=(start, end), payment_status="paid"
        ).aggregate(t=Sum("delivery_fee"))["t"]
    ) or 0
    withdrawal_charges = (
        VendorWalletTransaction.objects.filter(
            created_at__range=(start, end),
            transaction_type=VendorWalletTransaction.TYPE_WITHDRAWAL_FEE,
        ).aggregate(t=Sum("amount"))["t"]
    ) or 0
    cod_handled = (
        DeliveryAssignment.objects.filter(
            delivered_at__range=(start, end),
            status="delivered",
            cod_confirmed=True,
        ).aggregate(t=Sum("cod_collected"))["t"]
    ) or 0
    rows = [
        ("Marketplace Sales", marketplace_revenue),
        ("Fulfilment Delivery Fees", delivery_fees),
        ("Parcel Delivery Fees", parcel_revenue),
        ("Withdrawal Charges", withdrawal_charges),
    ]
    total = sum(amount for _, amount in rows)
    return {
        "rows": rows,
        "total": total,
        "cod_handled": cod_handled,
    }

