"""One-shot import of the legacy "CONTROLE FINANCEIRO" spreadsheet.

Rules (decided from the spreadsheet analysis):
- Subgroup -> group comes from the "Plano de Contas" sheet, not the row's "Grupo" column.
  That's how the spreadsheet DRE groups values (SUMIFS by subgroup name), so the
  imported DRE matches it (except reversals, which now subtract).
- Rows without a usable date, amount, type, status or subgroup are skipped and reported.
- "Produto/Nº Boleto" cells that Excel turned into dates were installments ("3/6"):
  they're restored as "day/month" text.
- Company comes from column K; blank rows go to a default company.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pghistory
from django.db import transaction
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance.models import Contact, Group, SubGroup, Transaction, TransactionStatus, TransactionType

PLAN_SHEET = 'Plano de Contas'
ENTRIES_SHEET = 'Lançamentos'

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
class ImportResult:
    plan: dict[str, str]
    entries: list[Entry]
    skipped: list[Skipped]
    subgroups_created: int = 0
    contacts_created: int = 0
    transactions_created: int = 0


def import_spreadsheet(path, *, default_company: Company, companies: dict[str, Company]) -> ImportResult:
    """Run inside the caller's transaction; the caller decides commit or rollback."""
    wb = load_workbook(path, read_only=True, data_only=True)
    plan = read_plan(wb)
    entries, skipped = read_entries(wb, plan)
    result = ImportResult(plan=plan, entries=entries, skipped=skipped)

    unmapped = sorted({e.company for e in entries if e.company and e.company not in companies})
    if unmapped:
        raise ValueError(f'Companies without mapping: {unmapped}')
    if Transaction.objects.exists():
        raise ValueError('Transactions already exist; the import only runs on an empty database')

    subgroups = {}
    for name, group in plan.items():
        subgroups[name], created = SubGroup.objects.get_or_create(name=name, group=group)
        result.subgroups_created += created

    contacts = {_contact_key(c.name): c for c in Contact.objects.all()}
    for entry in entries:
        key = _contact_key(entry.contact)
        if entry.contact and key not in contacts:
            contacts[key] = Contact.objects.create(name=entry.contact)
            result.contacts_created += 1

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
    return result
