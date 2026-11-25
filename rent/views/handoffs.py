"""US-03 Record and confirm handoffs - owner: Chiantina Lawrence"""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from rent.access import role_required
from rent.models import (
    Handoff,
    HandoffStep,
    HandoffStatus,
    RentPeriod,
    Role,
)
from rent.services import handoffs as handoff_service

# How many recent weeks the period list offers. Older weeks are rare and keep the list short.
RECENT_WEEKS = 8


class PeriodChoiceField(forms.ModelChoiceField):
    """Rent period select that marks the current week."""

    current = None

    def label_from_instance(self, period):
        label = str(period)
        if self.current is not None and period.pk == self.current.pk:
            label += " (this week)"
        return label


class PeriodSelect(forms.Select):
    """Each option carries the expected amount for that week, so the page can show it as the period changes."""

    expected = None

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        key = getattr(value, "value", value)
        if self.expected and key in self.expected:
            option["attrs"]["data-expected"] = f"{self.expected[key]:.2f}"
        return option


class HandoffForm(forms.Form):
    compare_noun = ""  # how the difference note names the expected amount
    """Shared by both handoff steps.

    The period list only offers weeks that have started and have not been handed over yet,
    newest first, and starts on the newest one. The amount starts at what the system expects
    for that week, and the date at today (future dates are refused here and in the service).
    """

    period = PeriodChoiceField(
        queryset=RentPeriod.objects.none(),
        label="Rent period",
        empty_label="Choose a rent period",
        widget=PeriodSelect,
    )
    # The amount handed over must be a positive number with up to two decimal places.
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        label="Amount handed over",
        error_messages={
            "min_value": "The amount is invalid."
        },
        widget=forms.NumberInput(attrs={"autocomplete": "off", "inputmode": "decimal", "step": "0.01", "min": "0.01"}),
    )
    # The date the cash changed hands. Defaults to today; later dates are not allowed.
    handed_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date handed over",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        current = RentPeriod.current()

        handed = self.handed_periods()
        open_ids = list(
            RentPeriod.objects.filter(start_date__lte=today)
            .exclude(pk__in=handed)
            .order_by("-start_date")
            .values_list("pk", flat=True)[:RECENT_WEEKS]
        )
        periods = RentPeriod.objects.filter(pk__in=open_ids).order_by("-start_date")

        field = self.fields["period"]
        field.queryset = periods
        field.current = current
        self.expected = {period.pk: self.expected_for(period) for period in periods}
        field.widget.expected = self.expected

        self.fields["handed_date"].widget.attrs["max"] = today.isoformat()
        self.fields["amount"].widget.attrs["aria-describedby"] = "handoff-diff"

        amount_attrs = self.fields["amount"].widget.attrs
        amount_attrs.update({"data-diff-id": "handoff-diff", "data-compare-noun": self.compare_noun, "data-flag": "1"})

        first = periods.first()
        self.has_open_periods = first is not None
        if not self.is_bound:
            self.initial.setdefault("handed_date", today)
            if first is not None:
                self.initial.setdefault("period", first.pk)
                expected = self.expected[first.pk]
                if expected > 0:
                    self.initial.setdefault("amount", int(expected) if expected == expected.to_integral_value() else expected)

        # Read the chosen period only now: a bound field caches its initial value on first read.
        if self.selected_expected is not None:
            amount_attrs["data-expected"] = f"{self.selected_expected:.2f}"

    def handed_periods(self):
        raise NotImplementedError

    def expected_for(self, period):
        raise NotImplementedError

    @property
    def selected_expected(self):
        """Expected amount for the period currently chosen (posted or initial), for the page to show."""
        value = self["period"].value()
        try:
            return self.expected.get(int(value))
        except (TypeError, ValueError):
            return None

    def flag_errors(self):
        """Point each field with an error at the message shown under it (screen readers read both)."""
        for name in self.errors:
            if name in self.fields:
                attrs = self.fields[name].widget.attrs
                attrs["aria-invalid"] = "true"
                described = f"{self[name].auto_id}-error {attrs.get('aria-describedby', '')}"
                attrs["aria-describedby"] = described.strip()


