from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.finance.management.commands.import_spreadsheet import Command as SpreadsheetCommand
from apps.legal.importer import run_collection_import


class Command(BaseCommand):
    help = ('Import the spreadsheet rows of customers under collection (run after import_spreadsheet; '
            'dry-run unless --commit).')

    def add_arguments(self, parser):
        parser.add_argument('path')
        parser.add_argument('--rows', required=True, metavar='FILE',
                            help='Text file with one "Lançamentos" row number per line')
        parser.add_argument('--default-company', required=True, metavar='CNPJ')
        parser.add_argument('--company', action='append', default=[], metavar='"NAME=CNPJ"')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, path, rows, default_company, company, commit, **options):
        helper = SpreadsheetCommand()  # same company arguments as import_spreadsheet
        default = helper._company(default_company)
        mapping = {}
        for item in company:
            name, sep, cnpj = item.rpartition('=')
            if not sep or not name.strip():
                raise CommandError(f'Invalid --company {item!r}; expected "NAME=CNPJ"')
            mapping[' '.join(name.split())] = helper._company(cnpj)
        try:
            row_numbers = {int(line) for line in Path(rows).read_text().split() if line.strip()}
        except ValueError:
            raise CommandError('--rows must contain only row numbers')

        try:
            result = run_collection_import(path, rows=row_numbers, default_company=default,
                                           companies=mapping, commit=commit)
        except ValueError as exc:
            raise CommandError(str(exc))

        out = self.stdout.write
        out(f'Rows imported: {result.rows_imported} of {len(row_numbers)}')
        for row, reason in result.rows_skipped:
            out(f'  - skipped row {row}: {reason}')
        out(f'Cases created: {len(result.cases)}')
        for contact, company_name, linked, open_amount, sheet in result.cases:
            match = f' <- "{sheet}"' if sheet else ' (not in the collection sheet)'
            out(f'  - {contact} [{company_name}]: {linked} installment(s), {open_amount:.2f} open{match}')
        if result.unmatched_sheet_rows:
            out(f'Collection sheet rows without imported installments: {result.unmatched_sheet_rows}')
        if commit:
            out(self.style.SUCCESS('Import committed.'))
        else:
            out(self.style.WARNING('Dry-run: nothing was saved. Use --commit to persist.'))
