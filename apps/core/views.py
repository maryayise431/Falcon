from django.views.generic import TemplateView

from apps.marketplace.models import MarketplaceProduct, ProductCategory


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        products = MarketplaceProduct.objects.filter(is_published=True).select_related(
            "category"
        )
        ctx["featured_products"] = products[:4]
        ctx["product_count"] = products.count()
        ctx["categories"] = ProductCategory.objects.all()[:6]
        return ctx


class TermsView(TemplateView):
    template_name = "core/terms.html"


class PrivacyView(TemplateView):
    template_name = "core/privacy.html"
