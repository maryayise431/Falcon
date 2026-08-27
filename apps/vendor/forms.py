from decimal import Decimal

from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.validators import NubanValidator, NigerianPhoneValidator, validate_positive_amount

from .models import VendorFulfillmentOrder, VendorProduct


class VendorProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = VendorProduct
        fields = ["name", "description", "price", "image", "customer_location", "quantity_available"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "price": forms.NumberInput(attrs={"min": "0", "step": "0.01", "placeholder": "0.00"}),
            "quantity_available": forms.NumberInput(attrs={"min": "1", "placeholder": "e.g. 50"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price"].localize = True
        self.fields["price"].widget.is_localized = True
        self.fields["name"].widget.attrs.setdefault("placeholder", "e.g. iPhone 15 Pro")
        self.fields["quantity_available"].widget.attrs.setdefault("placeholder", "e.g. 50")

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Product name is required.")
        return name

    def clean_quantity_available(self):
        qty = self.cleaned_data.get("quantity_available")
        if qty is None:
            raise forms.ValidationError("Quantity is required.")
        if qty <= 0:
            raise forms.ValidationError("Quantity must be at least 1.")
        return qty


class VendorOrderForm(forms.Form):
    product = forms.ModelChoiceField(queryset=VendorProduct.objects.none())
    quantity = forms.IntegerField(min_value=1)
    customer_name = forms.CharField(max_length=120)
    customer_phone = forms.CharField(validators=[NigerianPhoneValidator()], required=False)
    customer_whatsapp = forms.CharField(validators=[NigerianPhoneValidator()], required=False)
    customer_address = forms.CharField(
        widget=forms.TextInput(attrs={"placeholder": "Street, area, city"})
    )
    customer_address_lat = forms.CharField(required=False, widget=forms.HiddenInput)
    customer_address_lng = forms.CharField(required=False, widget=forms.HiddenInput)
    delivery_instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, vendor=None, **kwargs):
        super().__init__(*args, **kwargs)
        if vendor is not None:
            self.fields["product"].queryset = VendorProduct.objects.filter(
                vendor=vendor, status=VendorProduct.STATUS_RECEIVED
            )
        self.fields["product"].label_from_instance = lambda obj: obj.name
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-input".strip()


class BankAccountForm(StyledFormMixin, forms.Form):
    bank_name = forms.CharField(max_length=120)
    bank_code = forms.CharField()
    account_number = forms.CharField(validators=[NubanValidator()])
    account_name = forms.CharField(max_length=160, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["bank_code"].widget = forms.HiddenInput()
        self.fields["bank_name"].widget = forms.HiddenInput()
        self.fields["account_name"].widget = forms.TextInput(attrs={"readonly": True})

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("account_name", "").strip():
            self.add_error("account_name", "Please verify your account first.")
        return cleaned

    def save(self, profile):
        profile.bank_name = self.cleaned_data["bank_name"]
        profile.bank_code = self.cleaned_data["bank_code"]
        profile.bank_account_number = self.cleaned_data["account_number"]
        profile.account_name = self.cleaned_data["account_name"]
        profile.bank_verified = True
        profile.save(
            update_fields=[
                "bank_name",
                "bank_code",
                "bank_account_number",
                "account_name",
                "bank_verified",
            ]
        )
        return profile


class WithdrawalForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        validate_positive_amount(amount)
        if amount <= Decimal("250"):
            raise forms.ValidationError("Amount must be greater than the \u20a6250 withdrawal charge.")
        return amount


class ManagerDeliveryFeeForm(StyledFormMixin, forms.Form):
    delivery_fee = forms.DecimalField(max_digits=12, decimal_places=2)

    def clean_delivery_fee(self):
        fee = self.cleaned_data["delivery_fee"]
        if fee < 0:
            raise forms.ValidationError("Delivery fee cannot be negative.")
        return fee


class ManagerDeductWalletForm(StyledFormMixin, forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2)
    reason = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")
        reason = cleaned.get("reason", "").strip()
        if amount is not None and amount <= 0:
            self.add_error("amount", "Deduction amount must be greater than zero.")
        if not reason:
            self.add_error("reason", "A reason is required for every manual deduction.")
        return cleaned
