from django import forms


class StyledFormMixin:
    """Give every text-like widget the design-system `input` class."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput, forms.RadioSelect, forms.CheckboxSelectMultiple, forms.HiddenInput)):
                continue
            widget.attrs["class"] = (widget.attrs.get("class", "") + " input").strip()
