from django.db import migrations

BRANDING = {
    # provider: (English name, Bangla name, badge colour, show in footer)
    "bkash": ("bKash", "বিকাশ", "#E2136E", True),
    "nagad": ("Nagad", "নগদ", "#F7941D", True),
    "upay": ("Upay", "উপায়", "#4FB4E6", True),
    "pathaopay": ("Pathao Pay", "পাঠাও পে", "#EF4136", True),
    "sslcommerz": ("Visa / Mastercard", "ভিসা / মাস্টারকার্ড", "#FFFFFF", True),
    "mock": ("Test payment (staging only)", "টেস্ট পেমেন্ট", "#FBBF24", False),
}


def seed(apps, schema_editor):
    Setting = apps.get_model("payments", "PaymentProviderSetting")
    for provider, (en, bn, colour, footer) in BRANDING.items():
        Setting.objects.filter(provider=provider).update(
            display_name=en, display_name_en=en, display_name_bn=bn, brand_color=colour, show_in_footer=footer
        )


class Migration(migrations.Migration):
    dependencies = [("payments", "0003_paymentprovidersetting_brand_color_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
