from django.views.generic import RedirectView


class MarketplaceHomeRedirectView(RedirectView):
    permanent = False

    def get_redirect_url(self, *args, **kwargs):
        return "/manager/marketplace/orders/"
