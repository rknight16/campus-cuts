from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (CommissionEarning, Contractor, Handoff, Payment,
                     PaymentCorrection, Receipt, RentPeriod, RentSetting, Shop, User)


@admin.register(User)
class CampusUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Campus Cuts", {"fields": ("role",)}),)
    list_display = ("username", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active")


class NoDeleteAdmin(admin.ModelAdmin):
    """SF-1: payments and handoffs can never be deleted, even from the admin."""
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(NoDeleteAdmin):
    list_display = ("contractor", "rent_period", "amount", "payment_date", "recorded_by")
    list_filter = ("contractor__shop", "rent_period")


@admin.register(PaymentCorrection)
class PaymentCorrectionAdmin(NoDeleteAdmin):
    list_display = ("payment", "old_amount", "new_amount", "reason", "corrected_by", "corrected_at")


@admin.register(Handoff)
class HandoffAdmin(NoDeleteAdmin):
    list_display = ("rent_period", "step", "shop", "expected_amount", "amount_handed", "amount_received", "status")


@admin.register(Contractor)
class ContractorAdmin(admin.ModelAdmin):
    list_display = ("full_name", "staff_id", "shop", "trade", "pay_type", "is_active")
    list_filter = ("shop", "pay_type", "is_active")
    search_fields = ("full_name", "staff_id")


admin.site.register([Shop, RentSetting, RentPeriod, Receipt, CommissionEarning])
