from django.db import migrations


def populate_shop_assignments(apps, schema_editor):
    Contractor = apps.get_model("rent", "Contractor")
    ShopAssignment = apps.get_model("rent", "ShopAssignment")

    # Create an initial assignment for every existing contractor
    for contractor in Contractor.objects.all():

        # Find the Monday of the week the contractor joined
        start_date = contractor.joined_on

        from datetime import timedelta
        start_date = start_date - timedelta(days=start_date.weekday())

        ShopAssignment.objects.get_or_create(
            contractor_id=contractor.id,
            effective_from=start_date,
            defaults={
                "shop_id": contractor.shop_id,
                "pay_type": contractor.pay_type,
            }
        )


class Migration(migrations.Migration):

    dependencies = [
        ("rent", "0003_contractor_deactivated_on_shopassignment"),
    ]

    operations = [
        migrations.RunPython(
            populate_shop_assignments,
            migrations.RunPython.noop
        ),
    ]