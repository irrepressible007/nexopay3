from django.db import migrations

HERO_CATEGORIES = ["concert", "festivals", "competitions", "workshops", "stand-up"]


def seed(apps, schema_editor):
    Category = apps.get_model("events", "Category")
    Category.objects.filter(slug__in=HERO_CATEGORIES).update(show_in_hero=True)


class Migration(migrations.Migration):
    dependencies = [("events", "0003_category_icon_image_category_show_in_hero_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
