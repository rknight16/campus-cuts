"""US-03 Record and confirm handoffs - owner: Chiantina Lawrence"""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from rent.access import role_required
from rent.models import (
    Handoff,
    HandoffStep,
    HandoffStatus,
    RentPeriod,
    Role,
)
from rent.services import handoffs as handoff_service

# Form used by Shop Supervisors to record cash handed to the Company Supervisor.
class ShopHandoffForm(forms.Form):
    period = forms.ModelChoiceField(
        queryset=RentPeriod.objects.none(),
        label="Rent period",
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
    )
    # Allows the user to select the date the handoff took place.
    handed_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date handed over",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load the available rent periods, showing the newest ones first.
        self.fields["period"].queryset = RentPeriod.objects.order_by(
            "-start_date"
        )


# Form used by the Company Supervisor to record cash handed to the Owner.
class OwnerHandoffForm(forms.Form):
    period = forms.ModelChoiceField(
        queryset=RentPeriod.objects.none(),
        label="Rent period",
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
    )
    # Allows the user to select the date the handoff took place.
    handed_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Date handed over",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Load the available rent periods, showing the newest ones first.
        self.fields["period"].queryset = RentPeriod.objects.order_by(
            "-start_date"
        )


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

    # Create empty forms for displaying on the page.
    shop_form = ShopHandoffForm()
    owner_form = OwnerHandoffForm()

    # Check whether the user submitted a form.
    if request.method == "POST":
        action = request.POST.get("action")

        # Handle a Shop Supervisor recording a shop handoff.
        if action == "record_shop":
            form = ShopHandoffForm(request.POST)

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
                        shop=user.supervised_shop,
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
                    # Display any validation errors returned by the service.
                    for message in error.messages:
                        form.add_error(None, message)

            # Keep the submitted form so the user can see any errors.
            shop_form = form

            for field_errors in form.errors.values():
                for error in field_errors:
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
                    for message in error.messages:
                        form.add_error(None, message)

            # Keep the submitted form and display any errors.
            owner_form = form

            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)

        # Handle confirmation of an existing handoff.
        elif action == "confirm":
            # Retrieve the handoff using its ID.
            # If it does not exist, Django returns a 404 response.
            handoff = get_object_or_404(
                Handoff,
                pk=request.POST.get("handoff_id"),
            )
            form = ConfirmHandoffForm(request.POST)

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
    if user.role == Role.SHOP_SUPERVISOR:
        shop = user.supervised_shop

        if shop is None:
            handoff_list = handoff_list.none()
        else:
            handoff_list = handoff_list.filter(shop=shop)

    # Pass the handoff records, forms and role information to the template.
    context = {
        "handoffs": handoff_list,
        "shop_form": shop_form,
        "owner_form": owner_form,
        "shop_step": HandoffStep.SHOP_TO_COMPANY,
        "owner_step": HandoffStep.COMPANY_TO_OWNER,
        "awaiting_status": HandoffStatus.AWAITING,
        "is_shop_supervisor": user.role == Role.SHOP_SUPERVISOR,
        "is_company_supervisor": user.role == Role.COMPANY_SUPERVISOR,
        "is_owner": user.role == Role.OWNER,
    }

     # Display the handoff page with the information passed in the context.
    return render(request, "rent/handoffs.html", context)
