
"""
Data layer for the Campus Cuts Rent Tracking System.

Models follow SDS section 2.3.1 / 3.1:
User, Shop, Contractor, ShopAssignment, RentSetting, RentPeriod,
Payment, PaymentCorrection, Handoff, Receipt.

Business rules go in rent/services/.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


# ---------------------------------------------------------------------------
# Users and roles (SE-1, SE-2)
# ---------------------------------------------------------------------------

class Role(models.TextChoices):
    OWNER = "OWNER", "Owner"
    COMPANY_SUPERVISOR = "COMPANY_SUPERVISOR", "Company Supervisor"
    SHOP_SUPERVISOR = "SHOP_SUPERVISOR", "Shop Supervisor"
    CONTRACTOR = "CONTRACTOR", "Independent Contractor"


class User(AbstractUser):
    """Every user has exactly one role (SE-2).

    A Shop Supervisor is also an independent contractor, so a Shop Supervisor
    user has a Contractor profile as well (see Contractor.user).
    """

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.CONTRACTOR)

    @property
    def is_owner(self):
        return self.role == Role.OWNER

    @property
    def is_company_supervisor(self):
        return self.role == Role.COMPANY_SUPERVISOR

    @property
    def is_shop_supervisor(self):
        return self.role == Role.SHOP_SUPERVISOR

    @property
    def is_contractor(self):
        """True for anyone who pays rent (contractors and Shop Supervisors)."""
        return hasattr(self, "contractor_profile")

    @property
    def supervised_shop(self):
        """The shop this user supervises, or None."""
        if not self.is_shop_supervisor:
            return None
        return Shop.objects.filter(supervisor__user=self).first()

    def __str__(self):
        return self.get_full_name() or self.username


# ---------------------------------------------------------------------------
# Shops and rent settings (US-02)
# ---------------------------------------------------------------------------

class Campus(models.TextChoices):
    UWI = "UWI", "UWI"
    UTECH = "UTECH", "UTech"


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Monday"
    TUESDAY = 1, "Tuesday"
    WEDNESDAY = 2, "Wednesday"
    THURSDAY = 3, "Thursday"
    FRIDAY = 4, "Friday"
    SATURDAY = 5, "Saturday"
    SUNDAY = 6, "Sunday"


class Shop(models.Model):
    name = models.CharField(max_length=100, unique=True)
    campus = models.CharField(max_length=10, choices=Campus.choices)

    # One Shop Supervisor per shop (US-05 AC-5).
    supervisor = models.OneToOneField(
        "Contractor", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="supervised_shop",
    )

    class Meta:
        ordering = ["campus", "name"]

    def __str__(self):
        return self.name


class RentSetting(models.Model):
    """Weekly rent and due day for a shop, from a given rent period onward.

    A new row is added for each change, so the rent for any past period can
    always be looked up (US-02 AC-4, QA-2). Use RentSetting.for_shop().
    """

    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="rent_settings")

    weekly_rent = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )

    due_day = models.IntegerField(choices=Weekday.choices)

    effective_from = models.ForeignKey(
        "RentPeriod", on_delete=models.PROTECT,
        related_name="rent_settings_started"
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["shop", "-effective_from__start_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["shop", "effective_from"],
                name="one_setting_per_shop_per_period"
            ),
        ]

    @classmethod
    def for_shop(cls, shop, period):
        """The setting in force for the shop during the rent period."""
        return (
            cls.objects.filter(
                shop=shop,
                effective_from__start_date__lte=period.start_date
            )
            .order_by("-effective_from__start_date")
            .first()
        )

    def __str__(self):
        return f"{self.shop}: ${self.weekly_rent:,.0f} due {self.get_due_day_display()} from {self.effective_from}"


# ---------------------------------------------------------------------------
# Rent periods (SRS section 4: one week, Monday to Sunday)
# ---------------------------------------------------------------------------

class RentPeriod(models.Model):
    start_date = models.DateField(unique=True)  # Always a Monday
    end_date = models.DateField()  # Always the Sunday after

    class Meta:
        ordering = ["-start_date"]

    @staticmethod
    def monday_of(d: date) -> date:
        return d - timedelta(days=d.weekday())

    @classmethod
    def for_date(cls, d: date) -> "RentPeriod":
        """Get or create the rent period that contains date d."""
        start = cls.monday_of(d)

        period, _ = cls.objects.get_or_create(
            start_date=start,
            defaults={"end_date": start + timedelta(days=6)}
        )

        return period

    @classmethod
    def current(cls) -> "RentPeriod":
        from django.utils import timezone
        return cls.for_date(timezone.localdate())

    def next(self) -> "RentPeriod":
        return RentPeriod.for_date(self.start_date + timedelta(days=7))

    def due_date_for(self, due_day: int) -> date:
        """Returns the due date for the rent period (US-02 AC-3)."""
        return self.start_date + timedelta(days=due_day)

    def __str__(self):
        # Uses .day instead of %-d for Windows compatibility.
        return f"{self.start_date.day} {self.start_date:%b} to {self.end_date.day} {self.end_date:%b %Y}"


# ---------------------------------------------------------------------------
# Independent contractors (US-05)
# ---------------------------------------------------------------------------

class PayType(models.TextChoices):
    WEEKLY_RENT = "RENT", "Weekly rent"
    COMMISSION = "COMMISSION", "Commission (60:40)"


class Trade(models.TextChoices):
    BARBER = "BARBER", "Barber"
    HAIRSTYLIST = "HAIRSTYLIST", "Hairstylist"
    NAIL_TECH = "NAIL_TECH", "Nail technician"


staff_id_validator = RegexValidator(
    r"^\d{4}$",
    "Staff ID must be exactly 4 digits."
)


class Contractor(models.Model):
    """An independent contractor who pays rent. Shop Supervisors are contractors too."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="contractor_profile"
    )

    full_name = models.CharField(max_length=150)

    staff_id = models.CharField(
        max_length=4,
        unique=True,
        validators=[staff_id_validator]
    )

    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        related_name="contractors"
    )

    trade = models.CharField(
        max_length=20,
        choices=Trade.choices,
        default=Trade.BARBER
    )

    phone = models.CharField(max_length=20, blank=True)

    photo = models.ImageField(
        upload_to="contractor_photos/",
        blank=True
    )

    pay_type = models.CharField(
        max_length=20,
        choices=PayType.choices,
        default=PayType.WEEKLY_RENT
    )

    # Deactivated contractors keep their records and outstanding balances.
    is_active = models.BooleanField(default=True)

    deactivated_on = models.DateField(
        null=True,
        blank=True
    )  # Records when the contractor left (US-05 AC-6).

    # The Owner sets the date when adding a contractor.
    joined_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["shop", "full_name"]

    @property
    def is_shop_supervisor(self):
        return hasattr(self, "supervised_shop") and self.supervised_shop is not None

    def __str__(self):
        return f"{self.full_name} ({self.staff_id})"


