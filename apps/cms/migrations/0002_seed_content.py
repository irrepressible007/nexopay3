from django.db import migrations

SUBTITLES_BN = {
    "featured": "নেক্সোপে টিমের বাছাই করা",
    "upcoming": "প্রস্তুত থাকুন — শীঘ্রই টিকিট আসছে",
    "organizer_cta": "বিকাশ, নগদ ও কার্ডে টিকিট বিক্রি করুন, আর গেটে স্ক্যান করে অতিথিদের প্রবেশ করান।",
}

SECTIONS = [
    ("hero", "", "", ""),
    ("featured", "Featured events", "ফিচার্ড ইভেন্ট", "Hand-picked by the Nexopay team"),
    ("categories", "Browse by category", "ক্যাটাগরি অনুযায়ী খুঁজুন", ""),
    ("this_week", "Happening this week", "এই সপ্তাহে", ""),
    ("just_announced", "Just announced", "নতুন ঘোষণা", ""),
    ("upcoming", "Coming soon", "শীঘ্রই আসছে", "Get ready — tickets drop soon"),
    ("organizer_cta", "Hosting an event?", "ইভেন্ট আয়োজন করছেন?", "Sell tickets with bKash, Nagad and cards, and scan guests in at the gate."),
    ("faq", "Questions, answered", "সাধারণ জিজ্ঞাসা", ""),
]

PAGES = [
    ("about", "About Nexopay", "নেক্সোপে সম্পর্কে", "<p>Nexopay is Bangladesh's home for event tickets.</p>"),
    ("terms", "Terms & Conditions", "শর্তাবলী", "<p>Platform terms go here.</p>"),
    ("privacy", "Privacy Policy", "গোপনীয়তা নীতি", "<p>Privacy policy goes here.</p>"),
    ("refund-policy", "Refund Policy", "রিফান্ড নীতি", "<p>Refund policy goes here.</p>"),
]

FAQ = [
    ("How do I get my ticket?", "আমি টিকিট কীভাবে পাব?",
     "<p>After payment your tickets are emailed as a PDF and are always available under <strong>My tickets</strong> in your account. Show the QR code at the gate.</p>"),
    ("Which payment methods can I use?", "কোন পেমেন্ট মাধ্যম ব্যবহার করা যাবে?",
     "<p>bKash, Nagad, Upay, Pathao Pay and Visa/Mastercard cards.</p>"),
    ("I didn't receive the email — what now?", "ইমেইল পাইনি — কী করব?",
     "<p>Log in and open <strong>My tickets</strong>; you can download every ticket again at any time.</p>"),
    ("Can I buy more than one ticket?", "একাধিক টিকিট কেনা যাবে?",
     "<p>Each email/phone can buy a ticket type once unless the organizer allows a quantity for that ticket.</p>"),
]


def seed(apps, schema_editor):
    SiteSettings = apps.get_model("cms", "SiteSettings")
    HomeSection = apps.get_model("cms", "HomeSection")
    Page = apps.get_model("cms", "Page")
    FaqItem = apps.get_model("cms", "FaqItem")

    SiteSettings.objects.get_or_create(
        pk=1,
        defaults={
            "tagline": "Tickets to everything worth going to",
            "tagline_en": "Tickets to everything worth going to",
            "tagline_bn": "সেরা সব ইভেন্টের টিকিট, এক জায়গায়",
        },
    )
    if not HomeSection.objects.exists():
        for i, (kind, en, bn, sub) in enumerate(SECTIONS):
            HomeSection.objects.create(
                kind=kind, title=en, title_en=en, title_bn=bn, subtitle=sub, subtitle_en=sub,
                subtitle_bn=SUBTITLES_BN.get(kind, ""),
                cta_label_bn="আপনার ইভেন্ট যোগ করুন" if kind == "organizer_cta" else "",
                sort_order=i * 10, cta_label="List your event" if kind == "organizer_cta" else "",
                cta_label_en="List your event" if kind == "organizer_cta" else "",
                link_url="/organizers/apply/" if kind == "organizer_cta" else "",
            )
    for i, (slug, en, bn, body) in enumerate(PAGES):
        Page.objects.get_or_create(
            slug=slug,
            defaults={"title": en, "title_en": en, "title_bn": bn, "body": body, "body_en": body, "sort_order": i},
        )
    if not FaqItem.objects.exists():
        for i, (q_en, q_bn, a) in enumerate(FAQ):
            FaqItem.objects.create(
                question=q_en, question_en=q_en, question_bn=q_bn, answer=a, answer_en=a,
                sort_order=i, show_on_home=True,
            )


class Migration(migrations.Migration):
    dependencies = [("cms", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
