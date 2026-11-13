import datetime as dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Count, DecimalField, Sum, Value
from django.db.models.functions import Coalesce, TruncMonth

from apps.finance.models import Transaction, TransactionStatus, TransactionType
from apps.finance.selectors import _periods
from apps.sales.services import filter_sales
from apps.users.models import User

ZERO = Decimal('0')
MONEY = DecimalField(max_digits=16, decimal_places=2)


def sales_report_selector(*, user: User, start: dt.date, end: dt.date, **filters) -> dict:
    """Sold (by sale date) vs received (by payment date of the sale's receivables), per month."""
    if start > end:
        raise ValidationError('start must be before end')
    filters.pop('date_from', None)
    filters.pop('date_to', None)
    filters.pop('ordering', None)
    sales = filter_sales(user=user, **filters).order_by()  # no receivables join: sums stay exact

    sold = {
        row['period']: row for row in sales.filter(date__range=(start, end))
        .values(period=TruncMonth('date'))
        .annotate(sold=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY), count=Count('id'))
    }
    received = {
        row['period']: row['received'] for row in Transaction.objects.filter(
            sale__in=sales.values('pk'), status=TransactionStatus.REALIZED,
            type=TransactionType.INFLOW, date__range=(start, end),
        ).values(period=TruncMonth('date'))
        .annotate(received=Coalesce(Sum('amount'), Value(ZERO), output_field=MONEY))
    }

    periods = [
        {
            'period': p,
            'sold': sold.get(p, {}).get('sold', ZERO),
            'sales_count': sold.get(p, {}).get('count', 0),
            'received': received.get(p, ZERO),
        }
        for p in _periods(start, end, 'month')
    ]
    return {
        'start': start, 'end': end, 'periods': periods,
        'total_sold': sum((p['sold'] for p in periods), ZERO),
        'total_received': sum((p['received'] for p in periods), ZERO),
        'sales_count': sum(p['sales_count'] for p in periods),
    }
