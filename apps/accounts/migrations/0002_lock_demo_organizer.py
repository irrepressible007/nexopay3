"""Lock the demo organizer account that older `seed_demo` runs created with a published default password."""
from django.contrib.auth.hashers import check_password, make_password
from django.db import migrations

DEMO_EMAIL = "demo-organizer@nexopay.com.bd"
OLD_DEFAULT = "demo12345!"


def lock(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for user in User.objects.filter(email__iexact=DEMO_EMAIL):
        if user.password and check_password(OLD_DEFAULT, user.password):  # untouched if the owner changed it
            user.password = make_password(None)  # unusable
            user.save(update_fields=["password"])


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [migrations.RunPython(lock, migrations.RunPython.noop)]
