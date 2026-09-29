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
        assert ('<span class="word" style="--i:0">Big</span> <span class="word text-gradient" style="--i:1">nights</span> '
                '<span class="word" style="--i:2">ahead</span>') in content


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


class TestBrandColours:
    """Whatever colours an admin picks, text on them stays readable and the dark design holds."""

    def test_defaults_are_the_new_palette_and_readable(self):
        from apps.core.colors import contrast

        site = SiteSettings.load()  # created by a seed migration with older defaults, then migrated
        assert (site.primary_color, site.secondary_color, site.accent_color, site.background_color) == (
            "#7351F5", "#CF3573", "#FFC04D", "#0B0917")
        assert site.on_brand_color == "#FFFFFF" and site.on_accent_color == "#0B0917"
        assert min(contrast("#FFFFFF", site.primary_color), contrast("#FFFFFF", site.secondary_color)) >= 4.5
        site.clean()

    def test_light_background_is_refused(self):
        site = SiteSettings.load()
        site.background_color = "#F4F4F4"
        with pytest.raises(ValidationError) as error:
            site.clean()
        assert "background_color" in error.value.message_dict

    def test_colours_that_vanish_into_the_background_are_refused(self):
        site = SiteSettings.load()
        site.primary_color, site.accent_color = "#15122A", "#3B2F5E"
        with pytest.raises(ValidationError) as error:
            site.clean()
        assert {"primary_color", "accent_color"} <= set(error.value.message_dict)

    def test_light_brand_colours_get_dark_text(self, client):
        site = SiteSettings.load()
        site.primary_color, site.secondary_color, site.accent_color = "#FFD166", "#F9A8D4", "#5EEAD4"
        site.save()
        assert site.on_brand_color == "#0B0917"
        assert b"--on-brand:#0B0917" in client.get("/").content


class TestOutgoingEmailSettings:
    def form(self, **changes):
        from django.db.models.fields.files import FieldFile
        from django.forms.models import model_to_dict

        from apps.cms.admin import SiteSettingsForm

        site = SiteSettings.load()
        data = {k: v for k, v in model_to_dict(site).items() if v is not None and not isinstance(v, FieldFile)}
        data.update(changes)
        return SiteSettingsForm(data=data, instance=site)

    def test_personal_address_with_the_cpanel_server_is_refused(self):
        form = self.form(email_host="mail.nexopay.com.bd", email_username="someone@gmail.com", email_password="pw")
        assert not form.is_valid()
        assert "Gmail address only works" in str(form.errors["email_username"])

    def test_gmail_address_with_gmail_server_is_accepted(self):
        form = self.form(email_host="smtp.gmail.com", email_username="someone@gmail.com", email_password="app-pw",
                         email_from_address="someone@gmail.com")
        assert form.is_valid(), form.errors

    def test_from_address_defaults_to_the_mailbox(self):
        form = self.form(email_host="mail.nexopay.com.bd", email_username="tickets@nexopay.com.bd",
                         email_password="pw", email_from_address="")
        assert form.is_valid(), form.errors
        site = form.save()
        assert site.email_from_address == "tickets@nexopay.com.bd"
        assert site.email_password == "pw"

    def test_port_and_security_must_match(self):
        form = self.form(email_host="mail.nexopay.com.bd", email_username="tickets@nexopay.com.bd",
                         email_password="pw", email_port=587, email_use_ssl=True, email_use_tls=False)
        assert not form.is_valid()
        assert "Port 587 needs SSL off and TLS on" in str(form.errors)

    def test_empty_host_needs_nothing_else(self):
        assert self.form(email_host="", email_username="", email_from_address="").is_valid()

    def test_browser_autofill_is_switched_off(self, client):
        import re

        client.force_login(UserFactory(is_staff=True, is_superuser=True))
        html = client.get(reverse("admin:cms_sitesettings_change", args=[SiteSettings.load().pk])).content.decode()
        assert 'autocomplete="new-password"' in re.search(r'<input[^>]*name="email_password"[^>]*>', html).group(0)
        assert 'autocomplete="off"' in re.search(r'<input[^>]*name="email_username"[^>]*>', html).group(0)


