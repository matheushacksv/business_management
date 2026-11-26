"""One-shot import of the legacy collection data, run right after `import_spreadsheet`.

- Rows of "Lançamentos" picked by the client (customer in a collection action) have no date:
  they get an estimated one, monthly after that customer's last dated row above them
  (the "Produto/Nº Boleto" column holds the installment number, not a date). They are linked
  to one case per customer + company, which also links the customer's other planned inflows.
- The "Contratos Cancelados ou Ação de..." sheet fills the case fields (contract value,
  amount received, reason, closer/advisor) when its customer name matches.
"""

import datetime as dt
import difflib
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal

import pghistory
from django.db import transaction
from openpyxl import load_workbook

from apps.companies.models import Company
from apps.finance.importer import ENTRIES_SHEET, Entry, _contact_key, _text, parse_entry, read_plan
from apps.finance.services import add_months
from apps.finance.models import Contact, SubGroup, Transaction, TransactionStatus, TransactionType
from apps.legal.models import CaseComment, CollectionCase

CASES_SHEET_PREFIX = 'Contratos Cancelados'
STOPWORDS = {'de', 'do', 'da', 'dos', 'das', 'e', 'grupo', 'group', 'ltda', 'me'}


def _tokens(name: str) -> list[str]:
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().casefold()
    words = ''.join(c if c.isalnum() else ' ' for c in plain).split()
    return [w for w in words if len(w) >= 3 and w not in STOPWORDS]


def _similarity(a: str, b: str) -> int:
    """How many words of `a` have a close match in `b` (typos like Wiitech/Wittech count)."""
    tb = _tokens(b)
    return sum(1 for w in _tokens(a) if difflib.get_close_matches(w, tb, n=1, cutoff=0.8))


@dataclass
class CaseRow:
    client: str
    reason: str
    action: str
    contract: Decimal | None
    received: Decimal | None
    closer: str
    advisor: str


@dataclass
class Result:
    rows_imported: int = 0
    rows_skipped: list[tuple[int, str]] = field(default_factory=list)
    cases: list[tuple[str, str, int, Decimal, str | None]] = field(default_factory=list)  # contact, company, linked, open, sheet match
    unmatched_sheet_rows: list[str] = field(default_factory=list)


def _money(value) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal('0.01')) if value not in (None, '') else None
    except ArithmeticError:
        return None


def read_case_rows(wb) -> list[CaseRow]:
    sheet = next((wb[n] for n in wb.sheetnames if n.startswith(CASES_SHEET_PREFIX)), None)
    if sheet is None:
        return []
    rows = []
    for values in sheet.iter_rows(min_row=2, max_col=9, values_only=True):
        _month, client, reason, action, contract, received, _due, closer, advisor = values
        if _text(client):
            rows.append(CaseRow(_text(client), _text(reason), _text(action), _money(contract),
                                _money(received), _text(closer), _text(advisor)))
    return rows


