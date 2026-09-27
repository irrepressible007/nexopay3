from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.utils import normalize_phone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """
    Every user is a buyer. A user becomes an organizer by holding an approved
    OrganizerProfile, so one account can hold both roles.
    """

    username = None
    first_name = None
    last_name = None

    email = models.EmailField(_("email address"), unique=True)
    full_name = models.CharField(_("full name"), max_length=150, blank=True)
    phone = models.CharField(_("mobile number"), max_length=16, unique=True, null=True, blank=True)
    preferred_language = models.CharField(max_length=5, default="en")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = self.email.lower()
        if self.phone:
            self.phone = normalize_phone(self.phone)

    def get_full_name(self):
        return self.full_name or self.email

    def get_short_name(self):
        return (self.full_name.split(" ")[0] if self.full_name else self.email.split("@")[0])

    @property
    def organizer(self):
        return getattr(self, "organizer_profile", None)

    @property
    def is_organizer(self) -> bool:
        profile = self.organizer
        return bool(profile and profile.is_approved)
