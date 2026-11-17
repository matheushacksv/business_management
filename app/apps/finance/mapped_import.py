"""Import transactions from any .xlsx/.csv with user-chosen column mapping.

Stateless: every call gets the file again plus the mapping. `inspect_file` shows the
columns; `run_mapped_import` converts every row (dry run) or creates the transactions.

Each system field comes from a column or a fixed value. Values that don't match the
system (subgroup "Aluguel Sede", company "HENRIQUECEDOR", type "C"...) are reported as
`unknown` so the user maps them once (`value_maps`) for every row with that value.
"""

import csv
import datetime as dt
import io
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction
from openpyxl import load_workbook

from apps.companies.services import list_companies_service
from apps.finance.models import (
    NATURAL_TYPE, Account, Contact, Group, SubGroup, Transaction, TransactionStatus, TransactionType,
)
from apps.users.models import User

MAX_UPLOAD_SIZE = 20 * 1024 * 1024
MAX_ROWS = 10_000
SAMPLES = 3
PREVIEW_ROWS = 50
ERRORS_SHOWN = 200
FIELDS = ('date', 'amount', 'type', 'subgroup', 'status', 'company', 'account', 'contact', 'reference', 'notes')
MAPPABLE = ('type', 'status', 'subgroup', 'company', 'account')  # fields whose unknown values the user maps

TYPE_WORDS = {
    TransactionType.INFLOW: {'entrada', 'entradas', 'c', 'credito', 'receita', 'receitas', 'recebimento', '+'},
    TransactionType.OUTFLOW: {'saida', 'saidas', 'd', 'debito', 'despesa', 'despesas', 'pagamento', '-'},
}
STATUS_WORDS = {
    TransactionStatus.REALIZED: {'realizado', 'realizada', 'pago', 'paga', 'recebido', 'recebida', 'liquidado',
                                 'compensado', 'efetivado', 'sim', 'ok'},
    TransactionStatus.PLANNED: {'previsto', 'prevista', 'pendente', 'aberto', 'em aberto', 'a pagar',
                                'a receber', 'agendado', 'nao'},
}


def norm(value) -> str:
    """Matching key: no accents, case or extra spaces ("  Aluguél " == "aluguel")."""
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return ' '.join(text.casefold().split())


def _text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, dt.datetime):
        return value.strftime('%d/%m/%Y') if value.time() == dt.time() else value.strftime('%d/%m/%Y %H:%M')
    if isinstance(value, dt.date):
        return value.strftime('%d/%m/%Y')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return ' '.join(str(value).split())


# Reading the file

def _read_rows(file, sheet: str | None) -> tuple[list[str], str | None, list[list]]:
    """(sheet names, sheet used, rows as lists) for .xlsx; ([], None, rows) for .csv."""
    name = (file.name or '').lower()
    if file.size > MAX_UPLOAD_SIZE:
        raise ValidationError(f'File too large (max {MAX_UPLOAD_SIZE // (1024 * 1024)} MB)')
    file.seek(0)
    if name.endswith('.xlsx'):
        wb = load_workbook(file, read_only=True, data_only=True)
        sheets = wb.sheetnames
        used = sheet if sheet in sheets else sheets[0]
        rows = [list(r) for r in wb[used].iter_rows(values_only=True)]
        wb.close()
        return sheets, used, rows
    if name.endswith('.csv'):
        raw = file.read()
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')  # Excel "CSV" saved on Windows in Brazil
        try:
            dialect = csv.Sniffer().sniff(text[:5000], delimiters=';,\t|')
        except csv.Error:  # one-column or odd files: guess by counting separators
            delimiter = ';' if text[:5000].count(';') > text[:5000].count(',') else ','
            return [], None, list(csv.reader(io.StringIO(text), delimiter=delimiter))
        return [], None, list(csv.reader(io.StringIO(text), dialect))
    raise ValidationError('Expected an .xlsx or .csv file')


def _is_blank(row) -> bool:
    return all(_text(v) == '' for v in row)


def _detect_header(rows: list[list]) -> int:
    """1-based number of the first row with at least 2 text cells (titles above it are skipped)."""
    for i, row in enumerate(rows[:30]):
        texts = [v for v in row if isinstance(v, str) and v.strip() and not _parse_amount(v)[0]]
        if len(texts) >= 2:
            return i + 1
    return 1