# Form used by Shop Supervisors to record cash handed to the Company Supervisor.
class ShopHandoffForm(HandoffForm):
    compare_noun = "you recorded in rent"

    def __init__(self, *args, shop=None, **kwargs):
        self.shop = shop
        super().__init__(*args, **kwargs)

    def handed_periods(self):
        if self.shop is None:
            return []
        return Handoff.objects.filter(step=HandoffStep.SHOP_TO_COMPANY, shop=self.shop).values("rent_period")

    def expected_for(self, period):
        if self.shop is None:
            return Decimal("0.00")
        return handoff_service.expected_shop_amount(self.shop, period)


# Form used by the Company Supervisor to record cash handed to the Owner.
class OwnerHandoffForm(HandoffForm):
    compare_noun = "you confirmed from the shops"

    def handed_periods(self):
        return Handoff.objects.filter(step=HandoffStep.COMPANY_TO_OWNER).values("rent_period")

    def expected_for(self, period):
        return handoff_service.expected_owner_amount(period)


# Form used by the receiving person to enter the amount actually received.
class ConfirmHandoffForm(forms.Form):
    # The amount handed over must be a positive number with up to two decimal places.
    amount_received = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=0.01,
        label="Amount actually received",
        error_messages={
            "min_value": "The amount is invalid."
        },
    )


