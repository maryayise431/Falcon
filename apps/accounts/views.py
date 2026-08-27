from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from apps.audit.services import log_action
from apps.core.mixins import ManagerOrSubManagerMixin, ManagerRequiredMixin
from apps.core.utils import generate_otp, otp_expiry_time

from .emails import (
    send_password_reset_confirmation,
    send_password_reset_otp,
    send_registration_otp,
)
from .forms import (
    CustomerRegisterForm,
    ForgotPasswordForm,
    LoginForm,
    OTPForm,
    SetNewPasswordForm,
    StaffLoginForm,
    VendorRegisterForm,
)
from .models import CustomerProfile, FalconUser, OTPRecord, VendorProfile

PUBLIC_ROLES = {"customer", "vendor"}
STAFF_ROLES = {"manager", "sub_manager", "delivery_agent"}

ROLE_HOME = {
    "customer": "/marketplace/",
    "vendor": "/vendor/dashboard/",
    "delivery_agent": "/agent/dashboard/",
    "manager": "/manager/dashboard/",
    "sub_manager": "/sub-manager/dashboard/",
}


def role_home(role):
    return ROLE_HOME.get(role, "/")


def _create_otp(user, purpose):
    OTPRecord.objects.filter(user=user, purpose=purpose, is_used=False).update(
        is_used=True
    )
    code = generate_otp()
    OTPRecord.objects.create(
        user=user, otp_code=code, purpose=purpose, expires_at=otp_expiry_time()
    )
    return code


class PublicLoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_home(request.user.role))
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["portal"] = "public"
        return ctx

    def form_valid(self, form):
        email = form.cleaned_data["email"].lower().strip()
        password = form.cleaned_data["password"]
        user = FalconUser.objects.filter(email__iexact=email).first()
        if user is None or not check_password(password, user.password):
            form.add_error(None, "Invalid email or password.")
            return self.form_invalid(form)
        if user.role not in PUBLIC_ROLES:
            form.add_error(
                None, "Staff accounts must sign in through the staff portal."
            )
            return self.form_invalid(form)
        if not user.email_verified:
            code = _create_otp(user, OTPRecord.PURPOSE_REGISTRATION)
            send_registration_otp(user, code)
            self.request.session["pending_verification"] = {
                "user_id": user.id,
                "purpose": OTPRecord.PURPOSE_REGISTRATION,
            }
            messages.info(
                self.request,
                "Your email is not verified yet. We have sent you a fresh code.",
            )
            return redirect("accounts:verify_otp")
        if not user.is_active:
            form.add_error(
                None, "This account has been disabled. Please contact support."
            )
            return self.form_invalid(form)
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        log_action(self.request, "login_as_role", user, description=f"{user.get_role_display()} signed in")
        messages.success(self.request, f"Welcome back, {user.email}!")
        return redirect(role_home(user.role))


class StaffLoginView(PublicLoginView):
    template_name = "accounts/staff_login.html"
    form_class = StaffLoginForm

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["portal"] = "staff"
        return ctx

    def form_valid(self, form):
        email = form.cleaned_data["email"].lower().strip()
        password = form.cleaned_data["password"]
        user = FalconUser.objects.filter(email__iexact=email).first()
        if user is None or not check_password(password, user.password):
            form.add_error(None, "Invalid email or password.")
            return self.form_invalid(form)
        if user.role not in STAFF_ROLES and not user.is_superuser:
            form.add_error(
                None, "This portal is for Falcon staff only. Use the public login."
            )
            return self.form_invalid(form)
        if not user.email_verified or not user.is_active:
            form.add_error(None, "This account is not active. Contact an administrator.")
            return self.form_invalid(form)
        login(self.request, user, backend="django.contrib.auth.backends.ModelBackend")
        log_action(self.request, "login_as_role", user, description=f"{user.get_role_display()} signed in via staff portal")
        if user.is_superuser and user.role == FalconUser.ROLE_MANAGER:
            return redirect("/manager/dashboard/")
        return redirect(role_home(user.role))


