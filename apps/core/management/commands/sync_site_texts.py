from django.core.management.base import BaseCommand

from apps.cms.sitetext import sync_from_catalog


class Command(BaseCommand):
    help = "Mirror every translatable interface string into the admin's Site texts."

    def handle(self, *args, **options):
        self.stdout.write(str(sync_from_catalog()))
