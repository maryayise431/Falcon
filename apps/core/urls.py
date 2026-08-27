from django.urls import path

from .views import HomeView, PrivacyView, TermsView

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("terms/", TermsView.as_view(), name="terms"),
    path("privacy/", PrivacyView.as_view(), name="privacy"),
]
