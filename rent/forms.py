from django import forms
from django.utils import timezone
from rent.models import Contractor, Shop, PayType, RentPeriod


# AC-1 and AC-2: Form for adding a new contractor.
class AddContractorForm(forms.Form):

    full_name = forms.CharField(max_length=150)

    staff_id = forms.RegexField(
        regex=r"^[0-9]{4}$",
        max_length=4,
        min_length=4,
        error_messages={
            "invalid": "Staff ID must be exactly 4 digits."
        }
    )

    shop = forms.ModelChoiceField(
        queryset=Shop.objects.all()
    )  # Displays the available shops.

    phone = forms.CharField(
        max_length=20,
        required=False
    )  # Phone number is optional.

    photo = forms.ImageField(
        required=False
    )  # Contractor photo is optional.

    pay_type = forms.ChoiceField(
        choices=PayType.choices,
        initial=PayType.WEEKLY_RENT
    )

    joined_on = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"})
    )  # Records when the contractor joined.


# Form for updating a contractor's personal details.
class EditContractorForm(forms.Form):

    full_name = forms.CharField(max_length=150)

    phone = forms.CharField(
        max_length=20,
        required=False
    )

    photo = forms.ImageField(required=False)


# AC-4: Form for transferring a contractor.
class TransferContractorForm(forms.Form):

    new_shop = forms.ModelChoiceField(
        queryset=Shop.objects.all(),
        label="New shop"
    )  # Allows the Owner to select the destination shop.


# AC-3: Form for changing commission to weekly rent.
class ChangePayTypeForm(forms.Form):

    effective_period = forms.ModelChoiceField(
        queryset=RentPeriod.objects.none(),
        label="Effective rent period"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        next_period = RentPeriod.current().next()

        # Only display the next rent period or later periods.
        self.fields["effective_period"].queryset = (
            RentPeriod.objects.filter(
                start_date__gte=next_period.start_date
            ).order_by("start_date")
        )


# AC-5: Form for assigning a Shop Supervisor.
class ShopSupervisorForm(forms.Form):

    shop = forms.ModelChoiceField(
        queryset=Shop.objects.all()
    )

    contractor = forms.ModelChoiceField(
        queryset=Contractor.objects.filter(is_active=True)
    )  # Only active contractors can become supervisors.


# AC-5: Form for creating a Company Supervisor account.
class CompanySupervisorForm(forms.Form):

    full_name = forms.CharField(max_length=150)

    username = forms.CharField(max_length=150)

    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput
    )  # Hides the password while it is being entered.


# SF-3: Requires confirmation before deactivation.
class DeactivateForm(forms.Form):

    confirm = forms.BooleanField(
        required=True,
        label="I confirm that I want to deactivate this account."
    )