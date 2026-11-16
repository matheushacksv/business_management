"""Read-only reports built on top of list_transactions_service.

Every report accepts the same filters as the transaction list, so access control
(user -> companies) and filtering live in one place.
"""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Case, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, ExtractMonth, TruncMonth

from apps.companies.services import list_companies_service
from apps.finance.models import NATURAL_TYPE, Group, SubGroup, TransactionType
from apps.finance.services import list_transactions_service
from apps.users.models import User

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=16, decimal_places=2)
INFLOW_GROUPS = [g for g, t in NATURAL_TYPE.items() if t == TransactionType.INFLOW]

# Natural type adds, opposite type (reversal) subtracts — inside its own group
SIGNED_AMOUNT = Case(
    When(subgroup__group__in=INFLOW_GROUPS, type=TransactionType.INFLOW, then=F('amount')),
    When(~Q(subgroup__group__in=INFLOW_GROUPS), type=TransactionType.OUTFLOW, then=F('amount')),
    default=-F('amount'),
    output_field=MONEY,
)


def _sum(**filter_kwargs):
    q = Q(**filter_kwargs) if filter_kwargs else None
    return Coalesce(Sum('amount', filter=q), Value(ZERO), output_field=MONEY)


def _percent(value: Decimal, base: Decimal) -> Decimal | None:
    return (value / base).quantize(Decimal('0.0001')) if base else None


# DRE

DRE_LAYOUT = [
    ('info', 'gross_sales'),
    ('group', Group.OPERATING_REVENUE),
    ('group', Group.VARIABLE_COSTS),
    ('result', 'contribution_margin'),
    ('group', Group.FIXED_COSTS),
    ('result', 'profit_margin'),
    ('group', Group.NON_OPERATING_REVENUE),
    ('group', Group.NON_OPERATING_EXPENSES),
    ('result', 'net_result'),
]

RESULT_LABELS = {
    'gross_sales': 'Faturamento Bruto',
    'contribution_margin': 'Margem de Contribuição',
    'profit_margin': 'Margem de Lucro',
    'net_result': 'Resultado Líquido',
}


def _gross_sales(user: User, year: int, company_id=None) -> list[Decimal]:
    # Spreadsheet "Faturamento Bruto": sales by month (informative; % base stays operating revenue).
    # Only the company filter applies: the other filters are about transactions.
    from apps.sales.models import Sale  # local: sales depends on finance

    qs = Sale.objects.filter(company__in=list_companies_service(user=user), date__year=year)
    if company_id:
        qs = qs.filter(company_id__in=company_id)
    months = [ZERO] * 12
    for row in qs.order_by().values(month=ExtractMonth('date')).annotate(total=Sum('amount')):
        months[row['month'] - 1] = row['total']
    return months