# ---------------------------------------------------------------------------
# Shop assignment history (US-05 AC-3 and AC-4)
# ---------------------------------------------------------------------------

class ShopAssignment(models.Model):
    """Stores previous and new shop assignments and payment types."""

    contractor = models.ForeignKey(
        Contractor,
        on_delete=models.PROTECT,
        related_name="assignments"
    )  # Links the assignment to an independent contractor.

    shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT
    )  # Stores the shop the contractor is assigned to.

    pay_type = models.CharField(
        max_length=20,
        choices=PayType.choices,
        default=PayType.WEEKLY_RENT
    )  # Preserves whether the contractor paid rent or commission.

    effective_from = models.DateField()  # Date the assignment takes effect.

    class Meta:
        ordering = ["-effective_from"]  # Newest assignments appear first.

        constraints = [
            models.UniqueConstraint(
                fields=["contractor", "effective_from"],
                name="unique_contractor_assignment_date"
            ),
        ]  # Prevents duplicate assignments starting on the same date.

    def __str__(self):
        return f"{self.contractor} - {self.shop}"


# ---------------------------------------------------------------------------
# Payments and corrections (US-01, SF-1)
# ---------------------------------------------------------------------------

class NoDeleteQuerySet(models.QuerySet):
    def delete(self):
        raise PermissionDenied(
            "Payments and handoffs can never be deleted (SF-1)."
        )


class NoDeleteModel(models.Model):
    """Base class that blocks deletion of the record (SF-1 / SDS DeletionGuard)."""

    objects = NoDeleteQuerySet.as_manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise PermissionDenied(
            "Payments and handoffs can never be deleted (SF-1)."
        )


