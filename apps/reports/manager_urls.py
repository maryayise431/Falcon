from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "reports"

urlpatterns = [
    path("dashboard/", views.ManagerDashboardStatsView.as_view(), name="manager_dashboard"),
    path("marketplace/", RedirectView.as_view(pattern_name="marketplace:manager_orders", permanent=False), name="marketplace_redirect"),
    path("reports/marketplace/", views.MarketplaceSalesReportView.as_view(), name="report_marketplace"),
    path("reports/fulfillment/", views.VendorFulfillmentReportView.as_view(), name="report_fulfillment"),
    path("reports/revenue/", views.RevenueReportView.as_view(), name="report_revenue"),
    path("reports/daily/", views.DailyReportView.as_view(), name="report_daily"),
    path("reports/weekly/", views.WeeklyReportView.as_view(), name="report_weekly"),
    path("reports/monthly/", views.MonthlyReportView.as_view(), name="report_monthly"),
    path("reports/custom/", views.CustomReportView.as_view(), name="report_custom"),
    path("reports/parcel/", views.ParcelReportView.as_view(), name="report_parcel"),
    path("reports/cod/", views.CODReportView.as_view(), name="report_cod"),
    path("reports/withdrawals/", views.WithdrawalReportView.as_view(), name="report_withdrawals"),
]
