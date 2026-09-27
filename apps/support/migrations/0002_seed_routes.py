from django.db import migrations

ROUTES = {
    "payment_issue": "payments@nexopay.com.bd",
    "ticket_issue": "support@nexopay.com.bd",
    "account": "support@nexopay.com.bd",
    "list_event": "organizers@nexopay.com.bd",
    "technical": "support@nexopay.com.bd",
    "feedback": "hello@nexopay.com.bd",
}


def seed(apps, schema_editor):
    Route = apps.get_model("support", "SupportRoute")
    for reason, email in ROUTES.items():
        Route.objects.get_or_create(reason=reason, defaults={"email": email})


class Migration(migrations.Migration):
    dependencies = [("support", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
