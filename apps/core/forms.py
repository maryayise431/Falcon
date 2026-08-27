from django import forms


class StyledFormMixin:
    """Adds the shared ``form-input`` styling hook to every visible widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if getattr(widget, "input_type", "") == "hidden" or isinstance(
                widget, forms.CheckboxInput
            ):
                continue
            existing = widget.attrs.get("class", "")
            if "form-input" not in existing:
                widget.attrs["class"] = f"{existing} form-input".strip()
