"""Import a bank statement (OFX from any bank, or the C6 Bank PDF) into one account.

Two calls, stateless like the spreadsheet import:
- `analyze_statement_service` reads the file and suggests what to do with each line: create a realized
  transaction (subgroup from the rules learned on earlier imports), settle a planned installment that
  matches it, record a transfer when the other side is another company of the group, or skip it.
- `commit_statement_service` gets the lines back as reviewed by the user and applies them.
"""

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pghistory
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.companies.services import list_companies_service, normalize_cnpj
from apps.finance.mapped_import import norm
from apps.finance.models import (
    Account, Contact, Group, StatementRule, SubGroup, Transaction, TransactionStatus, TransactionType,
)
from apps.finance.services import create_transfer_service, parse_amount
from apps.users.models import User

MAX_SIZE = 10 * 1024 * 1024
SETTLE_BEFORE, SETTLE_AFTER = 60, 15  # days: a customer may pay late (or a bit early)


@dataclass
class Line:
    date: dt.date
    amount: Decimal  # positive
    type: str
    description: str

    @property
    def party(self) -> str:
        """The other side of a Pix ("Pix enviado para X" -> X)."""
        m = re.match(r'pix (?:enviado para|recebido de)\s+(.+)', self.description, re.I)
        return m.group(1).strip(' .') if m else ''


@dataclass
class Statement:
    lines: list[Line]
    cnpj: str = ''
    totals: tuple[Decimal, Decimal] | None = None  # inflows, outflows as printed by the bank


# Reading

def read_statement(file) -> Statement:
    if file.size and file.size > MAX_SIZE:
        raise ValidationError('File too large')
    data = file.read()
    if data.startswith(b'%PDF'):
        return _read_c6_pdf(data)
    text = data.decode('utf-8', errors='replace') if b'\xef\xbb\xbf' in data[:3] or _is_utf8(data) else data.decode('latin-1')
    if '<OFX>' in text.upper():
        return _read_ofx(text)
    raise ValidationError('Formato não reconhecido: envie o extrato em OFX ou o PDF do C6 Bank')


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


def _line(date: dt.date, signed: Decimal, description: str) -> Line | None:
    if not signed:
        return None
    return Line(date=date, amount=abs(signed), description=' '.join(description.split())[:200],
                type=TransactionType.INFLOW if signed > 0 else TransactionType.OUTFLOW)


def _read_ofx(text: str) -> Statement:
    """OFX 1.x (SGML, tags may be left open) or 2.x (XML)."""
    lines = []
    for block in re.findall(r'<STMTTRN>(.*?)(?=</STMTTRN>|<STMTTRN>|</BANKTRANLIST>)', text, re.S | re.I):
        tag = lambda name: (re.search(rf'<{name}>([^<\r\n]*)', block, re.I) or [None, ''])[1].strip()  # noqa: E731
        try:
            date = dt.datetime.strptime(tag('DTPOSTED')[:8], '%Y%m%d').date()
            signed = Decimal(tag('TRNAMT').replace(',', '.'))
        except (ValueError, InvalidOperation):
            continue
        line = _line(date, signed, tag('MEMO') or tag('NAME'))
        if line:
            lines.append(line)
    if not lines:
        raise ValidationError('Nenhum lançamento encontrado no OFX')
    return Statement(lines=lines)


C6_LINE = re.compile(r'^\s*(\d{2})/(\d{2})\s+\d{2}/\d{2}\s+(.+?)\s{2,}(.+?)\s{2,}(-?)R\$\s*([\d.]+,\d{2})\s*$')
C6_SECTION = re.compile(r'\(\s*\d{2}/\d{2}/(\d{4})\s*-')
C6_TOTALS = re.compile(r'Entradas:\s*R\$\s*([\d.]+,\d{2}).*?Sa[ií]das:\s*R\$\s*([\d.]+,\d{2})')


def _read_c6_pdf(data: bytes) -> Statement:
    """C6 Bank "Extrato da conta" export. Lines carry only day/month: the year comes from the month section."""
    from pypdf import PdfReader
    try:
        text = '\n'.join(p.extract_text(extraction_mode='layout') for p in PdfReader(BytesIO(data)).pages)
    except Exception:  # pypdf raises many types on broken files
        raise ValidationError('Não foi possível ler o PDF')
    return parse_c6_text(text)


