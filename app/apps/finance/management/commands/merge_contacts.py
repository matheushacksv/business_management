from django.core.management.base import BaseCommand

from apps.finance.contact_merge import run_merges


class Command(BaseCommand):
    help = 'Merge the contact pairs marked "S" in the reviewed suggestions file (dry-run unless --commit).'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, path, commit, **options):
        result = run_merges(path, user=None, commit=commit)
        out = self.stdout.write
        out(f'Merged: {len(result.merged)}')
        for keep, drop in result.merged:
            out(f'  - "{drop}" -> "{keep}"')
        for row, problem in result.errors:
            out(self.style.ERROR(f'  ! row {row}: {problem}'))
        if commit:
            out(self.style.SUCCESS('Merges committed.'))
        else:
            out(self.style.WARNING('Dry-run: nothing was saved. Use --commit to persist.'))