class RegistrationMixin:
    role = None

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_home(request.user.role))
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        bound = kwargs.get("form")
        if self.role == FalconUser.ROLE_VENDOR:
            ctx["vendor_form"] = bound if isinstance(bound, VendorRegisterForm) else VendorRegisterForm()
            ctx["customer_form"] = CustomerRegisterForm()
            ctx["initial_tab"] = "vendor"
        else:
            ctx["customer_form"] = bound if isinstance(bound, CustomerRegisterForm) else CustomerRegisterForm()
            ctx["vendor_form"] = VendorRegisterForm()
            ctx["initial_tab"] = "customer"
        return ctx

    def form_valid(self, form):
        role = self.role
        email = form.cleaned_data["email"]
        password = form.cleaned_data["password"]
        user = FalconUser.objects.create_user(
            email=email,
            password=password,
            role=role,
            is_active=False,
            email_verified=False,
        )
        if role == FalconUser.ROLE_CUSTOMER:
            CustomerProfile.objects.create(
                user=user,
                full_name=form.cleaned_data["full_name"],
                phone_number=form.cleaned_data["phone_number"],
            )
        else:
            VendorProfile.objects.create(
                user=user,
                business_name=form.cleaned_data["business_name"],
                username=form.cleaned_data["username"],
                contact_name=form.cleaned_data.get("business_name", ""),
                phone_number=form.cleaned_data["phone_number"],
            )
        code = _create_otp(user, OTPRecord.PURPOSE_REGISTRATION)
        send_registration_otp(user, code)
        self.request.session["pending_verification"] = {
            "user_id": user.id,
            "purpose": OTPRecord.PURPOSE_REGISTRATION,
        }
        log_action(self.request, "user_created", user, description=f"{role} registered: {email}")
        messages.success(
            self.request,
            "Account created! Check your email for the 6-digit verification code.",
        )
        return redirect("accounts:verify_otp")


class CustomerRegisterView(RegistrationMixin, FormView):
    role = FalconUser.ROLE_CUSTOMER
    template_name = "accounts/register.html"
    form_class = CustomerRegisterForm
    success_url = reverse_lazy("accounts:verify_otp")


class VendorRegisterView(RegistrationMixin, FormView):
    role = FalconUser.ROLE_VENDOR
    template_name = "accounts/register.html"
    form_class = VendorRegisterForm
    success_url = reverse_lazy("accounts:verify_otp")


def _pending_user(request):
    data = request.session.get("pending_verification")
    if not data:
        return None
    return FalconUser.objects.filter(id=data.get("user_id")).first()


