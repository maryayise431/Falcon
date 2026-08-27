from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from apps.accounts import views as accounts_views
from apps.delivery.views import ManagerDeliveryOverrideView

# Plan-canonical aliases (Phase 12 routing table) -> live namespaced routes.
ALIASES = [
    ("manager/marketplace/products/", "marketplace:manager_products"),
    ("manager/marketplace/orders/", "marketplace:manager_orders"),
    ("manager/vendor-orders/", "vendor:manager_vendor_orders"),
    ("manager/parcels/", "parcel:manager_list"),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.accounts.urls")),
    path("marketplace/", include("apps.marketplace.urls")),
    path("customer/", include("apps.marketplace.customer_urls")),
    path("vendor/", include("apps.vendor.urls")),
    path("vendor/reports/", include("apps.reports.vendor_urls")),
    path("agent/", include("apps.delivery.agent_urls")),
    path("track/", include("apps.delivery.public_urls")),
    path("parcel/", include("apps.parcel.urls")),
    path(
        "manager/delivery-override/<str:ref>/delivered/",
        ManagerDeliveryOverrideView.as_view(action_type="delivered"),
        name="manager_delivery_delivered",
    ),
    path(
        "manager/delivery-override/<str:ref>/failed/",
        ManagerDeliveryOverrideView.as_view(action_type="failed"),
        name="manager_delivery_failed",
    ),
    path(
        "manager/users/",
        accounts_views.ManagerUserListView.as_view(),
        name="manager_users",
    ),
    path(
        "manager/users/<int:pk>/toggle-active/",
        accounts_views.ManagerUserToggleActiveView.as_view(),
        name="manager_user_toggle",
    ),
    path(
        "manager/users/<int:pk>/delete/",
        accounts_views.ManagerUserDeleteView.as_view(),
        name="manager_user_delete",
    ),
    path("manager/", include("apps.reports.manager_urls")),
    path("manager/audit/", include("apps.audit.urls")),
    path("sub-manager/", include("apps.reports.submanager_urls")),
    path("api/verify-bank/", RedirectView.as_view(pattern_name="vendor:api_verify_bank", permanent=False)),
]

urlpatterns[:0] = [
    path(p, RedirectView.as_view(pattern_name=n, permanent=False)) for p, n in ALIASES
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
