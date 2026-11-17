"""Find likely duplicated contacts (to be reviewed by people) and apply the approved merges.

Flow: `suggest_contact_merges out.xlsx` -> the client marks "S" on the real duplicates ->
`merge_contacts out.xlsx --commit`. Contacts are referenced by exact name in the file.
"""

import difflib
import math
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Count, Q
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from apps.finance.models import Contact, Group, TransactionType
from apps.finance.services import merge_contacts_service

HEADER = ['Manter', 'Mesclar (some)', 'Semelhança', 'Lançamentos (manter)', 'Vendas (manter)',
          'Lançamentos (mesclar)', 'Vendas (mesclar)', 'Mesclar? (S/N)']
DECISION_COL = HEADER.index('Mesclar? (S/N)')


def _words(name: str) -> list[str]:
    plain = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode().casefold()
    return ''.join(c if c.isalnum() else ' ' for c in plain).split()


def _close(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 4 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.75)


def _contract_numbers(words: list[str]) -> set[str]:
    return {w.lstrip('0') for w in words if w.isdigit() and len(w) <= 2}


def similarity(a: str, b: str) -> float | None:
    """0..1 when the names look like the same contact, else None.

    "Luni Digital - 2" x "Luni Digital" are different contracts on purpose (the spreadsheet
    numbers them): never suggested.
    """
    wa, wb = _words(a), _words(b)
    if _contract_numbers(wa) != _contract_numbers(wb):
        return None
    ca, cb = ''.join(wa), ''.join(wb)
    if not ca or not cb:
        return None
    ratio = difflib.SequenceMatcher(None, ca, cb).ratio()
    if ca == cb or ratio >= 0.85:
        return ratio
    if min(len(ca), len(cb)) >= 6 and (ca.startswith(cb) or cb.startswith(ca)):
        return ratio  # "Splash Piscinas" x "Splash Piscinas Itajuba"
    long_a, long_b = [w for w in wa if len(w) >= 3], [w for w in wb if len(w) >= 3]
    matched = sum(1 for w in long_a if any(_close(w, x) for x in long_b))
    if matched >= 2 and matched >= math.ceil(0.6 * min(len(long_a), len(long_b))):
        return ratio  # "ALMD Advogados (Sammuel)" x "ALDM Advogados"
    return None


def suggest_pairs() -> list[tuple]:
    # Customers only (sales or revenue): expense "contacts" (purchases, payroll) are noise here
    revenue = Q(transactions__type=TransactionType.INFLOW, transactions__subgroup__group=Group.OPERATING_REVENUE)
    contacts = list(Contact.objects.annotate(
        txs=Count('transactions', distinct=True), sales_count=Count('sales', distinct=True),
        revenue_count=Count('transactions', filter=revenue, distinct=True),
    ).filter(Q(sales_count__gt=0) | Q(revenue_count__gt=0)))
    # ponytail: blocking by 3-letter word prefixes keeps it far from 800² comparisons; fine up to ~10k contacts
    blocks = defaultdict(set)
    for i, c in enumerate(contacts):
        for w in _words(c.name):
            if len(w) >= 3:
                blocks[w[:3]].add(i)
    seen, pairs = set(), []
    for members in blocks.values():
        members = sorted(members)
        for x, i in enumerate(members):
            for j in members[x + 1:]:
                if (i, j) in seen:
                    continue
                seen.add((i, j))
                a, b = contacts[i], contacts[j]
                if not (a.sales_count or b.sales_count):
                    continue  # nothing to fix on the sales side
                score = similarity(a.name, b.name)
                if score is None or score < 0.6:
                    continue
                keep, drop = (a, b) if (a.txs + a.sales_count, len(a.name)) >= (b.txs + b.sales_count, len(b.name)) else (b, a)
                pairs.append((keep, drop, score))
    # Sale on one side and transactions on the other first: the merges that fix sales x installments
    useful = lambda p: (p[0].sales_count > 0) != (p[1].sales_count > 0) and (p[0].txs > 0 or p[1].txs > 0)
    pairs.sort(key=lambda p: (not useful(p), -p[2], p[0].name))
    return pairs


def write_suggestions(path) -> int:
    pairs = suggest_pairs()
    wb = Workbook()
    ws = wb.active
    ws.title = 'Duplicados'
    ws.append(HEADER)
    for keep, drop, score in pairs:
        ws.append([keep.name, drop.name, round(score, 2), keep.txs, keep.sales_count, drop.txs, drop.sales_count, ''])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, min_col=DECISION_COL + 1, max_col=DECISION_COL + 1):
        row[0].fill = PatternFill('solid', fgColor='FFF2CC')
    for col, width in zip('ABCDEFGH', (45, 45, 12, 14, 12, 14, 12, 16)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = 'A2'
    wb.save(path)
    return len(pairs)


@dataclass
class MergeResult:
    merged: list[tuple[str, str]] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)


def apply_merges(path, *, user) -> MergeResult:
    """Run inside the caller's transaction (dry-run = rollback). Columns A/B swapped by the
    reviewer are fine: A is always kept."""
    result = MergeResult()
    merged_into: dict[str, str] = {}  # chains: B -> A on one row, C -> B on the next

    def resolve(name: str) -> str:
        while name in merged_into:
            name = merged_into[name]
        return name

    ws = load_workbook(path, read_only=True).active
    for row_number, values in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        values = list(values) + [None] * len(HEADER)
        if str(values[DECISION_COL] or '').strip().upper() not in ('S', 'SIM'):
            continue
        keep_name, drop_name = resolve(str(values[0] or '').strip()), resolve(str(values[1] or '').strip())
        keep = list(Contact.objects.filter(name=keep_name)[:2])
        drop = list(Contact.objects.filter(name=drop_name)[:2])
        problem = next((f'{label} "{name}": {"não encontrado" if not found else "nome repetido"}'
                        for label, name, found in (('manter', keep_name, keep), ('mesclar', drop_name, drop))
                        if len(found) != 1), None)
        if problem:
            result.errors.append((row_number, problem))
            continue
        if keep[0].pk == drop[0].pk:
            continue
        merge_contacts_service(user=user, target_id=keep[0].pk, source_ids=[drop[0].pk])
        merged_into[drop_name] = keep_name
        result.merged.append((keep_name, drop_name))
    return result


class _Rollback(Exception):
    pass


def run_merges(path, *, user, commit: bool) -> MergeResult:
    try:
        with transaction.atomic():
            result = apply_merges(path, user=user)
            if not commit:
                raise _Rollback(result)
    except _Rollback as rollback:
        result = rollback.args[0]
    return result
