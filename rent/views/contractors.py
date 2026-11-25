"""US-05 Manage contractors and shop assignments - Jordon Stewart."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404

from rent.access import role_required
from rent.models import Contractor, Shop, User, Role, RentPeriod
from rent.services import contractors as services

from rent.forms import (
    AddContractorForm,
    EditContractorForm,
    TransferContractorForm,
    ChangePayTypeForm,
    ShopSupervisorForm,
    CompanySupervisorForm,
    DeactivateForm,
)


# Only the Owner can access this page.
@role_required(Role.OWNER)
def contractors(request):

    if request.method == "POST":

        action = request.POST.get("action")

        try:

            # AC-1 and AC-2: Add a contractor.
            if action == "add":

                form = AddContractorForm(request.POST, request.FILES)

                if form.is_valid():

                    contractor = services.add_contractor(
                        **form.cleaned_data
                    )

                    messages.success(
                        request,
                        f"{contractor.full_name} added successfully."
                    )

                    # Display the new contractor's initial login details.
                    return render(request, "rent/contractor_created.html", {
                        "contractor": contractor,
                        "initial_password": contractor.initial_password,
                    })

            # Update contractor details.
            elif action == "edit":

                contractor = get_object_or_404(
                    Contractor,
                    pk=request.POST.get("contractor_id")
                )

                form = EditContractorForm(
                    request.POST, request.FILES
                )

                if form.is_valid():

                    services.update_contractor(
                        contractor=contractor,
                        **form.cleaned_data
                    )

                    messages.success(request, "Contractor updated successfully.")

                    return redirect("contractors")

            # AC-4: Transfer a contractor.
            elif action == "transfer":

                contractor = get_object_or_404(
                    Contractor,
                    pk=request.POST.get("contractor_id")
                )

                form = TransferContractorForm(request.POST)

                if form.is_valid():

                    services.transfer(
                        contractor=contractor,
                        **form.cleaned_data
                    )

                    messages.success(
                        request,
                        "Transfer scheduled for the next rent period."
                    )

                    return redirect("contractors")

            # AC-3: Change commission to weekly rent.
            elif action == "change_pay_type":

                contractor = get_object_or_404(
                    Contractor,
                    pk=request.POST.get("contractor_id")
                )

                form = ChangePayTypeForm(request.POST)

                if form.is_valid():

                    services.change_pay_type(
                        contractor=contractor,
                        **form.cleaned_data
                    )

                    messages.success(
                        request,
                        "Payment type change scheduled successfully."
                    )

                    return redirect("contractors")

            # AC-5: Assign a Shop Supervisor.
            elif action == "set_supervisor":

                form = ShopSupervisorForm(request.POST)

                if form.is_valid():

                    services.set_shop_supervisor(
                        **form.cleaned_data
                    )

                    messages.success(
                        request,
                        "Shop Supervisor assigned successfully."
                    )

                    return redirect("contractors")

            # AC-6 and SF-3: Deactivate a contractor.
            elif action == "deactivate":

                contractor = get_object_or_404(
                    Contractor,
                    pk=request.POST.get("contractor_id")
                )

                form = DeactivateForm(request.POST)

                # Deactivation requires confirmation.
                if form.is_valid():

                    services.deactivate(contractor=contractor)

                    messages.success(
                        request,
                        "Contractor deactivated successfully."
                    )

                    return redirect("contractors")

            # AC-5: Create a Company Supervisor account.
            elif action == "create_company_supervisor":

                form = CompanySupervisorForm(request.POST)

                if form.is_valid():

                    services.create_company_supervisor(
                        **form.cleaned_data
                    )

                    messages.success(
                        request,
                        "Company Supervisor created successfully."
                    )

                    return redirect("contractors")

            # AC-5: Deactivate the Company Supervisor.
            elif action == "deactivate_company_supervisor":

                supervisor = get_object_or_404(
                    User,
                    pk=request.POST.get("user_id"),
                    role=Role.COMPANY_SUPERVISOR
                )

                form = DeactivateForm(request.POST)

                if form.is_valid():

                    services.deactivate_company_supervisor(
                        user=supervisor
                    )

                    messages.success(
                        request,
                        "Company Supervisor deactivated successfully."
                    )

                    return redirect("contractors")

            else:
                messages.error(request, "Invalid action.")
                return redirect("contractors")

            # Display validation errors from the submitted form.
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")

        except ValidationError as error:

            # Display errors returned by the business logic.
            for message in error.messages:
                messages.error(request, message)

    # Retrieve the information displayed on the Contractors page.
    contractor_list = Contractor.objects.select_related("shop", "user")
    current_period = RentPeriod.current()

    # Get each contractor's current shop and payment type.
    for contractor in contractor_list:

        contractor.current_shop = services.shop_for(
            contractor, current_period
        )

        contractor.current_pay_type = services.pay_type_for(
            contractor, current_period
        )

    context = {
        "contractors": contractor_list,
        "shops": Shop.objects.all(),

        "company_supervisors": User.objects.filter(
            role=Role.COMPANY_SUPERVISOR
        ),

        "add_form": AddContractorForm(),
        "edit_form": EditContractorForm(),
        "transfer_form": TransferContractorForm(),
        "pay_type_form": ChangePayTypeForm(),
        "supervisor_form": ShopSupervisorForm(),
        "company_form": CompanySupervisorForm(),
        "deactivate_form": DeactivateForm(),

        "current_period": current_period,
    }

    return render(request, "rent/contractors.html", context)