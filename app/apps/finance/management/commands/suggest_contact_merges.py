from django.core.management.base import BaseCommand

from apps.finance.contact_merge import write_suggestions


class Command(BaseCommand):
    help = 'Write an .xlsx with likely duplicated contacts, to be reviewed (column "Mesclar? (S/N)").'

    def add_arguments(self, parser):
        parser.add_argument('path', help='Output .xlsx')

    def handle(self, *args, path, **options):
        count = write_suggestions(path)
        self.stdout.write(self.style.SUCCESS(f'{count} pair(s) written to {path}'))
