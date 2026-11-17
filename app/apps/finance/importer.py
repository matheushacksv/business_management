"""One-shot import of the legacy "CONTROLE FINANCEIRO" spreadsheet.

Rules (decided from the spreadsheet analysis):
- Subgroup -> group comes from the "Plano de Contas" sheet, not the row's "Grupo" column.
  That's how the spreadsheet DRE groups values (SUMIFS by subgroup name), so the
  imported DRE matches it (except reversals, which now subtract).
- Rows without a usable date, amount, type, status or subgroup are skipped and reported.
- "Produto/Nº Boleto" cells that Excel turned into dates were installments ("3/6"):
  they're restored as "day/month" text.
- Company comes from column K; blank rows go to a default company.
- "Vendas" sheet becomes Sales (feeds "Faturamento Bruto"). It has no company column:
  a "Forma de Pagamento" equal to a mapped company name picks that company, else the default.
  Products are deduplicated ignoring case/spaces; "N parcelas" in the terms fills installments.
"""

import datetime as dt
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pghistory
from django.db import transaction
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance.models import Contact, Group, SubGroup, Transaction, TransactionStatus, TransactionType
from apps.sales.models import Product, Sale

PLAN_SHEET = 'Plano de Contas'
ENTRIES_SHEET = 'Lançamentos'
SALES_SHEET = 'Vendas'

# "Plano de Contas": columns C..G, one group per column, subgroups from row 4 down
PLAN_COLUMNS = [
    Group.OPERATING_REVENUE,
    Group.NON_OPERATING_REVENUE,
    Group.VARIABLE_COSTS,
    Group.FIXED_COSTS,
    Group.NON_OPERATING_EXPENSES,
]
TYPES = {'Entradas': TransactionType.INFLOW, 'Saídas': TransactionType.OUTFLOW}
STATUSES = {'Realizado': TransactionStatus.REALIZED, 'Previsto': TransactionStatus.PLANNED}
EMPTY_MARKERS = {'', '-', '--'}


@dataclass
class Entry:
    row: int
    date: dt.date
    contact: str
    amount: Decimal
    type: str
    reference: str
    subgroup: str
    status: str
    notes: str
    company: str


@dataclass
class Skipped:
    row: int
    reason: str
    values: tuple


def _text(value) -> str:
    text = ' '.join(str(value).split()) if value is not None else ''
    return '' if text in EMPTY_MARKERS else text


def _contact_key(name: str) -> str:
    return name.casefold()


def read_plan(wb) -> dict[str, str]:
    """subgroup name -> group"""
    plan = {}
    for row in wb[PLAN_SHEET].iter_rows(min_row=4, min_col=3, max_col=7, values_only=True):
        for group, cell in zip(PLAN_COLUMNS, row):
            name = _text(cell)
            if name:
                plan[name] = group
    return plan


def parse_entry(row_number: int, values: tuple, plan: dict[str, str]) -> Entry | Skipped:
    date, contact, amount, type_, reference, _group, subgroup, status, notes, company = values[1:11]

    def skip(reason):
        return Skipped(row_number, reason, values[1:11])

    if isinstance(date, dt.datetime):
        date = date.date()
    if not isinstance(date, dt.date):
        return skip('missing date' if date is None else f'invalid date: {date!r}')
    try:
        amount = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return skip(f'invalid amount: {amount!r}')
    if amount <= 0:
        return skip('zero amount')
    if type_ not in TYPES:
        return skip(f'invalid type: {type_!r}')
    if status not in STATUSES:
        return skip(f'invalid status: {status!r}')
    subgroup = _text(subgroup)
    if subgroup not in plan:
        return skip(f'unknown subgroup: {subgroup!r}' if subgroup else 'missing subgroup')

    if isinstance(reference, dt.datetime):  # Excel turned "3/6" (installment) into a date
        reference = f'{reference.day}/{reference.month}'

    return Entry(
        row=row_number, date=date, contact=_text(contact)[:160], amount=amount,
        type=TYPES[type_], reference=_text(reference)[:120], subgroup=subgroup,
        status=STATUSES[status], notes=_text(notes), company=_text(company),
    )


