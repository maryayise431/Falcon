from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import Group as DjangoGroup
from django.contrib.auth.models import User as LegacyUser

from .models import (
    DeliveryAgentProfile,
    FalconUser,
    ManagerProfile,
    SubManagerProfile,
)

for _legacy in (LegacyUser, DjangoGroup):
    try:
        admin.site.unregister(_legacy)
    except admin.sites.NotRegistered:
        pass


STAFF_ROLE_CHOICES = [
    (value, label)
    for value, label in FalconUser.ROLE_CHOICES
    if value in FalconUser.STAFF_ROLES
]


class StaffUserCreationForm(UserCreationForm):
    full_name = forms.CharField(
        max_length=120,
        label="Full Name",
        help_text="Official name of this staff member.",
    )
    role = forms.TypedChoiceField(
        label="Type of Staff",
        choices=STAFF_ROLE_CHOICES,
        help_text="Manager, Sub-Manager or Delivery Agent. Staff accounts can only be "
        "created here.",
    )
    agent_address = forms.CharField(
        label="Delivery Agent Address",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Required for delivery agents. Residential base address of the agent.",
    )

    class Meta:
        model = FalconUser
        fields = ("email",)

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        address = cleaned.get("agent_address", "")
        if role == FalconUser.ROLE_AGENT and not address.strip():
            self.add_error("agent_address", "Address is required for delivery agents.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = self.cleaned_data["role"]
        user.email_verified = True
        if commit:
            user.save()
        return user


class ManagerProfileInline(admin.StackedInline):
    model = ManagerProfile
    fields = ("full_name",)
    can_delete = False
    verbose_name_plural = "Manager Profile"

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_MANAGER

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_MANAGER


class SubManagerProfileInline(admin.StackedInline):
    model = SubManagerProfile
    fields = ("full_name",)
    can_delete = False
    verbose_name_plural = "Sub-Manager Profile"

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_SUB_MANAGER

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_SUB_MANAGER


class DeliveryAgentProfileInline(admin.StackedInline):
    model = DeliveryAgentProfile
    fields = ("full_name", "phone_number", "assigned_zone", "address", "is_available")
    can_delete = False
    verbose_name_plural = "Delivery Agent Profile"

    def has_add_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_AGENT

    def has_change_permission(self, request, obj=None):
        return obj is None or obj.role == FalconUser.ROLE_AGENT


@admin.register(FalconUser)
class FalconUserAdmin(BaseUserAdmin):
    add_form = StaffUserCreationForm
    ordering = ("-date_joined",)
    list_display = (
        "email",
        "role",
        "is_active",
        "email_verified",
        "date_joined",
    )
    list_filter = ("role", "is_active")
    search_fields = ("email",)
    readonly_fields = ("last_login", "date_joined")

    add_fieldsets = (
        (
            "Create Staff Account",
            {
                "classes": ("wide",),
                "fields": (
                    "full_name",
                    "email",
                    "role",
                    "password1",
                    "password2",
                    "agent_address",
                ),
            },
        ),
    )
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Role", {"fields": ("role",)}),
        ("Status", {"fields": ("is_active", "email_verified")}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )

    class Media:
        js = ("js/admin_staff_form.js",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs.filter(role__in=FalconUser.STAFF_ROLES)
        return qs.filter(role__in=FalconUser.STAFF_ROLES).exclude(pk=request.user.pk)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "role":
            kwargs["choices"] = STAFF_ROLE_CHOICES
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        mapping = {
            FalconUser.ROLE_MANAGER: ManagerProfileInline,
            FalconUser.ROLE_SUB_MANAGER: SubManagerProfileInline,
            FalconUser.ROLE_AGENT: DeliveryAgentProfileInline,
        }
        inline_cls = mapping.get(obj.role)
        if inline_cls is None:
            return []
        return [inline_cls(self.model, self.admin_site)]

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        if not change:
            full_name = form.cleaned_data.get("full_name", "").strip()
            if obj.role == FalconUser.ROLE_MANAGER:
                ManagerProfile.objects.update_or_create(
                    user=obj, defaults={"full_name": full_name}
                )
            elif obj.role == FalconUser.ROLE_SUB_MANAGER:
                SubManagerProfile.objects.update_or_create(
                    user=obj, defaults={"full_name": full_name}
                )
            elif obj.role == FalconUser.ROLE_AGENT:
                agent_addr = form.cleaned_data.get("agent_address", "").strip()
                DeliveryAgentProfile.objects.update_or_create(
                    user=obj,
                    defaults={
                        "full_name": full_name,
                        "address": agent_addr,
                    },
                )
                if agent_addr:
                    from apps.core.models import Warehouse
                    agent_name = full_name or obj.email.split("@")[0]
                    code = "AG-" + obj.email.split("@")[0].upper()[:6]
                    wh, _ = Warehouse.objects.update_or_create(
                        code=code,
                        defaults={
                            "name": agent_name,
                            "address": agent_addr,
                            "city": "",
                            "state": "",
                            "is_active": True,
                        },
                    )
                    DeliveryAgentProfile.objects.filter(user=obj).update(warehouse=wh)
        role_model = {
            FalconUser.ROLE_MANAGER: ManagerProfile,
            FalconUser.ROLE_SUB_MANAGER: SubManagerProfile,
            FalconUser.ROLE_AGENT: DeliveryAgentProfile,
        }.get(obj.role)
        for model in (ManagerProfile, SubManagerProfile, DeliveryAgentProfile):
            if model is not role_model:
                model.objects.filter(user=obj).delete()

    def has_module_permission(self, request):
        return request.user.is_authenticated and request.user.role in FalconUser.STAFF_ROLES

    def has_add_permission(self, request):
        return request.user.role == FalconUser.ROLE_MANAGER or request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.role == FalconUser.ROLE_MANAGER or request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return True
