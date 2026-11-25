"""US-05 Contractor Management Tests - Jordon Stewart."""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.urls import reverse

from rent.models import (
    Contractor,
    User,
    Role,
    PayType,
    RentPeriod,
    Shop,
    Campus,
    RentSetting,
    Weekday,
    CommissionEarning,
    Payment,
)

from rent.services import contractors
from rent.services import rent_rules
from rent.services import payments
from rent.tests.helpers import make_world, PASSWORD


class ContractorTests(TestCase):

    def setUp(self):
        # Use the shared test data required by the README.
        self.w = make_world()

    # AC-1: Owner adds an independent contractor.
    def test_ac1_add_contractor(self):

        contractor = contractors.add_contractor(
            full_name="Test Contractor",
            staff_id="4433",
            shop=self.w.taylor,
            joined_on=date(2026, 11, 2)
        )

        self.assertEqual(contractor.staff_id, "4433")
        self.assertEqual(contractor.shop, self.w.taylor)
        self.assertEqual(contractor.user.username, "c4433")
        self.assertEqual(contractor.user.role, Role.CONTRACTOR)
        self.assertTrue(contractor.is_active)

        # Check that the generated login works.
        user = authenticate(
            username="c4433",
            password=contractor.initial_password
        )

        self.assertIsNotNone(user)

    # AC-2: Reject a duplicate staff ID.
    def test_ac2_duplicate_staff_id(self):

        contractors.add_contractor(
            full_name="First Contractor",
            staff_id="4433",
            shop=self.w.taylor
        )

        count = Contractor.objects.count()

        with self.assertRaises(ValidationError):
            contractors.add_contractor(
                full_name="Second Contractor",
                staff_id="4433",
                shop=self.w.utech
            )

        # No additional contractor should be created.
        self.assertEqual(Contractor.objects.count(), count)

    # AC-2: Reject staff IDs that are not exactly four digits.
    def test_ac2_invalid_staff_id(self):

        for staff_id in ["123", "12345", "abcd", "12ab"]:

            with self.subTest(staff_id=staff_id):

                with self.assertRaises(ValidationError):
                    contractors.add_contractor(
                        full_name="Invalid Contractor",
                        staff_id=staff_id,
                        shop=self.w.taylor
                    )

    # AC-2: Reject missing required information.
    def test_ac2_missing_required_fields(self):

        invalid_details = [
            {
                "full_name": "",
                "staff_id": "4433",
                "shop": self.w.taylor
            },
            {
                "full_name": "Test Contractor",
                "staff_id": "",
                "shop": self.w.taylor
            },
            {
                "full_name": "Test Contractor",
                "staff_id": "4433",
                "shop": None
            }
        ]

        for details in invalid_details:

            with self.subTest(details=details):

                with self.assertRaises(ValidationError):
                    contractors.add_contractor(**details)

    # Test updating a contractor's personal details.
    def test_update_contractor(self):

        contractor = self.w.taylor_c

        contractors.update_contractor(
            contractor=contractor,
            full_name="Updated Name",
            phone="8765550100"
        )

        contractor.refresh_from_db()

        self.assertEqual(contractor.full_name, "Updated Name")
        self.assertEqual(contractor.phone, "8765550100")

    # AC-3: Move from commission to weekly rent.
    def test_ac3_commission_to_weekly_rent(self):

        # Create the Students' Union shop from the SRS scenario.
        shop = Shop.objects.create(
            name="UWI Students' Union",
            campus=Campus.UWI
        )

        RentSetting.objects.create(
            shop=shop,
            weekly_rent=Decimal("18000.00"),
            due_day=Weekday.FRIDAY,
            effective_from=self.w.period,
            created_by=self.w.owner
        )

        contractor = contractors.add_contractor(
            full_name="Commission Contractor",
            staff_id="4433",
            shop=shop,
            pay_type=PayType.COMMISSION,
            joined_on=date(2026, 11, 2)
        )

        # Commission is 40% of $30,000, which is $12,000.
        CommissionEarning.objects.create(
            contractor=contractor,
            rent_period=self.w.period,
            earnings=Decimal("30000.00"),
            entered_by=self.w.taylor_sup.user
        )

        next_period = self.w.period.next()

        # Simulate the Owner making the change on November 4.
        with patch(
            "django.utils.timezone.localdate",
            return_value=date(2026, 11, 4)
        ):
            contractors.change_pay_type(
                contractor=contractor,
                effective_period=next_period
            )

        # Previous week must remain on commission.
        self.assertEqual(
            rent_rules.amount_owed(contractor, self.w.period),
            Decimal("12000.00")
        )

        # The following week must use weekly rent.
        self.assertEqual(
            rent_rules.amount_owed(contractor, next_period),
            Decimal("18000.00")
        )

    # AC-4: Transfer contractor from Taylor Hall to UTech.
    def test_ac4_transfer_preserves_previous_rent(self):

        contractor = self.w.taylor_c

        # Simulate a transfer on Wednesday, November 4.
        with patch(
            "django.utils.timezone.localdate",
            return_value=date(2026, 11, 4)
        ):
            contractors.transfer(
                contractor=contractor,
                new_shop=self.w.utech
            )

        old_period = self.w.period
        next_period = old_period.next()

        # November 2-8 must remain assigned to Taylor Hall.
        self.assertEqual(
            contractors.shop_for(contractor, old_period),
            self.w.taylor
        )

        self.assertEqual(
            rent_rules.amount_owed(contractor, old_period),
            Decimal("15000.00")
        )

        # November 9-15 must use the UTech assignment.
        self.assertEqual(
            contractors.shop_for(contractor, next_period),
            self.w.utech
        )

        self.assertEqual(
            rent_rules.amount_owed(contractor, next_period),
            Decimal("12000.00")
        )

    # AC-5: Replace the existing Shop Supervisor.
    def test_ac5_replace_shop_supervisor(self):

        old_supervisor = self.w.taylor_sup
        new_supervisor = self.w.taylor_c

        contractors.set_shop_supervisor(
            shop=self.w.taylor,
            contractor=new_supervisor
        )

        self.w.taylor.refresh_from_db()
        old_supervisor.user.refresh_from_db()
        new_supervisor.user.refresh_from_db()

        # The new contractor becomes supervisor.
        self.assertEqual(
            self.w.taylor.supervisor,
            new_supervisor
        )

        self.assertEqual(
            new_supervisor.user.role,
            Role.SHOP_SUPERVISOR
        )

        # The previous supervisor loses the role.
        self.assertEqual(
            old_supervisor.user.role,
            Role.CONTRACTOR
        )

    # AC-5: Create a Company Supervisor account.
    def test_ac5_create_company_supervisor(self):

        contractors.deactivate_company_supervisor(
            user=self.w.company
        )

        user = contractors.create_company_supervisor(
            full_name="New Company Supervisor",
            username="newcompany",
            password="testpassword123"
        )

        self.assertEqual(user.role, Role.COMPANY_SUPERVISOR)
        self.assertTrue(user.is_active)

        self.assertTrue(
            user.check_password("testpassword123")
        )

    # AC-5: Only one active Company Supervisor.
    def test_ac5_duplicate_company_supervisor(self):

        with self.assertRaises(ValidationError):

            contractors.create_company_supervisor(
                full_name="Another Supervisor",
                username="anothercompany",
                password="testpassword123"
            )

    # AC-5: Deactivate the Company Supervisor.
    def test_ac5_deactivate_company_supervisor(self):

        contractors.deactivate_company_supervisor(
            user=self.w.company
        )

        self.w.company.refresh_from_db()

        self.assertFalse(self.w.company.is_active)

        # The account must still exist.
        self.assertTrue(
            User.objects.filter(pk=self.w.company.pk).exists()
        )

        # The deactivated supervisor cannot log in.
        self.assertIsNone(
            authenticate(
                username=self.w.company.username,
                password=PASSWORD
            )
        )

    # AC-6: Preserve outstanding rent after deactivation.
    def test_ac6_deactivation_preserves_balance(self):

        contractor = self.w.taylor_c

        # Contractor pays $10,000 and still owes $5,000.
        payments.record_payment(
            contractor=contractor,
            period=self.w.period,
            amount=Decimal("10000.00"),
            payment_date=date(2026, 11, 6),
            recorded_by=self.w.taylor_sup.user
        )

        with patch(
            "django.utils.timezone.localdate",
            return_value=date(2026, 11, 8)
        ):
            contractors.deactivate(contractor=contractor)

        contractor.refresh_from_db()

        self.assertFalse(contractor.is_active)
        self.assertFalse(contractor.user.is_active)

        # Existing balance must remain unchanged.
        self.assertEqual(
            rent_rules.balance(contractor, self.w.period),
            Decimal("5000.00")
        )

        # No additional rent should be charged next week.
        self.assertEqual(
            rent_rules.amount_owed(
                contractor,
                self.w.period.next()
            ),
            Decimal("0.00")
        )

        # The remaining $5,000 can still be paid.
        payments.record_payment(
            contractor=contractor,
            period=self.w.period,
            amount=Decimal("5000.00"),
            payment_date=date(2026, 11, 9),
            recorded_by=self.w.taylor_sup.user
        )

        self.assertEqual(
            rent_rules.balance(contractor, self.w.period),
            Decimal("0.00")
        )

        # Both payment records must remain in the database.
        self.assertEqual(
            Payment.objects.filter(contractor=contractor).count(),
            2
        )

    # AC-6: Deactivated contractors cannot log in.
    def test_ac6_deactivated_contractor_login(self):

        contractor = self.w.taylor_c

        contractors.deactivate(contractor=contractor)

        user = authenticate(
            username=contractor.user.username,
            password=PASSWORD
        )

        self.assertIsNone(user)

        # Contractor's profile must not be deleted.
        self.assertTrue(
            Contractor.objects.filter(pk=contractor.pk).exists()
        )

    # SF-3: Deactivation requires confirmation.
    def test_sf3_deactivation_confirmation(self):

        self.client.force_login(self.w.owner)

        self.client.post(
            reverse("contractors"),
            {
                "action": "deactivate",
                "contractor_id": self.w.taylor_c.pk
            }
        )

        self.w.taylor_c.refresh_from_db()

        # Without confirmation, contractor must remain active.
        self.assertTrue(self.w.taylor_c.is_active)

    # Owner can access the Contractors page.
    def test_owner_can_access_contractors(self):

        self.client.force_login(self.w.owner)

        response = self.client.get(reverse("contractors"))

        self.assertEqual(response.status_code, 200)

    # SE-2: Other roles cannot access the Contractors page.
    def test_non_owner_access_denied(self):

        users = [
            self.w.company,
            self.w.taylor_sup.user,
            self.w.taylor_c.user
        ]

        for user in users:

            with self.subTest(role=user.role):

                self.client.force_login(user)

                response = self.client.get(
                    reverse("contractors")
                )

                self.assertEqual(response.status_code, 403)