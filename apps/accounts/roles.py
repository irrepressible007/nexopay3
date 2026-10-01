"""
Ready-made staff roles (admin › People › Staff roles). Put a staff member in a role to give them
just that part of the control room. Roles are created once; after that the admin may edit them
freely (they are never overwritten).

Each entry is "app.*" (everything in an app) or "app.codename".
"""
from django.utils.translation import gettext_noop

ROLES = {
    gettext_noop("Content editor"): [
        "cms.*", "events.view_event", "events.change_event", "events.view_category", "events.add_category",
        "events.change_category",
    ],
    gettext_noop("Event manager"): [
        "events.*", "organizers.view_organizerprofile", "organizers.change_organizerprofile", "orders.view_order",
        "tickets.view_ticket", "tickets.view_scanlog", "tickets.view_scanneraccess", "tickets.add_scanneraccess",
        "tickets.change_scanneraccess", "tickets.delete_scanneraccess",
    ],
    gettext_noop("Support agent"): [
        "support.*", "orders.view_order", "tickets.view_ticket", "tickets.change_ticket", "accounts.view_user",
        "events.view_event", "payments.view_refund", "payments.add_refund",
    ],
    gettext_noop("Finance"): [
        "payments.*", "orders.view_order", "events.view_event", "organizers.view_organizerprofile",
    ],
}


def ensure_staff_roles(using="default"):
    """Create any missing role group with its permissions (existing groups are left untouched)."""
    from django.contrib.auth.models import Group, Permission

    for name, rules in ROLES.items():
        group, created = Group.objects.using(using).get_or_create(name=name)
        if not created:
            continue
        perms = Permission.objects.using(using).none()
        for rule in rules:
            app, _, codename = rule.partition(".")
            qs = Permission.objects.using(using).filter(content_type__app_label=app)
            perms |= qs if codename == "*" else qs.filter(codename=codename)
        group.permissions.set(perms)
