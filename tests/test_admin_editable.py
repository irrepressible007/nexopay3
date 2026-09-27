"""Everything visible must be editable by admins without code."""
import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.cms.models import FooterColumn, MenuItem, Page, SiteSettings, SiteText
from apps.cms.sitetext import bump_version, ensure_applied, make_key
from apps.events.models import Category

from .factories import UserFactory

pytestmark = pytest.mark.django_db


def text(msgid):
    return SiteText.objects.get(key=make_key(msgid))


@pytest.fixture(autouse=True)
def _reset_texts():
    yield
    SiteText.objects.update(text_en="", text_en_plural="", text_bn="")
    bump_version()
    ensure_applied()


class TestSiteTexts:
    def test_every_interface_string_is_listed(self):
        assert SiteText.objects.count() > 400
        assert SiteText.objects.filter(msgid="Continue to checkout", group="Event page & tickets panel").exists()

    def test_admin_override_changes_live_page_in_both_languages(self, client):
        row = text("Sign up")
        row.text_en = "Join free"
        row.text_bn = "ফ্রি যোগ দিন"
        row.full_clean()
        row.save()
        assert b"Join free" in client.get("/accounts/login/").content
        assert "ফ্রি যোগ দিন" in client.get("/bn/accounts/login/").content.decode()

    def test_placeholders_must_be_kept(self):
        row = text("Only %(n)s left")
        row.text_en = "Hurry, almost gone"
        with pytest.raises(ValidationError):
            row.full_clean()
        row.text_en = "Hurry — only %(n)s tickets left"
        row.full_clean()

    def test_plain_texts_cannot_inject_html(self):
        row = text("Sign up")
        row.text_en = "<script>alert(1)</script>Join"
        row.full_clean()
        assert "<script>" not in row.text_en

    def test_reset_restores_default(self, client):
        row = text("Sign up")
        row.text_en = "Join free"
        row.save()
        assert b"Join free" in client.get("/accounts/login/").content
        row.text_en = ""
        row.save()
        content = client.get("/accounts/login/").content
        assert b"Join free" not in content and b"Sign up" in content

    def test_admin_changelist_inline_edit(self, client):
        admin = UserFactory(is_staff=True, is_superuser=True)
        client.force_login(admin)
        row = text("Sign up")
        url = reverse("admin:cms_sitetext_changelist") + "?q=Sign+up"
        response = client.get(url)
        assert response.status_code == 200
        change = client.get(reverse("admin:cms_sitetext_change", args=[row.pk]))
        assert change.status_code == 200


class TestMenusAndSettings:
    def test_menus_come_from_admin_and_localize(self, client):
        MenuItem.objects.create(location="header", label="Concert Nights", label_bn="কনসার্ট রাত",
                                url="/events/?category=concert", sort_order=1)
        column = FooterColumn.objects.create(title="Company", title_bn="প্রতিষ্ঠান", sort_order=99)
        MenuItem.objects.create(location="footer", column=column, label="Careers", url="https://jobs.example.com")
        en = client.get("/events/").content.decode()
        assert "Concert Nights" in en and "Careers" in en and "https://jobs.example.com" in en
        bn = client.get("/bn/events/").content.decode()
        assert "কনসার্ট রাত" in bn and 'href="/bn/events/?category=concert"' in bn

    def test_empty_pages_show_placeholder(self, client):
        page = Page.objects.get(slug="about")
        assert page.body_en == ""
        assert b"being updated" in client.get("/p/about/").content
        assert "হালনাগাদ" in client.get("/bn/p/about/").content.decode()

    def test_email_uses_admin_smtp_settings(self):
        from apps.core.mail import SiteEmailBackend

        site = SiteSettings.load()
        site.email_host, site.email_port, site.email_username = "mail.example.com", 587, "tickets@example.com"
        site.email_use_ssl, site.email_use_tls = False, True
        site.email_password = "pw123"
        site.email_from_address = "tickets@example.com"
        site.save()
        assert "pw123" not in SiteSettings.objects.get(pk=1).email_password_encrypted
        backend = SiteEmailBackend()
        assert (backend.host, backend.port, backend.username, backend.password) == ("mail.example.com", 587, "tickets@example.com", "pw123")
        assert backend.use_tls and not backend.use_ssl
        assert "tickets@example.com" in backend.default_sender()

    def test_brand_colours_apply_instantly(self, client):
        site = SiteSettings.load()
        site.primary_color = "#123456"
        site.save()
        assert b"--brand:#123456" in client.get("/").content

    def test_hero_headline_is_editable_with_highlight(self, client):
        from apps.cms.models import HomeSection

        hero = HomeSection.objects.get(kind="hero")
        hero.title_en = "Big *nights* ahead"
        hero.save()
        content = client.get("/").content.decode()
        assert 'Big <span class="text-gradient">nights</span> ahead' in content


def test_all_admin_editing_screens_open(client):
    from apps.payments.models import PaymentProviderSetting

    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    urls = [
        reverse("admin:cms_sitetext_changelist"),
        reverse("admin:cms_sitetext_changelist") + "?group=Homepage&customized=no",
        reverse("admin:cms_headerlink_changelist"),
        reverse("admin:cms_headerlink_add"),
        reverse("admin:cms_footercolumn_changelist"),
        reverse("admin:cms_footercolumn_change", args=[FooterColumn.objects.first().pk]),
        reverse("admin:cms_sitesettings_change", args=[SiteSettings.load().pk]),
        reverse("admin:events_category_change", args=[Category.objects.first().pk]),
        reverse("admin:payments_paymentprovidersetting_changelist"),
    ]
    urls += [reverse("admin:payments_paymentprovidersetting_change", args=[s.pk]) for s in PaymentProviderSetting.objects.all()]
    for url in urls:
        assert client.get(url).status_code == 200, url


def test_admin_saves_payment_credentials_encrypted(client):
    from apps.payments.models import PaymentProviderSetting

    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    setting = PaymentProviderSetting.objects.get(provider="bkash")
    url = reverse("admin:payments_paymentprovidersetting_change", args=[setting.pk])
    data = {
        "display_name_en": "bKash", "display_name_bn": "বিকাশ", "is_sandbox": "on", "brand_color": "#E2136E",
        "show_in_footer": "on", "sort_order": 0,
        "cred_app_key": "KEY", "cred_app_secret": "SECRET", "cred_username": "USER", "cred_password": "PASS",
        "cred_base_url": "",
    }
    response = client.post(url, data)
    assert response.status_code == 302, response.content[:500]
    setting.refresh_from_db()
    assert setting.get_credentials() == {"app_key": "KEY", "app_secret": "SECRET", "username": "USER", "password": "PASS"}
    # Saving again with secrets left blank keeps them.
    data.update({"cred_app_secret": "", "cred_password": ""})
    client.post(url, data)
    setting.refresh_from_db()
    assert setting.get_credentials()["app_secret"] == "SECRET"
    # The saved secret is never sent back to the browser.
    assert b"SECRET" not in client.get(url).content