def parse_c6_text(text: str) -> Statement:
    cnpj = re.search(r'CNPJ:\s*([\d./-]+)', text)
    year, inflows, outflows, lines = None, Decimal('0'), Decimal('0'), []
    for raw in text.splitlines():
        if (m := C6_SECTION.search(raw)) and not C6_LINE.match(raw):
            year = int(m.group(1))
        if t := C6_TOTALS.search(raw):
            inflows += parse_amount(t.group(1)) or 0
            outflows += parse_amount(t.group(2)) or 0
        m = C6_LINE.match(raw)
        if m and year:
            day, month, _kind, description, minus, value = m.groups()
            amount = parse_amount(value)
            line = amount and _line(dt.date(year, int(month), int(day)), -amount if minus else amount, description)
            if line:
                lines.append(line)
    if not lines:
        raise ValidationError('Nenhum lançamento encontrado: o PDF é o extrato do C6 Bank?')
    return Statement(lines=lines, cnpj=normalize_cnpj(cnpj.group(1)) if cnpj else '', totals=(inflows, outflows))


# Suggestions

def _company_key(name: str) -> str:
    words = [w for w in norm(name).replace('.', ' ').split() if w not in {'ltda', 'me', 'eireli', 'sa', 's/a', 'epp'}]
    return ''.join(words)


def _is_investment(description: str) -> bool:
    return bool(re.search(r'\bcdb\b|aplica[cç][aã]o|resgate', norm(description)))


def _account_for(user: User, account_id: int) -> Account:
    account = Account.objects.select_related('company').filter(
        pk=account_id, company__in=list_companies_service(user=user)).first()
    if account is None:
        raise ValidationError('Account does not exist')
    return account


def analyze_statement_service(*, user: User, account_id: int, file) -> dict:
    account = _account_for(user, account_id)
    company = account.company
    statement = read_statement(file)
    lines = sorted(statement.lines, key=lambda l: l.date)
    warnings = []
    if statement.cnpj and statement.cnpj != company.cnpj:
        warnings.append(f'O CNPJ do extrato ({statement.cnpj}) não é o da empresa da conta ({company.cnpj})')
    if statement.totals:
        got = (sum((l.amount for l in lines if l.type == TransactionType.INFLOW), Decimal('0')),
               sum((l.amount for l in lines if l.type == TransactionType.OUTFLOW), Decimal('0')))
        if got != statement.totals:
            warnings.append(f'Soma lida (entradas {got[0]}, saídas {got[1]}) diferente dos totais do extrato '
                            f'({statement.totals[0]}, {statement.totals[1]}): confira se faltou alguma linha')

    first, last = lines[0].date, lines[-1].date
    # duplicates: realized transactions already in the company with the same date, amount and type
    # (counted: two equal Pix on the same day are two lines)
    existing = Counter(Transaction.objects.filter(
        company=company, status=TransactionStatus.REALIZED, date__range=(first, last),
    ).values_list('date', 'amount', 'type'))
    rules = {(r.key, r.type): r.subgroup_id for r in StatementRule.objects.all()}  # type:ignore
    others = {_company_key(c.name): c for c in list_companies_service(user=user).exclude(pk=company.pk)}
    planned = list(Transaction.objects.filter(
        company=company, status=TransactionStatus.PLANNED, transfer__isnull=True,
        date__range=(first - dt.timedelta(days=SETTLE_AFTER), last + dt.timedelta(days=SETTLE_BEFORE)),
    ).select_related('contact', 'subgroup'))
    used: set[int] = set()

    out = []
    for i, line in enumerate(lines):
        key = (line.date, line.amount, line.type)
        duplicate = existing[key] > 0
        if duplicate:
            existing[key] -= 1
        suggestion: dict = {'action': 'skip' if duplicate else 'create', 'subgroup_id': rules.get((norm(line.description), line.type))}
        other = others.get(_company_key(line.party)) if line.party else None
        match = None if duplicate or other else _match(line, planned, used)
        if duplicate:
            pass  # skipped by default; the user may still import it
        elif other:
            suggestion.update(action='transfer', company_id=other.pk)
        elif match:
            used.add(match.pk)
            suggestion.update(action='settle', match_id=match.pk)
        elif _is_investment(line.description) and not suggestion['subgroup_id']:
            suggestion['action'] = 'skip'
        out.append({
            'index': i, 'date': line.date, 'amount': line.amount, 'type': line.type, 'description': line.description,
            'party': line.party, 'duplicate': duplicate, **suggestion,
            'match_label': _label(match) if match else None,
        })
    return {
        'account_id': account.pk, 'company_id': company.pk, 'company_name': company.name, 'warnings': warnings,
        'lines': out, 'candidates': [{'id': t.pk, 'label': _label(t), 'type': t.type, 'amount': t.amount} for t in planned],
    }


