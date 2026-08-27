from django import forms

from apps.core.forms import StyledFormMixin
from apps.core.models import Warehouse

from .models import MarketplaceProduct


class CheckoutForm(StyledFormMixin, forms.Form):
    delivery_method = forms.ChoiceField(
        choices=[("door_delivery", "Door Delivery"), ("pickup", "Warehouse Pickup")],
        widget=forms.RadioSelect(attrs={"class": "delivery-method-radio"}),
        initial="door_delivery",
    )
    delivery_address = forms.CharField(
        widget=forms.TextInput(attrs={"placeholder": "Street, area, city"}),
        required=False,
    )
    receiver_phone = forms.CharField(max_length=20, required=False)
    delivery_address_lat = forms.CharField(required=False, widget=forms.HiddenInput)
    delivery_address_lng = forms.CharField(required=False, widget=forms.HiddenInput)
    pickup_warehouse = forms.IntegerField(required=False, widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("delivery_method")
        if method == "door_delivery":
            if not cleaned.get("delivery_address", "").strip():
                self.add_error("delivery_address", "Please enter a delivery address.")
            if not cleaned.get("receiver_phone", "").strip():
                self.add_error("receiver_phone", "Phone number is required for delivery.")
            cleaned["pickup_warehouse"] = None
        elif method == "pickup":
            cleaned["delivery_address"] = ""
            cleaned["receiver_phone"] = ""
            wh_id = cleaned.get("pickup_warehouse")
            if not wh_id:
                self.add_error("pickup_warehouse", "Please select a warehouse for pickup.")
            else:
                warehouse = Warehouse.objects.filter(id=wh_id, is_active=True).first()
                if not warehouse:
                    self.add_error("pickup_warehouse", "Selected warehouse is not available.")
        return cleaned

    def clean_delivery_address_lat(self):
        val = self.cleaned_data.get("delivery_address_lat", "")
        if val:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return None

    def clean_delivery_address_lng(self):
        val = self.cleaned_data.get("delivery_address_lng", "")
        if val:
            try:
                return float(val)
            except (TypeError, ValueError):
                return None
        return None


class MarketplaceProductForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = MarketplaceProduct
        fields = ["name", "category", "price", "stock", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css} form-input".strip()

    def clean_price(self):
        price = self.cleaned_data["price"]
        if price <= 0:
            raise forms.ValidationError("Price must be greater than zero.")
        return price