def dre_selector(*, user: User, year: int, **filters) -> dict:
    filters.pop('date_from', None)
    filters.pop('date_to', None)
    filters.pop('ordering', None)
    rows = (
        list_transactions_service(user=user, **filters)
        .filter(date__year=year)
        .order_by()  # no ORDER BY inside GROUP BY
        .values('subgroup_id', month=ExtractMonth('date'))
        .annotate(total=Sum(SIGNED_AMOUNT))
    )
    by_subgroup: dict[int, list[Decimal]] = {}
    for row in rows:
        by_subgroup.setdefault(row['subgroup_id'], [ZERO] * 12)[row['month'] - 1] = row['total']

    
    subgroups_by_group: dict[str, list[dict]] = {g: [] for g in Group.values}
    for sg in SubGroup.objects.order_by('name'):
        if filters.get('subgroup_id') and sg.pk not in filters['subgroup_id']:
            continue
        months = by_subgroup.get(sg.pk, [ZERO] * 12)
        subgroups_by_group[sg.group].append(
            {'key': f'subgroup:{sg.pk}', 'label': sg.name, 'kind': 'subgroup', 'months': months}
        )

    group_months = {
        g: [sum((s['months'][m] for s in subs), ZERO) for m in range(12)]
        for g, subs in subgroups_by_group.items()
    }

    def combine(fn):
        return [fn(m) for m in range(12)]

    contribution = combine(lambda m: group_months[Group.OPERATING_REVENUE][m] - group_months[Group.VARIABLE_COSTS][m])
    profit = combine(lambda m: contribution[m] - group_months[Group.FIXED_COSTS][m])
    net = combine(
        lambda m: profit[m]
        + group_months[Group.NON_OPERATING_REVENUE][m]
        - group_months[Group.NON_OPERATING_EXPENSES][m]
    )
    results = {
        'contribution_margin': contribution, 'profit_margin': profit, 'net_result': net,
        'gross_sales': _gross_sales(user, year, filters.get('company_id')),
    }

    lines = []
    for kind, key in DRE_LAYOUT:
        if kind == 'group':
            lines.append({'key': f'group:{key}', 'label': Group(key).label, 'kind': 'group',
                          'months': group_months[key]})
            lines.extend(subgroups_by_group[key])
        else:
            lines.append({'key': key, 'label': RESULT_LABELS[key], 'kind': kind, 'months': results[key]})

    
    revenue = group_months[Group.OPERATING_REVENUE]
    revenue_total = sum(revenue, ZERO)
    for line in lines:
        line['total'] = sum(line['months'], ZERO)
        informative = line['kind'] == 'info'
        line['percents'] = [None if informative else _percent(v, revenue[m]) for m, v in enumerate(line['months'])]
        line['total_percent'] = None if informative else _percent(line['total'], revenue_total)

    return {'year': year, 'lines': lines}


# DRE views (same table shape for the screen and the Excel export)

MONTH_LABELS = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']
COST_GROUPS = {f'group:{g}' for g in (Group.VARIABLE_COSTS, Group.FIXED_COSTS, Group.NON_OPERATING_EXPENSES)}


def _delta(current: Decimal, previous: Decimal) -> tuple[Decimal, Decimal | None]:
    diff = current - previous
    return diff, (diff / abs(previous)).quantize(Decimal('0.0001')) if previous else None


def _better(line: dict, group_key: str) -> str | None:
    """Which direction is good news: costs going down, everything else going up."""
    if line['kind'] == 'info':
        return None
    if line['kind'] == 'result':  # margins and net result: always "higher is better"
        return 'up'
    return 'down' if (line['key'] if line['kind'] == 'group' else group_key) in COST_GROUPS else 'up'