# Only these three roles are allowed to access the handoff page.
@role_required(
    Role.SHOP_SUPERVISOR,
    Role.COMPANY_SUPERVISOR,
    Role.OWNER,
)
def handoffs(request):
    """Display handoffs and process the actions allowed for each role."""

    # Make sure a current rent period exists.
    RentPeriod.current()

    user = request.user

    # Create empty forms for displaying on the page. Each role only sees its own form.
    is_shop_supervisor = user.role == Role.SHOP_SUPERVISOR
    is_company_supervisor = user.role == Role.COMPANY_SUPERVISOR
    shop = user.supervised_shop if is_shop_supervisor else None
    shop_form = ShopHandoffForm(shop=shop) if is_shop_supervisor else None
    owner_form = OwnerHandoffForm() if is_company_supervisor else None

    # Check whether the user submitted a form.
    if request.method == "POST":
        action = request.POST.get("action")

        # Handle a Shop Supervisor recording a shop handoff.
        if action == "record_shop":
            form = ShopHandoffForm(request.POST, shop=shop)

            # Only Shop Supervisors can record shop handoffs.
            if user.role != Role.SHOP_SUPERVISOR:
                messages.error(
                    request, "You cannot record a shop handoff."
                )
                return redirect("handoffs")

            # Check that all submitted form information is valid.
            if form.is_valid():
                try:
                    # Call the service function to apply the business rules
                    # and save the shop handoff.
                    handoff_service.record_shop_handoff(
                        shop=shop,
                        period=form.cleaned_data["period"],
                        amount=form.cleaned_data["amount"],
                        handed_date=form.cleaned_data["handed_date"],
                        handed_by=user,
                    )
                    messages.success(
                        request, "Shop handoff recorded successfully."
                    )
                    return redirect("handoffs")

                except ValidationError as error:
                    # Errors from the service land on the field they are about.
                    form.add_error(None, error)

            # Keep the submitted form so the user can see any errors next to their fields.
            shop_form = form
            for error in form.non_field_errors():
                messages.error(request, error)

        # Handle the Company Supervisor recording a handoff to the Owner.
        elif action == "record_owner":
            form = OwnerHandoffForm(request.POST)

             # Only the Company Supervisor can record this handoff.
            if user.role != Role.COMPANY_SUPERVISOR:
                messages.error(
                    request, "You cannot record an owner handoff."
                )
                return redirect("handoffs")

            if form.is_valid():
                try:
                    # Call the service function to calculate the expected
                    # amount and save the owner handoff.
                    handoff_service.record_owner_handoff(
                        period=form.cleaned_data["period"],
                        amount=form.cleaned_data["amount"],
                        handed_date=form.cleaned_data["handed_date"],
                        handed_by=user,
                    )
                    messages.success(
                        request, "Owner handoff recorded successfully."
                    )
                    return redirect("handoffs")

                except ValidationError as error:
                    form.add_error(None, error)

            # Keep the submitted form and show any errors next to their fields.
            owner_form = form
            for error in form.non_field_errors():
                messages.error(request, error)

        # Handle confirmation of an existing handoff.
        elif action == "confirm":
            # Retrieve the handoff using its ID.
            # If it does not exist, Django returns a 404 response.
            handoff = get_object_or_404(
                Handoff,
                pk=request.POST.get("handoff_id"),
            )
            data = request.POST.copy()
            # "Received exactly $X": the one-tap button confirms the amount handed over.
            if data.get("received_exact"):
                data["amount_received"] = str(handoff.amount_handed)
            form = ConfirmHandoffForm(data)

            if form.is_valid():
                try:
                    # Call the service function to check the user's role,
                    # save the amount received and update the confirmation details.
                    handoff_service.confirm_handoff(
                        handoff=handoff,
                        amount_received=form.cleaned_data[
                            "amount_received"
                        ],
                        confirmed_by=user,
                    )
                    messages.success(
                        request, "Handoff confirmed successfully."
                    )
                    return redirect("handoffs")

                except ValidationError as error:
                    for message in error.messages:
                        messages.error(request, message)

            else:
                # Display errors if the confirmation form is invalid.
                for field_errors in form.errors.values():
                    for error in field_errors:
                        messages.error(request, error)

        else:
            # Handle an unrecognised form action.
            messages.error(request, "Invalid handoff action.")

    # Shop Supervisors only see their own shop's handoffs.
    handoff_list = Handoff.objects.select_related(
        "shop",
        "rent_period",
        "handed_by",
        "confirmed_by",
    )

    # Shop Supervisors can only view handoffs belonging to their own shop.
    if is_shop_supervisor:
        if shop is None:
            handoff_list = handoff_list.none()
        else:
            handoff_list = handoff_list.filter(shop=shop)

    for form in (shop_form, owner_form):
        if form is not None:
            form.flag_errors()

    # Split out the handoffs this user has to confirm, so they come first on the page.
    is_owner = user.role == Role.OWNER

    def waiting_on_me(h):
        if h.status != HandoffStatus.AWAITING:
            return False
        return (is_company_supervisor and h.step == HandoffStep.SHOP_TO_COMPANY) or (
            is_owner and h.step == HandoffStep.COMPANY_TO_OWNER)

    waiting = [h for h in handoff_list if waiting_on_me(h)]
    records = [h for h in handoff_list if not waiting_on_me(h)]
    record_form = shop_form or owner_form
    # The record form starts folded away while something is waiting to be confirmed,
    # unless it is showing errors from a submit.
    form_open = record_form is not None and (not waiting or record_form.is_bound)

    # Pass the handoff records, forms and role information to the template.
    context = {
        "waiting": waiting,
        "records": records,
        "form_open": form_open,
        "shop_form": shop_form,
        "owner_form": owner_form,
        "shop_step": HandoffStep.SHOP_TO_COMPANY,
        "owner_step": HandoffStep.COMPANY_TO_OWNER,
        "awaiting_status": HandoffStatus.AWAITING,
        "is_shop_supervisor": is_shop_supervisor,
        "is_company_supervisor": is_company_supervisor,
        "is_owner": is_owner,
    }

     # Display the handoff page with the information passed in the context.
    return render(request, "rent/handoffs.html", context)