class Payment(NoDeleteModel):
    """One cash payment from a contractor for one rent period (US-01 AC-1).

    Amount and payment_date hold the current corrected values.
    The original values are kept in PaymentCorrection rows.
    """

    contractor = models.ForeignKey(
        Contractor,
        on_delete=models.PROTECT,
        related_name="payments"
    )

    rent_period = models.ForeignKey(
        RentPeriod,
        on_delete=models.PROTECT,
        related_name="payments"
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )

    payment_date = models.DateField()

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments_recorded"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-payment_date", "-created_at"]

    @property
    def is_corrected(self):
        return self.corrections.exists()

    def __str__(self):
        return f"${self.amount:,.0f} from {self.contractor.full_name} for {self.rent_period}"


class PaymentCorrection(NoDeleteModel):
    """A change to a payment, keeping the original details (US-01 AC-7)."""

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="corrections"
    )

    old_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    new_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    old_payment_date = models.DateField()
    new_payment_date = models.DateField()
    reason = models.CharField(max_length=255)

    corrected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    corrected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-corrected_at"]


class CommissionEarning(models.Model):
    """Earnings entered for a contractor on commission (US-01 AC-6).

    Amount owed for that period is 40% of earnings.
    """

    contractor = models.ForeignKey(
        Contractor,
        on_delete=models.PROTECT,
        related_name="commission_earnings"
    )

    rent_period = models.ForeignKey(
        RentPeriod,
        on_delete=models.PROTECT
    )

    earnings = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))]
    )

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    entered_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["contractor", "rent_period"],
                name="one_earning_per_contractor_per_period"
            ),
        ]


# ---------------------------------------------------------------------------
# Handoffs (US-03)
# ---------------------------------------------------------------------------

class HandoffStep(models.TextChoices):
    SHOP_TO_COMPANY = "SHOP_TO_CS", "Shop Supervisor to Company Supervisor"
    COMPANY_TO_OWNER = "CS_TO_OWNER", "Company Supervisor to Owner"


class HandoffStatus(models.TextChoices):
    AWAITING = "AWAITING", "Awaiting confirmation"
    CONFIRMED = "CONFIRMED", "Confirmed"


class Handoff(NoDeleteModel):
    """Cash handed over for one rent period, at one step of the chain."""

    step = models.CharField(
        max_length=20,
        choices=HandoffStep.choices
    )

    # Empty for Company Supervisor to Owner handoffs.
    shop = models.ForeignKey(
        Shop,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="handoffs"
    )

    rent_period = models.ForeignKey(
        RentPeriod,
        on_delete=models.PROTECT,
        related_name="handoffs"
    )

    expected_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    amount_handed = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))]
    )

    handed_date = models.DateField()

    handed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="handoffs_given"
    )

    amount_received = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="handoffs_confirmed"
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=HandoffStatus.choices,
        default=HandoffStatus.AWAITING
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-rent_period__start_date", "step", "shop"]

        constraints = [
            # One handoff per shop per period.
            models.UniqueConstraint(
                fields=["shop", "rent_period", "step"],
                name="one_shop_handoff_per_period",
                condition=Q(step="SHOP_TO_CS")
            ),

            # One Company Supervisor to Owner handoff per period.
            models.UniqueConstraint(
                fields=["rent_period", "step"],
                name="one_owner_handoff_per_period",
                condition=Q(step="CS_TO_OWNER")
            ),
        ]

    @property
    def is_mismatch(self):
        """Flags a handoff if the amounts differ (US-03 AC-5)."""

        if self.amount_handed != self.expected_amount:
            return True

        return (
            self.amount_received is not None
            and self.amount_received != self.expected_amount
        )

    def __str__(self):
        where = self.shop or "All shops"
        return f"{where} - {self.get_step_display()} - {self.rent_period}"


# ---------------------------------------------------------------------------
# Receipts (US-07)
# ---------------------------------------------------------------------------

class Receipt(models.Model):

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="receipts"
    )

    # Balance still owed immediately after the payment.
    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    is_corrected = models.BooleanField(default=False)

    corrects = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="corrected_by_receipts"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def number(self):
        """Six-digit receipt number, e.g. 000123."""
        return f"{self.pk:06d}" if self.pk else "------"

    def __str__(self):
        return f"Receipt {self.number}"
