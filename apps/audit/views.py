from django.db.models import Q
from django.views.generic import ListView

from apps.core.mixins import ManagerOrSubManagerMixin

from .models import AuditLog


class AuditLogListView(ManagerOrSubManagerMixin, ListView):
    template_name = "audit/list.html"
    context_object_name = "logs"
    paginate_by = 30

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        action = self.request.GET.get("action", "")
        if action:
            qs = qs.filter(action=action)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(description__icontains=query)
                | Q(reason__icontains=query)
                | Q(actor__email__icontains=query)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["action_filter"] = self.request.GET.get("action", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["actions"] = AuditLog.ACTION_CHOICES
        return ctx