def _table(file, sheet: str | None, header_row: int | None):
    sheets, used, rows = _read_rows(file, sheet)
    header_row = header_row or _detect_header(rows)
    if header_row < 1 or header_row > max(len(rows), 1):
        raise ValidationError('Header row is out of the file')
    header = rows[header_row - 1] if rows else []
    body = [(header_row + 1 + i, row) for i, row in enumerate(rows[header_row:]) if not _is_blank(row)]
    if len(body) > MAX_ROWS:
        raise ValidationError(f'Too many rows ({len(body)}); the limit is {MAX_ROWS} per import')
    width = max([len(header)] + [len(r) for _, r in body[:200]] or [0])
    headers = [_text(header[i]) if i < len(header) else '' for i in range(width)]
    return sheets, used, header_row, headers, body


def inspect_file(file, *, sheet: str | None = None, header_row: int | None = None) -> dict:
    sheets, used, header_row, headers, body = _table(file, sheet, header_row)
    columns = [
        {'index': i, 'header': h or f'Coluna {i + 1}',
         'samples': [_text(r[i]) if i < len(r) else '' for _, r in body[:SAMPLES]]}
        for i, h in enumerate(headers)
    ]
    return {'sheets': sheets, 'sheet': used, 'header_row': header_row, 'columns': columns, 'total_rows': len(body)}


# Parsing values

def _parse_amount(value) -> tuple[Decimal | None, bool]:
    """(absolute amount, is negative). Accepts numbers, "1.234,56", "R$ -10,00", "(10,00)", "10,00-"."""
    if isinstance(value, bool) or value is None:
        return None, False
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    else:
        text = str(value).strip().replace('R$', '').replace('\xa0', '').replace(' ', '')
        negative = text.startswith('(') and text.endswith(')') or text.endswith('-')
        text = text.strip('()').rstrip('-')
        if not text or not re.fullmatch(r'[+-]?[\d.,]+', text):
            return None, False
        if ',' in text and '.' in text:  # the last separator is the decimal one
            text = text.replace('.', '').replace(',', '.') if text.rfind(',') > text.rfind('.') else text.replace(',', '')
        elif ',' in text:
            text = text.replace('.', '').replace(',', '.')
        elif text.count('.') > 1 or re.fullmatch(r'[+-]?\d{1,3}\.\d{3}', text):
            # ponytail: "1.234" is read as one thousand (Brazilian files); "1.5" stays one and a half
            text = text.replace('.', '')
        try:
            number = Decimal(text)
        except InvalidOperation:
            return None, False
        if negative:
            number = -abs(number)
    return abs(number).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), number < 0


DATE_FORMATS = ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d', '%d-%m-%Y', '%d.%m.%Y', '%Y/%m/%d')


def _parse_date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)) and 20000 < value < 80000:  # Excel serial date in a CSV
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(value))
    text = _text(value).split(' ')[0].split('T')[0]
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# Mapping

@dataclass
class Mapping:
    """`columns[field]` = column index; `fixed[field]` = value (id or choice) for every row."""
    columns: dict[str, int] = field(default_factory=dict)
    fixed: dict[str, object] = field(default_factory=dict)
    type_mode: str = 'column'  # column | sign | subgroup | fixed
    value_maps: dict[str, dict[str, object]] = field(default_factory=dict)  # field -> {raw value: id/choice}
    create_contacts: bool = True
    skip_duplicates: bool = True

    @classmethod
    def from_dict(cls, data: dict) -> 'Mapping':
        unknown = set(data.get('columns', {})) - set(FIELDS) | set(data.get('fixed', {})) - set(FIELDS)
        if unknown:
            raise ValidationError(f'Unknown fields: {sorted(unknown)}')
        return cls(
            columns={k: int(v) for k, v in data.get('columns', {}).items() if v is not None},
            fixed={k: v for k, v in data.get('fixed', {}).items() if v not in (None, '')},
            type_mode=data.get('type_mode', 'column'),
            value_maps={f: {norm(k): v for k, v in m.items() if v not in (None, '')}
                        for f, m in data.get('value_maps', {}).items() if f in MAPPABLE},
            create_contacts=bool(data.get('create_contacts', True)),
            skip_duplicates=bool(data.get('skip_duplicates', True)),
        )