def read_entries(wb, plan: dict[str, str]) -> tuple[list[Entry], list[Skipped]]:
    entries, skipped = [], []
    for row_number, values in enumerate(
        wb[ENTRIES_SHEET].iter_rows(min_row=3, max_col=11, values_only=True), start=3
    ):
        values = tuple(values) + (None,) * (11 - len(values))
        if all(_text(v) == '' for v in values[1:10]):
            continue  # blank row
        result = parse_entry(row_number, values, plan)
        (entries if isinstance(result, Entry) else skipped).append(result)
    return entries, skipped


@dataclass
class SaleEntry:
    row: int
    date: dt.date
    contact: str
    amount: Decimal
    product: str
    payment_method: str
    payment_terms: str
    installments: int | None


INSTALLMENTS_RE = re.compile(r'(\d+)\s*parcela', re.IGNORECASE)


def _installments(terms: str) -> int | None:
    match = INSTALLMENTS_RE.search(terms)
    if not match:
        return 1 if re.search(r'[àa]\s*vista', terms, re.IGNORECASE) else None
    count = int(match.group(1))
    return count + 1 if 'entrada' in terms.lower() else count


def _amount(value) -> Decimal | None:
    try:
        amount = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None
    return amount


def read_sales(wb) -> tuple[list[SaleEntry], list[Skipped]]:
    if SALES_SHEET not in wb.sheetnames:
        return [], []
    sales, skipped = [], []
    for row_number, values in enumerate(
        wb[SALES_SHEET].iter_rows(min_row=3, max_col=7, values_only=True), start=3
    ):
        values = tuple(values) + (None,) * (7 - len(values))
        date, contact, amount, product, method, terms = values[1:7]
        if all(_text(v) == '' for v in values[1:7]):
            continue

        def skip(reason):
            skipped.append(Skipped(row_number, f'sales: {reason}', values[1:7]))

        if isinstance(date, dt.datetime):
            date = date.date()
        if not isinstance(date, dt.date):
            skip('missing date' if date is None else f'invalid date: {date!r}')
            continue
        value = _amount(amount)
        if value is None:
            skip(f'invalid amount: {amount!r}')
            continue
        if value <= 0:
            skip('zero amount')
            continue
        terms = _text(terms)
        sales.append(SaleEntry(
            row=row_number, date=date, contact=_text(contact)[:160], amount=value,
            product=_text(product)[:120], payment_method=_text(method)[:60],
            payment_terms=terms[:120], installments=_installments(terms),
        ))
    return sales, skipped


@dataclass
class ImportResult:
    plan: dict[str, str]
    entries: list[Entry]
    skipped: list[Skipped]
    sales: list[SaleEntry] | None = None
    subgroups_created: int = 0
    contacts_created: int = 0
    transactions_created: int = 0
    products_created: int = 0
    sales_created: int = 0


class UnmappedCompanies(ValueError):
    def __init__(self, names: list[str]):
        self.names = names
        super().__init__(f'Companies without mapping: {names}')


def parse_workbook(file) -> ImportResult:
    """Read and validate the spreadsheet; touches no database rows."""
    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except Exception:  # openpyxl raises zip/xml/format errors of many kinds
        raise ValueError('Invalid spreadsheet: expected an .xlsx file')
    missing = [name for name in (PLAN_SHEET, ENTRIES_SHEET) if name not in wb.sheetnames]
    if missing:
        raise ValueError(f'Spreadsheet is missing the sheets: {missing}')
    plan = read_plan(wb)
    entries, skipped = read_entries(wb, plan)
    sales, sales_skipped = read_sales(wb)
    return ImportResult(plan=plan, entries=entries, skipped=skipped + sales_skipped, sales=sales)


def company_names(result: ImportResult) -> list[str]:
    """Company names found in the "Empresa" column (must be mapped to a Company)."""
    return sorted({e.company for e in result.entries if e.company})