def _match(line: Line, planned: list[Transaction], used: set[int]) -> Transaction | None:
    """Planned transaction of the same type and amount around the date; same customer first, then closest date."""
    window = (line.date - dt.timedelta(days=SETTLE_BEFORE), line.date + dt.timedelta(days=SETTLE_AFTER))
    found = [t for t in planned if t.pk not in used and t.type == line.type and t.amount == line.amount
             and window[0] <= t.date <= window[1]]
    party = norm(line.party)
    return min(found, key=lambda t: (not (party and t.contact and norm(t.contact.name) == party), abs((t.date - line.date).days)),
               default=None)


def _label(t: Transaction) -> str:
    who = t.contact.name if t.contact else (t.reference or t.subgroup.name)
    return f'{t.date:%d/%m/%Y} · {who} · {t.reference or t.subgroup.name}'


# Applying

def commit_statement_service(*, user: User, account_id: int, lines: list[dict]) -> dict:
    account = _account_for(user, account_id)
    company = account.company
    companies = list_companies_service(user=user)
    counts = Counter()
    with transaction.atomic(), pghistory.context(user=user.pk, source='statement_import'):
        for line in lines:
            action, kind = line['action'], line['type']
            if action == 'skip':
                counts['skipped'] += 1
            elif action == 'create':
                subgroup = SubGroup.objects.filter(pk=line.get('subgroup_id')).exclude(group=Group.TRANSFER).first()
                if subgroup is None:
                    raise ValidationError(f'Escolha o subgrupo de "{line["description"]}" ({line["date"]:%d/%m})')
                Transaction.objects.create(
                    company=company, account=account, subgroup=subgroup, contact=_contact(line.get('party', '')),
                    date=line['date'], amount=line['amount'], type=kind, status=TransactionStatus.REALIZED,
                    reference=line['description'][:120],
                )
                StatementRule.objects.update_or_create(key=norm(line['description']), type=kind,
                                                       defaults={'subgroup': subgroup})
                counts['created'] += 1
            elif action == 'settle':
                tx = Transaction.objects.select_for_update().filter(
                    pk=line.get('match_id'), company=company, status=TransactionStatus.PLANNED,
                    type=kind, amount=line['amount'], transfer__isnull=True).first()
                if tx is None:
                    raise ValidationError(f'A parcela escolhida para "{line["description"]}" não serve '
                                          '(já baixada, outro valor ou outra empresa)')
                tx.status, tx.date, tx.account = TransactionStatus.REALIZED, line['date'], account
                tx.save(update_fields=['status', 'date', 'account', 'updated_at'])
                counts['settled'] += 1
            elif action == 'transfer':
                other = companies.exclude(pk=company.pk).filter(pk=line.get('company_id')).first()
                if other is None:
                    raise ValidationError(f'Escolha a outra empresa de "{line["description"]}"')
                inflow = kind == TransactionType.INFLOW
                create_transfer_service(
                    user=user, from_company_id=other.pk if inflow else company.pk,
                    to_company_id=company.pk if inflow else other.pk, date=line['date'], amount=line['amount'],
                    status=TransactionStatus.REALIZED, from_account_id=None if inflow else account.pk,
                    to_account_id=account.pk if inflow else None, notes=line['description'],
                )
                counts['transfers'] += 1
            else:
                raise ValidationError('Invalid action')
    return {'created': counts['created'], 'settled': counts['settled'], 'transfers': counts['transfers'],
            'skipped': counts['skipped']}


def _contact(party: str) -> Contact | None:
    if not party.strip():
        return None
    return Contact.objects.filter(name__iexact=party.strip()).order_by('pk').first() \
        or Contact.objects.create(name=party.strip()[:160])
