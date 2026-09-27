from datetime import timedelta
from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.events.models import Category, Event, TicketType
from apps.organizers.models import OrganizerProfile


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.Faker("name")
    phone = factory.Sequence(lambda n: f"+88017{n:08d}")
    password = factory.PostGenerationMethodCall("set_password", "pass12345!")

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()


class OrganizerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrganizerProfile

    user = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Organizer {n}")
    slug = factory.Sequence(lambda n: f"organizer-{n}")
    contact_email = factory.LazyAttribute(lambda o: f"{o.slug}@example.com")
    contact_phone = "01712345678"
    status = OrganizerProfile.Status.APPROVED


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category
        django_get_or_create = ("slug",)

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")


class EventFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Event
        skip_postgeneration_save = True

    organizer = factory.SubFactory(OrganizerFactory)
    title = factory.Sequence(lambda n: f"Event {n}")
    slug = factory.Sequence(lambda n: f"event-{n}")
    status = Event.Status.ON_SALE
    starts_at = factory.LazyFunction(lambda: timezone.now() + timedelta(days=14))
    venue_name = "Bashundhara ICCB"

    @factory.post_generation
    def categories(self, create, extracted, **kwargs):
        if create and extracted:
            self.categories.set(extracted)


class TicketTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TicketType

    event = factory.SubFactory(EventFactory)
    name = factory.Sequence(lambda n: f"Ticket {n}")
    price = Decimal("500.00")
    stock = 100