def dre_table_selector(*, user: User, view: str, year: int, month: int | None = None, **filters) -> dict:
    """DRE as a generic table: columns + lines with one value per column.

    monthly: Jan..Dez + Total | years: year-1, year, variation, variation % |
    month: same month last year, previous month, month, % vs previous month, % vs last year.
    `percents` follow the values (share of operating revenue); None on variation columns.
    """
    current = dre_selector(user=user, year=year, **filters)
    if view == 'monthly':
        columns = [{'label': m, 'kind': 'value'} for m in MONTH_LABELS] + [{'label': 'Total', 'kind': 'value'}]
        pick = lambda line, _: (line['months'] + [line['total']], line['percents'] + [line['total_percent']])
        title = f'DRE {year}'
        previous = None
    else:
        previous = dre_selector(user=user, year=year - 1, **filters)
        if view == 'years':
            columns = [{'label': str(year - 1), 'kind': 'value'}, {'label': str(year), 'kind': 'value'},
                       {'label': 'Variação', 'kind': 'delta'}, {'label': 'Var %', 'kind': 'delta_percent'}]

            def pick(line, old):
                diff, pct = _delta(line['total'], old['total'])
                return ([old['total'], line['total'], diff, pct],
                        [old['total_percent'], line['total_percent'], None, None])
            title = f'DRE {year} × {year - 1}'
        elif view == 'month':
            if not month or not 1 <= month <= 12:
                raise ValidationError('month must be between 1 and 12')
            m = month - 1
            label = lambda mi, y: f'{MONTH_LABELS[mi]}/{y}'
            prev_label = label(11, year - 1) if m == 0 else label(m - 1, year)
            columns = [{'label': label(m, year - 1), 'kind': 'value'}, {'label': prev_label, 'kind': 'value'},
                       {'label': label(m, year), 'kind': 'value'},
                       {'label': 'vs mês ant.', 'kind': 'delta_percent'}, {'label': 'vs ano ant.', 'kind': 'delta_percent'}]

            def pick(line, old):
                # January's previous month is December of the year before
                prev_value, prev_pct = (old['months'][11], old['percents'][11]) if m == 0 \
                    else (line['months'][m - 1], line['percents'][m - 1])
                value = line['months'][m]
                return ([old['months'][m], prev_value, value, _delta(value, prev_value)[1], _delta(value, old['months'][m])[1]],
                        [old['percents'][m], prev_pct, line['percents'][m], None, None])
            title = f'DRE {label(m, year)}'
        else:
            raise ValidationError(f'Invalid view: {view}')

    old_lines = {line['key']: line for line in previous['lines']} if previous else {}
    lines, group_key = [], ''
    for line in current['lines']:
        if line['kind'] == 'group':
            group_key = line['key']
        old = old_lines.get(line['key'], {**line, 'months': [ZERO] * 12, 'total': ZERO,
                                          'percents': [None] * 12, 'total_percent': None})
        values, percents = pick(line, old)
        lines.append({'key': line['key'], 'label': line['label'], 'kind': line['kind'],
                      'better': _better(line, group_key), 'values': values, 'percents': percents})
    return {'title': title, 'columns': columns, 'lines': lines}


# Cash flow

MAX_DAILY_RANGE = 366


def _periods(start: date, end: date, granularity: str) -> list[date]:
    if granularity == 'day':
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    periods, current = [], start.replace(day=1)
    while current <= end:
        periods.append(current)
        days = calendar.monthrange(current.year, current.month)[1]
        current = current + timedelta(days=days)
    return periods


def cash_flow_selector(
    *, user: User, start: date, end: date, granularity: str = 'month', **filters
) -> dict:
    if start > end:
        raise ValidationError('start must be before end')
    if granularity == 'day' and (end - start).days >= MAX_DAILY_RANGE:
        raise ValidationError(f'Daily cash flow is limited to {MAX_DAILY_RANGE} days')
    filters.pop('date_from', None)
    filters.pop('date_to', None)
    filters.pop('ordering', None)

    # Cash flow uses the real direction of money (type), not the DRE group sign
    qs = list_transactions_service(user=user, **filters).order_by()

    # account/subgroup; per-account opening balances would need an Account.initial_balance
    companies = list_companies_service(user=user)
    if filters.get('company_id'):
        companies = companies.filter(pk__in=filters['company_id'])
    initial = companies.aggregate(total=Coalesce(Sum('initial_balance'), Value(ZERO), output_field=MONEY))['total']

    before = qs.filter(date__lt=start).aggregate(
        inflow=_sum(type=TransactionType.INFLOW), outflow=_sum(type=TransactionType.OUTFLOW)
    )
    balance = initial + before['inflow'] - before['outflow']

    period_expr = TruncMonth('date') if granularity == 'month' else F('date')
    rows = (
        qs.filter(date__range=(start, end))
        .values(period=period_expr)
        .annotate(inflow=_sum(type=TransactionType.INFLOW), outflow=_sum(type=TransactionType.OUTFLOW))
    )
    by_period = {row['period']: row for row in rows}

    opening_balance = balance
    periods = []
    for period in _periods(start, end, granularity):
        row = by_period.get(period, {'inflow': ZERO, 'outflow': ZERO})
        closing = balance + row['inflow'] - row['outflow']
        periods.append({
            'period': period, 'opening': balance,
            'inflow': row['inflow'], 'outflow': row['outflow'], 'closing': closing,
        })
        balance = closing

    return {
        'start': start, 'end': end, 'granularity': granularity,
        'opening': opening_balance, 'closing': balance, 'periods': periods,
    }
