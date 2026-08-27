from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied


class RoleRequiredMixin(LoginRequiredMixin):
    allowed_roles = set()

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and self.allowed_roles:
            if request.user.role not in self.allowed_roles:
                raise PermissionDenied(
                    "Your account does not have access to this area."
                )
        return super().dispatch(request, *args, **kwargs)


class ManagerRequiredMixin(RoleRequiredMixin):
    allowed_roles = {"manager"}


class ManagerOrSubManagerMixin(RoleRequiredMixin):
    allowed_roles = {"manager", "sub_manager"}


class ReadOnlySubManagerMixin(ManagerOrSubManagerMixin):
    def post(self, request, *args, **kwargs):
        if request.user.role == "sub_manager":
            raise PermissionDenied("Sub-Managers have read-only access.")
        parent_post = getattr(super(), "post", None)
        if parent_post is not None:
            return parent_post(request, *args, **kwargs)
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["GET"])


class VendorRequiredMixin(RoleRequiredMixin):
    allowed_roles = {"vendor"}


class CustomerRequiredMixin(RoleRequiredMixin):
    allowed_roles = {"customer"}


class CustomerOrVendorRequiredMixin(RoleRequiredMixin):
    allowed_roles = {"customer", "vendor"}


class AgentRequiredMixin(RoleRequiredMixin):
    allowed_roles = {"delivery_agent"}
