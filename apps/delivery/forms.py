from django import forms

from apps.core.forms import StyledFormMixin


class AgentPickupForm(StyledFormMixin, forms.Form):
    pickup_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))


class AgentDeliverForm(StyledFormMixin, forms.Form):
    cod_collected = forms.DecimalField(max_digits=12, decimal_places=2)
    delivery_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean_cod_collected(self):
        amount = self.cleaned_data["cod_collected"]
        if amount < 0:
            raise forms.ValidationError("COD amount cannot be negative.")
        return amount


class ParcelDeliverForm(StyledFormMixin, forms.Form):
    delivery_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Delivery notes (optional)"}),
    )


class AgentFailForm(StyledFormMixin, forms.Form):
    failure_reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 2}),
        error_messages={"required": "Please describe why the delivery failed."},
    )
