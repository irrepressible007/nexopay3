from django.db import migrations

HEADER = [
    ("Events", "ইভেন্ট", "/events/"),
    ("On sale", "বিক্রি চলছে", "/events/?status=live"),
    ("Coming soon", "শীঘ্রই আসছে", "/events/?status=upcoming"),
    ("For organizers", "আয়োজকদের জন্য", "/organizers/apply/"),
]

FOOTER = [
    ("Discover", "খুঁজে দেখুন", [
        ("All events", "সব ইভেন্ট", "/events/"),
        ("On sale now", "এখন বিক্রি চলছে", "/events/?status=live"),
        ("Coming soon", "শীঘ্রই আসছে", "/events/?status=upcoming"),
    ]),
    ("Organizers", "আয়োজক", [
        ("Sell tickets", "টিকিট বিক্রি করুন", "/organizers/apply/"),
        ("Promote your event", "ইভেন্টের প্রচার", "/contact/?reason=list_event"),
    ]),
    ("Help", "সহায়তা", [
        ("FAQ", "সাধারণ জিজ্ঞাসা", "/faq/"),
        ("Contact us", "যোগাযোগ", "/contact/"),
        ("About Nexopay", "নেক্সোপে সম্পর্কে", "/p/about/"),
        ("Terms & Conditions", "শর্তাবলী", "/p/terms/"),
        ("Privacy Policy", "গোপনীয়তা নীতি", "/p/privacy/"),
        ("Refund Policy", "রিফান্ড নীতি", "/p/refund-policy/"),
    ]),
]

# Placeholder bodies written by the first seed — cleared so admins start from empty pages.
PLACEHOLDERS = {
    "<p>Nexopay is Bangladesh's home for event tickets.</p>",
    "<p>Platform terms go here.</p>",
    "<p>Privacy policy goes here.</p>",
    "<p>Refund policy goes here.</p>",
}

OLD_COLOURS = {"primary_color": "#A855F7", "secondary_color": "#EC4899", "background_color": "#07060B"}
NEW_COLOURS = {"primary_color": "#8B5CF6", "secondary_color": "#D946EF", "background_color": "#08051A"}


def seed(apps, schema_editor):
    MenuItem = apps.get_model("cms", "MenuItem")
    FooterColumn = apps.get_model("cms", "FooterColumn")
    Page = apps.get_model("cms", "Page")
    SiteSettings = apps.get_model("cms", "SiteSettings")
    HomeSection = apps.get_model("cms", "HomeSection")

    if not MenuItem.objects.exists():
        for i, (en, bn, url) in enumerate(HEADER):
            MenuItem.objects.create(location="header", label=en, label_en=en, label_bn=bn, url=url, sort_order=i * 10)
        for c, (title_en, title_bn, links) in enumerate(FOOTER):
            column = FooterColumn.objects.create(title=title_en, title_en=title_en, title_bn=title_bn, sort_order=c * 10)
            for i, (en, bn, url) in enumerate(links):
                MenuItem.objects.create(location="footer", column=column, label=en, label_en=en, label_bn=bn,
                                        url=url, sort_order=i * 10)

    for page in Page.objects.all():
        changed = False
        for field in ("body", "body_en", "body_bn"):
            if getattr(page, field, None) in PLACEHOLDERS:
                setattr(page, field, "")
                changed = True
        if changed:
            page.save()

    for site in SiteSettings.objects.all():
        for field, old in OLD_COLOURS.items():
            if getattr(site, field).upper() == old:
                setattr(site, field, NEW_COLOURS[field])
        site.save()

    for hero in HomeSection.objects.filter(kind="hero"):
        if not (hero.title_en or hero.title):
            hero.title = hero.title_en = "Tickets to *everything* worth going to."
            hero.title_bn = "সেরা সব ইভেন্টের *টিকিট*, এক জায়গায়"
            hero.save()


class Migration(migrations.Migration):
    dependencies = [("cms", "0003_footercolumn_sitetext_remove_page_show_in_footer_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
