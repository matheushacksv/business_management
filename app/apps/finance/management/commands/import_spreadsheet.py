import csv
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.companies.models import Company
from apps.companies.services import normalize_cnpj
from apps.finance.importer import import_spreadsheet


class DryRunRollback(Exception):
    pass


class Command(BaseCommand):
    help = 'Import the legacy CONTROLE FINANCEIRO spreadsheet (dry-run unless --commit).'

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument(
            '--default-company', required=True, metavar='CNPJ',
            help='Company for rows with an empty company column',
        )
        parser.add_argument(
            '--company', action='append', default=[], metavar='"NAME=CNPJ"',
            help='Map a spreadsheet company name to a CNPJ (repeatable)',
        )
        parser.add_argument('--skipped-report', metavar='CSV', help='Write skipped rows to this CSV')
        parser.add_argument('--commit', action='store_true', help='Persist the import (default: dry-run)')

    def _company(self, cnpj):
        try:
            return Company.objects.get(cnpj=normalize_cnpj(cnpj))
        except Company.DoesNotExist:
            raise CommandError(f'Company with CNPJ {cnpj} not found; create it first')

    def handle(self, *args, path, default_company, company, skipped_report, commit, **options):
        default = self._company(default_company)
        mapping = {}
        for item in company:
            name, sep, cnpj = item.rpartition('=')
            if not sep or not name.strip():
                raise CommandError(f'Invalid --company {item!r}; expected "NAME=CNPJ"')
            mapping[' '.join(name.split())] = self._company(cnpj)

        try:
            with transaction.atomic():
                result = import_spreadsheet(path, default_company=default, companies=mapping)
                if not commit:
                    raise DryRunRollback
        except DryRunRollback:
            pass
        except ValueError as exc:
            raise CommandError(str(exc))

        out = self.stdout.write
        out(f'Subgroups in plan: {len(result.plan)} (created {result.subgroups_created})')
        out(f'Contacts created: {result.contacts_created}')
        out(f'Transactions: {result.transactions_created} imported, {len(result.skipped)} skipped')
        reasons = Counter(s.reason.split(':')[0] for s in result.skipped)
        for reason, count in reasons.most_common():
            out(f'  - {reason}: {count}')
        if skipped_report:
            with open(skipped_report, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['row', 'reason', 'date', 'contact', 'amount', 'type', 'reference',
                                 'group', 'subgroup', 'status', 'notes', 'company'])
                for s in result.skipped:
                    writer.writerow([s.row, s.reason, *s.values])
            out(f'Skipped rows written to {skipped_report}')
        if commit:
            out(self.style.SUCCESS('Import committed.'))
        else:
            out(self.style.WARNING('Dry-run: nothing was saved. Use --commit to persist.'))