class _Lookups:
    """Everything a row can point to, loaded once (visible to the user only)."""

    def __init__(self, user: User):
        self.companies = {c.pk: c for c in list_companies_service(user=user)}
        self.company_keys = {}
        for c in self.companies.values():
            self.company_keys[norm(c.name)] = c
            self.company_keys[re.sub(r'\D', '', c.cnpj or '')] = c
        self.subgroups = {s.pk: s for s in SubGroup.objects.exclude(group=Group.TRANSFER)}
        names = Counter(norm(s.name) for s in self.subgroups.values())
        # Same name in two groups is ambiguous: the user maps it
        self.subgroup_keys = {norm(s.name): s for s in self.subgroups.values() if names[norm(s.name)] == 1}
        self.accounts = {a.pk: a for a in Account.objects.filter(company__in=self.companies.values())}
        self.contacts = {norm(c.name): c for c in Contact.objects.all()}


@dataclass
class _Row:
    row: int
    date: dt.date
    amount: Decimal
    type: str
    status: str
    subgroup: SubGroup
    company: object
    account: Account | None
    contact_name: str
    reference: str
    notes: str
    duplicate: bool = False


def _resolve(field_name: str, raw, mapped, lookups: _Lookups, company=None):
    """Raw cell (or the user's choice `mapped`: id/choice) -> system value; None when unknown."""
    key = norm(raw)
    if field_name == 'type':
        if mapped in TransactionType.values:
            return mapped
        return next((t for t, words in TYPE_WORDS.items() if key in words), None)
    if field_name == 'status':
        if mapped in TransactionStatus.values:
            return mapped
        return next((s for s, words in STATUS_WORDS.items() if key in words), None)
    if field_name == 'subgroup':
        return lookups.subgroups.get(_int(mapped)) or lookups.subgroup_keys.get(key)
    if field_name == 'company':
        return (lookups.companies.get(_int(mapped)) or lookups.company_keys.get(key)
                or lookups.company_keys.get(re.sub(r'\D', '', key) or '-'))
    if field_name == 'account':
        account = lookups.accounts.get(_int(mapped)) or next(
            (a for a in lookups.accounts.values() if norm(a.name) == key and a.company_id == company.pk), None)
        return account if account and account.company_id == company.pk else None
    raise AssertionError(field_name)


def _int(value) -> int | None:
    try:
        return int(value)  # type:ignore
    except (TypeError, ValueError):
        return None


def _convert(number: int, row: list, mapping: Mapping, lookups: _Lookups, unknown: dict[str, Counter]):
    """One file row -> (_Row, None) or (None, error dict)."""
    def cell(field_name):
        index = mapping.columns.get(field_name)
        return row[index] if index is not None and index < len(row) else None

    def error(field_name, code, value=None):
        return None, {'row': number, 'field': field_name, 'code': code, 'value': _text(value)[:80]}

    def pick(field_name, company=None):
        """Fixed value or the column's value, resolved. Returns (value, error)."""
        if field_name in mapping.fixed:
            fixed = mapping.fixed[field_name]
            value = _resolve(field_name, '', fixed, lookups, company)
            return (value, None) if value else error(field_name, 'invalid_fixed', fixed)
        raw = cell(field_name)
        if _text(raw) == '':
            return error(field_name, 'missing')
        mapped = mapping.value_maps.get(field_name, {}).get(norm(raw))
        value = _resolve(field_name, raw, mapped, lookups, company)
        if value is None:
            unknown.setdefault(field_name, Counter())[_text(raw)] += 1
            return error(field_name, 'unknown', raw)
        return value, None

    raw_date = cell('date')
    date = _parse_date(raw_date)
    if date is None:
        return error('date', 'missing' if _text(raw_date) == '' else 'invalid_date', raw_date)
    raw_amount = cell('amount')
    amount, negative = _parse_amount(raw_amount)
    if amount is None:
        return error('amount', 'missing' if _text(raw_amount) == '' else 'invalid_amount', raw_amount)
    if amount == 0:
        return error('amount', 'zero_amount', raw_amount)

    subgroup, err = pick('subgroup')
    if err:
        return None, err
    if mapping.type_mode == 'sign':
        type_ = TransactionType.OUTFLOW if negative else TransactionType.INFLOW
    elif mapping.type_mode == 'subgroup':
        type_ = NATURAL_TYPE[subgroup.group]
    else:
        type_, err = pick('type')
        if err:
            return None, err
    if 'status' in mapping.columns or 'status' in mapping.fixed:
        status, err = pick('status')
        if err:
            return None, err
    else:
        status = TransactionStatus.REALIZED
    company, err = pick('company')
    if err:
        return None, err
    account = None
    if 'account' in mapping.columns or 'account' in mapping.fixed:
        if 'account' in mapping.fixed or _text(cell('account')):
            account, err = pick('account', company)
            if err:
                return None, err

    return _Row(
        row=number, date=date, amount=amount, type=type_, status=status, subgroup=subgroup,
        company=company, account=account, contact_name=_text(cell('contact'))[:160],
        reference=_text(cell('reference'))[:120], notes=_text(cell('notes')),
    ), None


