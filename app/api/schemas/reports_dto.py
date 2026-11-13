import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import Schema


class DREParams(Schema):
    year: int


class DRELine(Schema):
    key: str  # 'group:<group>', 'subgroup:<id>' or a result key
    label: str
    kind: Literal['group', 'subgroup', 'result']
    months: list[Decimal]  # 12 values, January first
    total: Decimal
    percents: list[Decimal | None]  # over operating revenue; null when revenue is 0
    total_percent: Decimal | None


class DREOut(Schema):
    year: int
    lines: list[DRELine]


class CashFlowParams(Schema):
    start: dt.date
    end: dt.date
    granularity: Literal['month', 'day'] = 'month'


class CashFlowPeriod(Schema):
    period: dt.date  # first day of the month, or the day
    opening: Decimal
    inflow: Decimal
    outflow: Decimal
    closing: Decimal


class CashFlowOut(Schema):
    start: dt.date
    end: dt.date
    granularity: Literal['month', 'day']
    opening: Decimal
    closing: Decimal
    periods: list[CashFlowPeriod]
