"""Link imported installments (transactions) to their sales.

The spreadsheet has no link between "Vendas" and "Lançamentos", so imported sales show
nothing received. For each sale, candidates are the operating-revenue inflows of the same
customer (same name; else look-alike names, after every exact name took its own) from 20 days before
the sale up to 20 days before that customer's next sale. They are linked only when their
total matches the sale amount (R$ 1 tolerance): the amount is the proof, the installment
count may differ (split down payments, renegotiated dates).

When a customer has overlapping contracts (e.g. advisory + CRM), the window mixes both:
then the installments are split by their "k/N" series (reference column) and a series, or
a down payment series + an installment series, whose total matches the sale is linked.
"""

import datetime as dt
import re
from itertools import combinations
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.finance.contact_merge import similarity
from apps.finance.importer import _contact_key
from apps.finance.models import Group, Transaction, TransactionType
from apps.sales.models import Sale

TOLERANCE = Decimal('1.00')
WINDOW = dt.timedelta(days=20)
SERIES_RE = re.compile(r'(\d+)\s*/\s*(\d+)')


def _series(found: list[Transaction]) -> list[list[Transaction]]:
    """Group installments by "k/N" denominator; the rest go one by one."""
    by_total: dict[str, list[Transaction]] = defaultdict(list)
    singles = []
    for t in found:
        match = SERIES_RE.search(t.reference or '')
        (by_total[match.group(2)] if match else singles).append(t)
    return list(by_total.values()) + [[t] for t in singles]


def _matching(found: list[Transaction], amount: Decimal) -> list[Transaction] | None:
    ok = lambda txs: abs(sum((t.amount for t in txs), Decimal('0')) - amount) <= TOLERANCE
    if found and ok(found):
        return found
    series = _series(found)
    for size in (1, 2):  # one series, or down payment series + installment series
        for combo in combinations(series, size):
            txs = [t for group in combo for t in group]
            if ok(txs):
                return txs
    return None


@dataclass
class LinkResult:
    linked_sales: int = 0
    linked_transactions: int = 0
    already_linked: int = 0
    not_matching: list[tuple[Sale, int, Decimal]] = field(default_factory=list)  # sale, candidates, total


def link_receivables() -> LinkResult:
    """Run inside the caller's transaction (dry-run = rollback)."""
    result = LinkResult()
    revenue = (Transaction.objects.filter(type=TransactionType.INFLOW, subgroup__group=Group.OPERATING_REVENUE,
                                          sale__isnull=True, transfer__isnull=True, contact__isnull=False)
               .select_related('contact').order_by('date', 'id'))
    by_name = defaultdict(list)
    for t in revenue:
        by_name[t.contact.name].append(t)

    sales = list(Sale.objects.filter(contact__isnull=False).select_related('contact').order_by('date', 'id'))

    def names_for(sale_name: str) -> tuple[bool, tuple[str, ...]]:
        exact = sorted(n for n in by_name if _contact_key(n) == _contact_key(sale_name))
        if exact:
            return True, tuple(exact)
        # Look-alikes, best first; only installments left unused by the exact names are taken
        scored = sorted(((similarity(sale_name, n), n) for n in by_name), key=lambda p: (-(p[0] or 0), p[1]))
        return False, tuple(n for score, n in scored if score is not None)

    groups = defaultdict(list)
    for sale in sales:
        groups[names_for(sale.contact.name)].append(sale)

    linked_sale_ids = set(Transaction.objects.filter(sale__isnull=False).values_list('sale_id', flat=True))
    used: set[int] = set()
    for (_exact, names), group in sorted(groups.items(), key=lambda g: not g[0][0]):  # exact names first
        candidates = sorted((t for n in names for t in by_name[n]), key=lambda t: (t.date, t.id))
        for i, sale in enumerate(group):
            if sale.pk in linked_sale_ids:
                result.already_linked += 1
                continue
            end = group[i + 1].date - WINDOW if i + 1 < len(group) else dt.date.max
            available = [t for t in candidates if t.date >= sale.date - WINDOW and t.pk not in used]
            found = [t for t in available if t.date < end]
            # Window first; then series anywhere after the sale (overlapping contracts)
            linked = _matching(found, sale.amount) or _matching(available, sale.amount)
            if linked:
                Transaction.objects.filter(pk__in=[t.pk for t in linked]).update(sale=sale)
                used.update(t.pk for t in linked)
                result.linked_sales += 1
                result.linked_transactions += len(linked)
            else:
                result.not_matching.append((sale, len(found), sum((t.amount for t in found), Decimal('0'))))
    return result


class _Rollback(Exception):
    pass


def run_link(*, commit: bool) -> LinkResult:
    try:
        with transaction.atomic():
            result = link_receivables()
            if not commit:
                raise _Rollback(result)
    except _Rollback as rollback:
        result = rollback.args[0]
    return result