def import_collection(file, *, rows: set[int], default_company: Company, companies: dict[str, Company]) -> Result:
    """Run inside the caller's transaction (dry-run = rollback)."""
    if CollectionCase.objects.exists():
        raise ValueError('Collection cases already exist; this import only runs once')
    wb = load_workbook(file, read_only=True, data_only=True)
    plan = read_plan(wb)
    result = Result()

    entries: list[Entry] = []
    last_date: dict[str, dt.date] = {}  # contact -> last dated row so far
    undated: dict[str, int] = {}
    for row_number, values in enumerate(wb[ENTRIES_SHEET].iter_rows(min_row=3, max_col=11, values_only=True), start=3):
        values = list(values) + [None] * (11 - len(values))
        key = _contact_key(_text(values[2]))
        if isinstance(values[1], dt.datetime):
            last_date[key], undated[key] = values[1].date(), 0
        if row_number not in rows:
            continue
        if values[1] is None:  # estimated: monthly after the customer's last dated row
            undated[key] = undated.get(key, 0) + 1
            values[1] = add_months(last_date.get(key, dt.date.today()), undated[key])
        parsed = parse_entry(row_number, tuple(values), plan)
        if isinstance(parsed, Entry):
            entries.append(parsed)
        else:
            result.rows_skipped.append((row_number, parsed.reason))

    unmapped = sorted({e.company for e in entries if e.company and e.company not in companies})
    if unmapped:
        raise ValueError(f'Companies without mapping: {unmapped}')

    contacts = {_contact_key(c.name): c for c in Contact.objects.all()}
    subgroups = {(s.name, s.group): s for s in SubGroup.objects.all()}
    by_case: dict[tuple[int, int], list[Transaction]] = {}
    with pghistory.context(source='collection_import'):
        for e in entries:
            if not e.contact:
                result.rows_skipped.append((e.row, 'missing contact'))
                continue
            contact = contacts.get(_contact_key(e.contact))
            if contact is None:
                contact = contacts[_contact_key(e.contact)] = Contact.objects.create(name=e.contact)
            subgroup = subgroups.get((e.subgroup, plan[e.subgroup]))
            if subgroup is None:
                raise ValueError(f'Subgroup {e.subgroup!r} not found: run import_spreadsheet first')
            company = companies.get(e.company, default_company)
            tx = Transaction.objects.create(
                company=company, subgroup=subgroup, contact=contact, date=e.date, amount=e.amount,
                type=e.type, status=e.status, reference=e.reference, notes=e.notes,
            )
            by_case.setdefault((company.pk, contact.pk), []).append(tx)
            result.rows_imported += 1

        sheet_rows = read_case_rows(wb)
        names = {key: Contact.objects.get(pk=key[1]).name for key in by_case}
        # Best pairs first, so a weak match never takes the row of a strong one
        pairs = sorted(((_similarity(r.client, names[key]), i, key) for key in by_case
                        for i, r in enumerate(sheet_rows)), key=lambda p: -p[0])
        match: dict[tuple[int, int], int] = {}
        for score, i, key in pairs:
            if score and key not in match and i not in match.values():
                match[key] = i
        matched = set(match.values())
        for (company_id, contact_id), _txs in by_case.items():
            name = names[(company_id, contact_id)]
            row = sheet_rows[match[(company_id, contact_id)]] if (company_id, contact_id) in match else None
            if row:
                summary = (f'{row.reason or "Inadimplente"}. Ação de cobrança: {row.action or "-"}. '
                           f'Closer: {row.closer or "-"}. Assessor: {row.advisor or "-"}.')
            else:
                summary = ''
            case = CollectionCase.objects.create(
                company_id=company_id, contact_id=contact_id, summary=summary,
                proposal_amount=row.contract if row else None, paid_amount=row.received if row else None,
            )
            linked = Transaction.objects.filter(
                company_id=company_id, contact_id=contact_id, type=TransactionType.INFLOW,
                status=TransactionStatus.PLANNED, collection_case__isnull=True,
            ).update(collection_case=case)
            CaseComment.objects.create(case=case, text=(
                f'Importado da planilha: {linked} parcela(s) em aberto vinculada(s). '
                'Complete os campos obrigatórios (empresa, contato, o que foi entregue, link do drive).'))
            open_amount = sum((t.amount for t in case.transactions.filter(status=TransactionStatus.PLANNED)), Decimal('0'))
            result.cases.append((name, Company.objects.get(pk=company_id).name, linked, open_amount,
                                 row.client if row else None))
        result.unmatched_sheet_rows = [r.client for i, r in enumerate(sheet_rows) if i not in matched]
    return result


class _Rollback(Exception):
    pass


def run_collection_import(file, *, commit: bool, **kwargs) -> Result:
    try:
        with transaction.atomic():
            result = import_collection(file, **kwargs)
            if not commit:
                raise _Rollback(result)
    except _Rollback as rollback:
        result = rollback.args[0]
    return result
