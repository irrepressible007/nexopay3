from django.db import migrations

PROVIDERS = [
    ("bkash", "bKash", 0),
    ("nagad", "Nagad", 1),
    ("upay", "Upay", 2),
    ("pathaopay", "Pathao Pay", 3),
    ("sslcommerz", "Card (Visa / Mastercard)", 4),
    ("mock", "Test payment (staging only)", 99),
]


def seed(apps, schema_editor):
    Setting = apps.get_model("payments", "PaymentProviderSetting")
    for code, name, order in PROVIDERS:
        Setting.objects.get_or_create(
            provider=code, defaults={"display_name": name, "sort_order": order, "is_enabled": False}
        )


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
