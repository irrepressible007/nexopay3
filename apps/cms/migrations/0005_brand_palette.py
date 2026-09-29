import django.core.validators
from django.db import migrations, models

HEX = django.core.validators.RegexValidator('^#[0-9A-Fa-f]{6}$', 'Use a hex colour like #A855F7.')

# field: (new default, earlier defaults that were never changed by an admin)
PALETTE = {
    "primary_color": ("#7351F5", {"#A855F7", "#8B5CF6"}),
    "secondary_color": ("#CF3573", {"#EC4899", "#D946EF"}),
    "accent_color": ("#FFC04D", {"#22D3EE"}),
    "background_color": ("#0B0917", {"#07060B", "#08051A"}),
}


def adopt_new_palette(apps, schema_editor):
    """Move colours still on an old default to the new palette; admin-chosen colours stay."""
    SiteSettings = apps.get_model("cms", "SiteSettings")
    for site in SiteSettings.objects.all():
        changed = []
        for field, (new, old) in PALETTE.items():
            if (getattr(site, field) or "").upper() in old:
                setattr(site, field, new)
                changed.append(field)
        if changed:
            site.save(update_fields=changed)
    from django.core.cache import cache

    cache.delete("cms:site-settings")  # SiteSettings.load() caches the row; show the new colours now


class Migration(migrations.Migration):

    dependencies = [
        ('cms', '0004_seed_navigation'),
    ]

    operations = [
        migrations.AlterField(
            model_name='sitesettings',
            name='primary_color',
            field=models.CharField(default='#7351F5', help_text='Buttons, links and highlights. Default #7351F5.', max_length=7, validators=[HEX]),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='secondary_color',
            field=models.CharField(default='#CF3573', help_text='Blends with the primary colour in gradients. Default #CF3573.', max_length=7, validators=[HEX]),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='accent_color',
            field=models.CharField(default='#FFC04D', help_text='Small highlights: “coming soon”, stars, countdowns. Default #FFC04D.', max_length=7, validators=[HEX]),
        ),
        migrations.AlterField(
            model_name='sitesettings',
            name='background_color',
            field=models.CharField(default='#0B0917', help_text='Page background; must stay dark. Default #0B0917.', max_length=7, validators=[HEX]),
        ),
        migrations.RunPython(adopt_new_palette, migrations.RunPython.noop),
    ]