class VerifyOTPView(FormView):
    template_name = "accounts/verify_otp.html"
    form_class = OTPForm
    success_url = "/"

    def dispatch(self, request, *args, **kwargs):
        self.pending_user = _pending_user(request)
        if not self.pending_user:
            messages.warning(request, "No verification in progress. Please sign up or log in.")
            return redirect("accounts:login")
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        return {}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["pending_email"] = self.pending_user.email
        return ctx

    def form_valid(self, form):
        code = form.cleaned_data["otp_code"].strip()
        record = (
            OTPRecord.objects.filter(
                user=self.pending_user,
                purpose=OTPRecord.PURPOSE_REGISTRATION,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )
        if record is None or not record.is_valid():
            form.add_error(None, "This code has expired. Request a new one.")
            return self.form_invalid(form)
        if record.otp_code != code:
            form.add_error(None, "Incorrect code. Please try again.")
            return self.form_invalid(form)
        record.is_used = True
        record.save()
        self.pending_user.is_active = True
        self.pending_user.email_verified = True
        self.pending_user.save(update_fields=["is_active", "email_verified"])
        if self.pending_user.role == FalconUser.ROLE_VENDOR:
            VendorProfile.objects.filter(user=self.pending_user).update(is_verified=True)
        del self.request.session["pending_verification"]
        login(
            self.request,
            self.pending_user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        messages.success(
            self.request, "Email verified! Welcome to Falcon Delivery Service."
        )
        return redirect(role_home(self.pending_user.role))

    def post(self, request, *args, **kwargs):
        if "resend" in request.POST:
            code = _create_otp(
                self.pending_user, OTPRecord.PURPOSE_REGISTRATION
            )
            send_registration_otp(self.pending_user, code)
            messages.info(request, "A new verification code has been sent to your email.")
            return redirect("accounts:verify_otp")
        return super().post(request, *args, **kwargs)


class ForgotPasswordView(FormView):
    template_name = "accounts/forgot_password.html"
    form_class = ForgotPasswordForm
    success_url = reverse_lazy("accounts:reset_password_verify")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_home(request.user.role))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        email = form.cleaned_data["email"].lower().strip()
        user = FalconUser.objects.filter(email__iexact=email).first()
        if user and user.role in PUBLIC_ROLES:
            code = _create_otp(user, OTPRecord.PURPOSE_PASSWORD_RESET)
            send_password_reset_otp(user, code)
            self.request.session["pending_verification"] = {
                "user_id": user.id,
                "purpose": OTPRecord.PURPOSE_PASSWORD_RESET,
            }
        messages.info(
            self.request,
            "If that email belongs to a customer or vendor account, a reset code has been sent.",
        )
        return super().form_valid(form)


class ResetPasswordOTPView(FormView):
    template_name = "accounts/reset_password_verify.html"
    form_class = OTPForm
    success_url = reverse_lazy("accounts:set_new_password")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_home(request.user.role))
        self.pending_user = _pending_user(request)
        if not self.pending_user:
            messages.warning(request, "Start the password reset from the beginning.")
            return redirect("accounts:forgot_password")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        code = form.cleaned_data["otp_code"].strip()
        record = (
            OTPRecord.objects.filter(
                user=self.pending_user,
                purpose=OTPRecord.PURPOSE_PASSWORD_RESET,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )
        if record is None or not record.is_valid():
            form.add_error(None, "This code has expired. Request a new one.")
            return self.form_invalid(form)
        if record.otp_code != code:
            form.add_error(None, "Incorrect code. Please try again.")
            return self.form_invalid(form)
        record.is_used = True
        record.save()
        self.request.session["reset_user_id"] = self.pending_user.id
        del self.request.session["pending_verification"]
        return redirect(self.success_url)

    def post(self, request, *args, **kwargs):
        if "resend" in request.POST:
            code = _create_otp(self.pending_user, OTPRecord.PURPOSE_PASSWORD_RESET)
            send_password_reset_otp(self.pending_user, code)
            messages.info(request, "A new reset code has been sent to your email.")
            return redirect("accounts:reset_password_verify")
        return super().post(request, *args, **kwargs)


class SetNewPasswordView(FormView):
    template_name = "accounts/set_new_password.html"
    form_class = SetNewPasswordForm
    success_url = reverse_lazy("accounts:login")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(role_home(request.user.role))
        if not request.session.get("reset_user_id"):
            messages.warning(request, "Verify your identity first.")
            return redirect("accounts:forgot_password")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = FalconUser.objects.filter(
            id=self.request.session["reset_user_id"]
        ).first()
        if not user:
            messages.error(self.request, "Account not found.")
            return redirect("accounts:forgot_password")
        user.set_password(form.cleaned_data["password"])
        user.save()
        send_password_reset_confirmation(user)
        del self.request.session["reset_user_id"]
        log_action(self.request, "user_updated", user, description="Password reset completed")
        messages.success(self.request, "Password updated! You can now sign in.")
        return redirect(self.success_url)


class LogoutView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return redirect("/")
        return render(request, "accounts/logout_confirm.html")

    def post(self, request):
        logout(request)
        messages.info(request, "You have been signed out.")
        return redirect("/")


def api_check_email(request):
    email = (request.GET.get("email") or "").strip().lower()
    exists = FalconUser.objects.filter(email__iexact=email).exists() if email else False
    valid_format = "@" in email and "." in email.split("@")[-1]
    return JsonResponse({"exists": exists, "valid": bool(valid_format)})


def api_check_username(request):
    username = (request.GET.get("username") or "").strip().lower()
    exists = (
        VendorProfile.objects.filter(username__iexact=username).exists()
        if username
        else False
    )
    return JsonResponse({"exists": exists})


class ManagerUserListView(ManagerOrSubManagerMixin, ListView):
    template_name = "manager/users.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        qs = FalconUser.objects.all().order_by("-date_joined")
        role = self.request.GET.get("role", "").strip()
        if role:
            qs = qs.filter(role=role)
        query = self.request.GET.get("q", "").strip()
        if query:
            qs = qs.filter(
                Q(email__icontains=query)
                | Q(customerprofile__full_name__icontains=query)
                | Q(vendorprofile__business_name__icontains=query)
                | Q(deliveryagentprofile__full_name__icontains=query)
            )
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["role_choices"] = FalconUser.ROLE_CHOICES
        ctx["active_role"] = self.request.GET.get("role", "")
        ctx["search_query"] = self.request.GET.get("q", "")
        return ctx


class ManagerUserToggleActiveView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(FalconUser, pk=pk)
        if user.pk == request.user.pk:
            messages.error(request, "You cannot disable your own account.")
            return redirect("manager_users")
        previous = {"is_active": user.is_active}
        user.is_active = not user.is_active
        user.save(update_fields=["is_active"])
        log_action(
            request,
            "user_disabled" if not user.is_active else "user_enabled",
            user,
            description=f"{user.email} {'disabled' if not user.is_active else 're-enabled'} by {request.user.email}",
            previous_value=previous,
            new_value={"is_active": user.is_active},
        )
        messages.success(
            request,
            f"{user.email} has been {'disabled' if not user.is_active else 're-enabled'}.",
        )
        return redirect("manager_users")


class ManagerUserDeleteView(ManagerRequiredMixin, View):
    def post(self, request, pk):
        user = get_object_or_404(FalconUser, pk=pk)
        if user.pk == request.user.pk:
            messages.error(request, "You cannot delete your own account.")
            return redirect("manager_users")
        if user.is_superuser and not FalconUser.objects.filter(
            is_superuser=True
        ).exclude(pk=user.pk).exists():
            messages.error(request, "Cannot delete the last superuser.")
            return redirect("manager_users")
        email = user.email
        try:
            with transaction.atomic():
                log_action(
                    request,
                    "user_deleted",
                    None,
                    description=f"{email} deleted by {request.user.email}",
                )
                user.delete()
        except ProtectedError:
            messages.error(
                request,
                f"{email} has order or wallet records that must be preserved. "
                "Disable the account instead.",
            )
            return redirect("manager_users")
        messages.success(request, f"{email} deleted.")
        return redirect("manager_users")