def _mark_duplicates(rows: list[_Row]) -> None:
    """Same company, date, amount, type and subgroup as an existing transaction."""
    if not rows:
        return
    existing = set(
        Transaction.objects.filter(
            company__in={r.company.pk for r in rows},
            date__range=(min(r.date for r in rows), max(r.date for r in rows)),
        ).values_list('company_id', 'date', 'amount', 'type', 'subgroup_id')
    )
    for r in rows:
        r.duplicate = (r.company.pk, r.date, r.amount, r.type, r.subgroup.pk) in existing


def run_mapped_import(
    file, *, user: User, mapping: dict, sheet: str | None = None, header_row: int | None = None,
    commit: bool = False,
) -> dict:
    """Dry run (commit=False) or create the valid rows. Requires transactions:create (checked by the API)."""
    mapping_ = Mapping.from_dict(mapping)
    for required in ('date', 'amount'):
        if required not in mapping_.columns:
            raise ValidationError(f'Map a column to "{required}"')
    for required in ('subgroup', 'company'):
        if required not in mapping_.columns and required not in mapping_.fixed:
            raise ValidationError(f'Map a column or a fixed value to "{required}"')
    if mapping_.type_mode not in ('column', 'sign', 'subgroup', 'fixed'):
        raise ValidationError('Invalid type mode')
    if mapping_.type_mode in ('column', 'fixed') and 'type' not in mapping_.columns and 'type' not in mapping_.fixed:
        raise ValidationError('Map the type: a column, a fixed value, the amount sign or the subgroup')

    _, _, header_row, _, body = _table(file, sheet, header_row)
    lookups = _Lookups(user)
    rows, errors, unknown = [], [], {}
    for number, raw in body:
        converted, err = _convert(number, raw, mapping_, lookups, unknown)
        (rows.append(converted) if converted else errors.append(err))
    _mark_duplicates(rows)
    to_create = [r for r in rows if not (mapping_.skip_duplicates and r.duplicate)]
    new_contacts = sorted({r.contact_name for r in to_create
                           if r.contact_name and norm(r.contact_name) not in lookups.contacts})

    result = {
        'committed': False, 'header_row': header_row, 'total_rows': len(body),
        'valid_count': len(rows), 'error_count': len(errors),
        'duplicate_count': sum(r.duplicate for r in rows), 'to_create': len(to_create),
        'new_contacts': len(new_contacts) if mapping_.create_contacts else 0,
        'errors': errors[:ERRORS_SHOWN],
        'unknown': {f: [{'value': v, 'count': n} for v, n in c.most_common()] for f, c in unknown.items()},
        'preview': [_row_out(r) for r in rows[:PREVIEW_ROWS]],
        'created': 0,
    }
    if not commit:
        return result
    if not to_create:
        raise ValidationError('Nothing to import')

    with transaction.atomic(), pghistory.context(user=user.pk, source='transaction_import'):
        if mapping_.create_contacts:
            for name in new_contacts:
                lookups.contacts[norm(name)] = Contact.objects.create(name=name)
        created = Transaction.objects.bulk_create(
            Transaction(
                company=r.company, subgroup=r.subgroup, account=r.account,
                contact=lookups.contacts.get(norm(r.contact_name)) if r.contact_name else None,
                date=r.date, amount=r.amount, type=r.type, status=r.status,
                reference=r.reference, notes=r.notes,
            )
            for r in to_create
        )
    result.update(committed=True, created=len(created))
    return result


def _row_out(r: _Row) -> dict:
    return {
        'row': r.row, 'date': r.date, 'amount': r.amount, 'type': r.type, 'status': r.status,
        'subgroup_name': r.subgroup.name, 'company_name': r.company.name,
        'account_name': r.account.name if r.account else None, 'contact_name': r.contact_name or None,
        'reference': r.reference, 'notes': r.notes, 'duplicate': r.duplicate,
    }
