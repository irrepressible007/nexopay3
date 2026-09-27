import pytest
from django.core.cache import cache

from .factories import EventFactory, OrganizerFactory, TicketTypeFactory, UserFactory


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Re-apply seed data: transactional tests flush tables, and --reuse-db keeps that state."""
    import importlib

    from django.apps import apps as django_apps

    seeds = [
        "apps.events.migrations.0002_seed_categories",
        "apps.cms.migrations.0002_seed_content",
        "apps.payments.migrations.0002_seed_providers",
        "apps.support.migrations.0002_seed_routes",
    ]
    with django_db_blocker.unblock():
        for module in seeds:
            importlib.import_module(module).seed(django_apps, None)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def buyer(db):
    return UserFactory()


@pytest.fixture
def organizer(db):
    return OrganizerFactory()


@pytest.fixture
def event(db, organizer):
    return EventFactory(organizer=organizer)


@pytest.fixture
def ticket_type(db, event):
    return TicketTypeFactory(event=event, price="500.00", stock=10)


def checkout_kwargs(user, event, quantities, **extra):
    data = {
        "user": user,
        "event": event,
        "quantities": quantities,
        "buyer_name": user.full_name or "Test Buyer",
        "buyer_phone": user.phone or "01712345678",
        "delivery_email": user.email,
    }
    data.update(extra)
    return data
