from django.contrib.auth import views as auth_views
from django.urls import path

from rent.views import (account, contractors, dashboard, handoffs, home,
                        payments, receipts, rent_settings)

urlpatterns = [
    path("", home.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="rent/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    path("owner/", home.owner_home, name="owner_home"),
    path("company/", home.company_home, name="company_home"),
    path("supervisor/", home.supervisor_home, name="supervisor_home"),

    # US-01 Raynardo
    path("payments/record/", payments.record_payment, name="record_payment"),
    path("payments/<int:payment_id>/correct/",
         payments.correct_payment, name="correct_payment"),
    # US-02 Jordon Mingoes
    path("rent-settings/", rent_settings.rent_settings, name="rent_settings"),
    # US-03 Chiantina
    path("handoffs/", handoffs.handoffs, name="handoffs"),
    # US-04 Dylandre
    path("dashboard/", dashboard.dashboard, name="dashboard"),
    # US-05 Jordon Stewart
    path("contractors/", contractors.contractors, name="contractors"),
    # US-06 Raynardo
    path("account/", account.my_account, name="my_account"),
    path("account/<int:contractor_id>/",
         account.contractor_account, name="contractor_account"),
    # US-07 Jordon Mingoes
    path("receipts/", receipts.receipts, name="receipts"),
    path("receipts/<int:receipt_id>/",
         receipts.receipt_detail, name="receipt_detail"),
]
