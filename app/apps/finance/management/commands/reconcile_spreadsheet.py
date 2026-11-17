from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.finance.reconcile import reconcile, write_report


class Command(BaseCommand):
    help = (
        'Compare the system with the legacy spreadsheet (DRE + monthly cash flow, month by month) '
        'and write an Excel report. Nothing is saved: the import runs in a rolled-back transaction. '
        'Needs LibreOffice (soffice) to recalculate the spreadsheet for each year.'
    )

    def add_arguments(self, parser):
        parser.add_argument('spreadsheet', type=Path)
        parser.add_argument('--years', type=int, nargs='+', help='Default: every year with transactions')
        parser.add_argument('--output', type=Path, default=Path('conferencia-planilha.xlsx'))
        parser.add_argument('--soffice', default='soffice', help='LibreOffice binary')

    def handle(self, *args, spreadsheet: Path, years, output: Path, soffice: str, **options):
        if not spreadsheet.exists():
            raise CommandError(f'File not found: {spreadsheet}')
        try:
            result = reconcile(spreadsheet, years, soffice, log=self.stdout.write)
        except RuntimeError as error:
            raise CommandError(str(error))
        write_report(result, output)
        for s in result['summary']:
            different = s['compared'] - s['matched']
            style = self.style.SUCCESS if not different else self.style.WARNING
            self.stdout.write(style(f"{s['year']}: {s['matched']}/{s['compared']} batem, {different} diferente(s), "
                                    f"maior diferença R$ {s['max_diff']}"))
        self.stdout.write(f"{len(result['skipped'])} linha(s) não importada(s). Relatório: {output.resolve()}")
