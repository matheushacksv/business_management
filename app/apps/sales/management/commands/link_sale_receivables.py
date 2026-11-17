import csv

from django.core.management.base import BaseCommand

from apps.sales.linking import run_link


class Command(BaseCommand):
    help = 'Link imported installments to their sales when the amounts match (dry-run unless --commit).'

    def add_arguments(self, parser):
        parser.add_argument('--report', metavar='CSV', help='Write the sales left unlinked to this CSV')
        parser.add_argument('--commit', action='store_true')

    def handle(self, *args, report, commit, **options):
        result = run_link(commit=commit)
        out = self.stdout.write
        out(f'Sales linked: {result.linked_sales} ({result.linked_transactions} installments)')
        out(f'Sales already linked before: {result.already_linked}')
        out(f'Sales left unlinked (amounts do not match): {len(result.not_matching)}')
        if report:
            with open(report, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['sale_id', 'date', 'contact', 'amount', 'installments_found', 'installments_total'])
                for sale, count, total in result.not_matching:
                    writer.writerow([sale.pk, sale.date, sale.contact.name, sale.amount, count, total])
            out(f'Unlinked sales written to {report}')
        if commit:
            out(self.style.SUCCESS('Links committed.'))
        else:
            out(self.style.WARNING('Dry-run: nothing was saved. Use --commit to persist.'))
