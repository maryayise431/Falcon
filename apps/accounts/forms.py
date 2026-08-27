import re

from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.core.forms import StyledFormMixin
from .models import FalconUser, VendorProfile


CHECK_EMAIL_URL = "/api/check-email/"
CHECK_USERNAME_URL = "/api/check-username/"


class CustomerRegisterForm(StyledFormMixin, forms.Form):
    full_name = forms.CharField(max_length=120, label="Full Name")
    phone_number = forms.CharField(max_length=20, label="Phone Number")
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput, label="Password")
    confirm_password = forms.CharField(
        widget=forms.PasswordInput, label="Confirm Password"
    )

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if FalconUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password"), cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if p1:
            if len(p1) < 8:
                raise forms.ValidationError("Password must be at least 8 characters.")
            validate_password(p1)
        return cleaned


class VendorRegisterForm(CustomerRegisterForm):
    business_name = forms.CharField(max_length=160, label="Business Name")
    username = forms.CharField(
        widget=forms.TextInput(attrs={"data-check-url": CHECK_USERNAME_URL}),
        label="Username",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("full_name", None)
        order = ["business_name", "username", "phone_number", "email", "password", "confirm_password"]
        self.fields = {key: self.fields[key] for key in order if key in self.fields}

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if not re.fullmatch(r"[a-z0-9_.]{3,40}", username):
            raise forms.ValidationError(
                "Username must be 3-40 characters: letters, numbers, dots or underscores."
            )
        if VendorProfile.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken.")
        return username


class LoginForm(StyledFormMixin, forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)


class StaffLoginForm(StyledFormMixin, forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)


class OTPForm(StyledFormMixin, forms.Form):
    otp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "one-time-code"}
        ),
    )


class ForgotPasswordForm(StyledFormMixin, forms.Form):
    email = forms.EmailField()


class SetNewPasswordForm(StyledFormMixin, forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label="New Password")
    confirm_password = forms.CharField(
        widget=forms.PasswordInput, label="Confirm New Password"
    )

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password"), cleaned.get("confirm_password")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError("Passwords do not match.")
        if p1:
            if len(p1) < 8:
                raise forms.ValidationError("Password must be at least 8 characters.")
            validate_password(p1)
        return cleaned
