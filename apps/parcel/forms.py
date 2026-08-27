from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.validators import NigerianPhoneValidator

from .models import ParcelRequest


class ParcelRequestForm(forms.ModelForm):
    class Meta:
        model = ParcelRequest
        fields = [
            "pickup_type",
            "dropoff_warehouse",
            "sender_name",
            "sender_phone",
            "pickup_address",
            "receiver_name",
            "receiver_phone",
            "receiver_address",
            "parcel_type",
            "parcel_image",
            "parcel_description",
            "delivery_instructions",
        ]
        widgets = {
            "pickup_address": forms.TextInput(
                attrs={"placeholder": "Street, area, city"}
            ),
            "receiver_address": forms.TextInput(
                attrs={"placeholder": "Street, area, city"}
            ),
            "parcel_description": forms.Textarea(attrs={"rows": 3}),
            "delivery_instructions": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["dropoff_warehouse"].queryset = (
            self.fields["dropoff_warehouse"].queryset.filter(is_active=True)
        )
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-input".strip()

    def clean(self):
        cleaned = super().clean()
        pickup_type = cleaned.get("pickup_type")
        if pickup_type == ParcelRequest.PICKUP and not cleaned.get("pickup_address"):
            self.add_error("pickup_address", "Pickup address is required for pickups.")
        if pickup_type == ParcelRequest.DROP_OFF and not cleaned.get("dropoff_warehouse"):
            self.add_error(
                "dropoff_warehouse", "Choose the warehouse you will drop off at."
            )
        return cleaned


class ParcelQuoteForm(StyledFormMixin, forms.Form):
    delivery_fee = forms.DecimalField(max_digits=12, decimal_places=2)
    quote_note = forms.CharField(max_length=255, required=False)

    def clean_delivery_fee(self):
        fee = self.cleaned_data["delivery_fee"]
        if fee <= 0:
            raise forms.ValidationError("Quote must be greater than zero.")
        return fee