def import_spreadsheet(
    file, *, default_company: Company, companies: dict[str, Company], require_empty: bool = True,
) -> ImportResult:
    """Run inside the caller's transaction; the caller decides commit or rollback.

    `require_empty=False` is for the reconciliation, which imports into throwaway companies
    inside a transaction that is always rolled back.
    """
    result = parse_workbook(file)
    plan, entries, sales = result.plan, result.entries, result.sales or []

    unmapped = [name for name in company_names(result) if name not in companies]
    if unmapped:
        raise UnmappedCompanies(unmapped)
    if require_empty and (Transaction.objects.exists() or Sale.objects.exists()):
        raise ValueError('Transactions/sales already exist; the import only runs on an empty database')

    subgroups = {}
    for name, group in plan.items():
        subgroups[name], created = SubGroup.objects.get_or_create(name=name, group=group)
        result.subgroups_created += created

    contacts = {_contact_key(c.name): c for c in Contact.objects.all()}
    for name in [e.contact for e in entries] + [s.contact for s in sales]:
        key = _contact_key(name)
        if name and key not in contacts:
            contacts[key] = Contact.objects.create(name=name)
            result.contacts_created += 1

    products = {_contact_key(p.name): p for p in Product.objects.all()}
    for sale in sales:
        key = _contact_key(sale.product)
        if sale.product and key not in products:
            products[key] = Product.objects.create(name=sale.product)
            result.products_created += 1

    with transaction.atomic(), pghistory.context(source='spreadsheet_import'):
        created = Transaction.objects.bulk_create(
            Transaction(
                company=companies.get(e.company, default_company),
                subgroup=subgroups[e.subgroup],
                contact=contacts.get(_contact_key(e.contact)) if e.contact else None,
                date=e.date, amount=e.amount, type=e.type, status=e.status,
                reference=e.reference, notes=e.notes,
            )
            for e in entries
        )
    result.transactions_created = len(created)

    with transaction.atomic(), pghistory.context(source='spreadsheet_import'):
        created_sales = Sale.objects.bulk_create(
            Sale(
                company=companies.get(s.payment_method, default_company),
                contact=contacts.get(_contact_key(s.contact)) if s.contact else None,
                product=products.get(_contact_key(s.product)) if s.product else None,
                date=s.date, amount=s.amount, payment_method=s.payment_method,
                payment_terms=s.payment_terms, installments_count=s.installments,
            )
            for s in sales
        )
    result.sales_created = len(created_sales)
    return result


class _Rollback(Exception):
    pass


def run_import(file, *, default_company: Company, companies: dict[str, Company], commit: bool) -> ImportResult:
    """Import, or simulate it (commit=False): everything runs and is rolled back."""
    try:
        with transaction.atomic():
            result = import_spreadsheet(file, default_company=default_company, companies=companies)
            if not commit:
                raise _Rollback(result)
    except _Rollback as rollback:
        result = rollback.args[0]
    return result



# API entry point

MAX_UPLOAD_SIZE = 20 * 1024 * 1024


def import_upload_service(
    *, user, file, default_company_id: int, companies: dict[str, int], commit: bool
) -> dict:
    """Preview (commit=False) or run the import of an uploaded spreadsheet. Admins only.

    The preview always answers, even with unmapped companies, so the frontend can ask
    the user to map each name found in the "Empresa" column.
    """
    from django.core.exceptions import PermissionDenied, ValidationError

    from apps.companies.services import list_companies_service

    if not user.is_admin:
        raise PermissionDenied('Only administrators can import spreadsheets')
    if not (file.name or '').lower().endswith('.xlsx'):
        raise ValidationError('Expected an .xlsx file')
    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError(f'File too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)')

    visible = list_companies_service(user=user)
    default = visible.get(pk=default_company_id)
    found = {c.pk: c for c in visible.filter(pk__in=companies.values())}
    missing = sorted({pk for pk in companies.values() if pk not in found})
    if missing:
        raise ValidationError(f'Companies not found: {missing}')
    mapping = {' '.join(name.split()): found[pk] for name, pk in companies.items()}

    try:
        parsed = parse_workbook(file)
        names = company_names(parsed)
        unmapped = [n for n in names if n not in mapping]
        if unmapped and not commit:
            result = parsed  # parse-only preview: nothing to load until every name is mapped
        else:
            file.seek(0)
            result = run_import(file, default_company=default, companies=mapping, commit=commit)
    except UnmappedCompanies as exc:
        raise ValidationError(f'Map every company before importing: {exc.names}')
    except ValueError as exc:
        raise ValidationError(str(exc))

    return {
        'committed': commit and not unmapped,
        'company_names': names,
        'unmapped_companies': unmapped,
        'transactions_found': len(parsed.entries),
        'sales_found': len(parsed.sales or []),
        'subgroups_created': result.subgroups_created,
        'contacts_created': result.contacts_created,
        'products_created': result.products_created,
        'transactions_created': result.transactions_created,
        'sales_created': result.sales_created,
        'skipped': [{'row': s.row, 'reason': s.reason} for s in parsed.skipped],
    }
