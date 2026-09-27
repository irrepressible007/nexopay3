from django.db import migrations

CATEGORIES = [
    # slug, English, Bangla, icon, accent
    ("festivals", "Festivals", "উৎসব", "festival", "#F59E0B"),
    ("concert", "Concert", "কনসার্ট", "mic", "#A855F7"),
    ("competitions", "Competitions", "প্রতিযোগিতা", "trophy", "#22D3EE"),
    ("sports", "Sports", "খেলাধুলা", "ball", "#22C55E"),
    ("conferences", "Conferences", "সম্মেলন", "podium", "#3B82F6"),
    ("workshops", "Workshops", "কর্মশালা", "tools", "#F97316"),
    ("movie-drama", "Movie / Drama", "সিনেমা / নাটক", "film", "#EF4444"),
    ("party", "Party", "পার্টি", "party", "#EC4899"),
    ("exhibitions", "Exhibitions", "প্রদর্শনী", "frame", "#14B8A6"),
    ("seminars", "Seminars", "সেমিনার", "book", "#6366F1"),
    ("pop-culture", "Pop Culture", "পপ কালচার", "sparkles", "#D946EF"),
    ("music", "Music", "সংগীত", "music", "#8B5CF6"),
    ("stand-up", "Stand-up", "স্ট্যান্ড-আপ কমেডি", "smile", "#FACC15"),
    ("fashion-shows", "Fashion Shows", "ফ্যাশন শো", "shirt", "#F472B6"),
    ("fundraisers", "Fundraisers", "তহবিল সংগ্রহ", "heart", "#FB7185"),
    ("hiphop", "Hiphop", "হিপহপ", "headphones", "#84CC16"),
    ("reunions", "Reunions", "পুনর্মিলনী", "users", "#38BDF8"),
    ("launching", "Launching", "লঞ্চিং", "rocket", "#F43F5E"),
]


def seed(apps, schema_editor):
    Category = apps.get_model("events", "Category")
    for order, (slug, en, bn, icon, color) in enumerate(CATEGORIES):
        Category.objects.update_or_create(
            slug=slug,
            defaults={
                "name": en, "name_en": en, "name_bn": bn, "icon": icon,
                "accent_color": color, "sort_order": order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("events", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