def test_send_test_email_button(client, settings):
    from django.contrib.messages import get_messages
    from django.core import mail

    client.force_login(UserFactory(is_staff=True, is_superuser=True, email="boss@example.com"))
    url = reverse("admin:cms_sitesettings_send_test_email", args=[SiteSettings.load().pk])
    response = client.get(url)
    assert response.status_code == 302
    assert [message.to for message in mail.outbox] == [["boss@example.com"]]
    assert "Test email sent to boss@example.com" in [str(m) for m in get_messages(response.wsgi_request)][-1]

    # A mail server that can't be reached is explained to the admin, not raised.
    settings.EMAIL_BACKEND = "apps.core.mail.SiteEmailBackend"
    site = SiteSettings.load()
    site.email_host, site.email_port, site.email_use_ssl, site.email_use_tls = "127.0.0.1", 1, False, False
    site.save()
    response = client.get(url)
    assert response.status_code == 302
    assert "couldn't reach the mail server" in [str(m) for m in get_messages(response.wsgi_request)][-1]


FAKE_SENDMAIL = """
import os, pathlib, sys
pathlib.Path(os.environ["FAKE_SENDMAIL_LOG"]).write_text(repr(sys.argv[1:]) + "\\n" + sys.stdin.read())
if os.environ.get("FAKE_SENDMAIL_REFUSE"):
    sys.stderr.write("550 sender not allowed")
    sys.exit(1)
"""


class TestServerMailProgram:
    """With no email host in the admin, mail goes to the server's own mail program (sendmail)."""

    @pytest.fixture
    def fake_sendmail(self, settings, tmp_path, monkeypatch):
        import sys

        script = tmp_path / "fake_sendmail.py"
        script.write_text(FAKE_SENDMAIL)
        log = tmp_path / "sent.txt"
        monkeypatch.setenv("FAKE_SENDMAIL_LOG", str(log))
        settings.SENDMAIL_COMMAND = [sys.executable, str(script)]
        settings.EMAIL_BACKEND = "apps.core.mail.SiteEmailBackend"
        site = SiteSettings.load()
        site.email_host, site.email_from_name, site.email_from_address = "", "Nexopay", "tickets@nexopay.com.bd"
        site.save()
        return log

    def test_message_is_handed_to_the_mail_program(self, fake_sendmail):
        from ast import literal_eval

        from django.core.mail import EmailMessage

        sent = EmailMessage("Your tickets", "Body text", to=["buyer@example.com"], bcc=["copy@example.com"]).send()
        assert sent == 1
        args, message = fake_sendmail.read_text().split("\n", 1)
        assert literal_eval(args) ==["-i", "-f", "tickets@nexopay.com.bd", "--", "buyer@example.com", "copy@example.com"]
        assert "From: Nexopay <tickets@nexopay.com.bd>" in message
        assert "Subject: Your tickets" in message
        assert "copy@example.com" not in message  # Bcc stays hidden

    def test_refusal_is_explained_by_the_test_button(self, fake_sendmail, client, monkeypatch):
        from django.contrib.messages import get_messages

        monkeypatch.setenv("FAKE_SENDMAIL_REFUSE", "1")
        client.force_login(UserFactory(is_staff=True, is_superuser=True, email="boss@example.com"))
        response = client.get(reverse("admin:cms_sitesettings_send_test_email", args=[SiteSettings.load().pk]))
        message = [str(m) for m in get_messages(response.wsgi_request)][-1]
        assert "mail program didn't accept it" in message and "550 sender not allowed" in message


def test_payment_credential_fields_are_not_autofilled(client):
    import re

    from apps.payments.models import PaymentProviderSetting

    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    setting = PaymentProviderSetting.objects.get(provider="bkash")
    html = client.get(reverse("admin:payments_paymentprovidersetting_change", args=[setting.pk])).content.decode()
    assert 'autocomplete="off"' in re.search(r'<input[^>]*name="cred_username"[^>]*>', html).group(0)
    assert 'autocomplete="new-password"' in re.search(r'<input[^>]*name="cred_password"[^>]*>', html).group(0)
