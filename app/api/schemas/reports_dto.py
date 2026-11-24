import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import Schema
from pydantic import Field


class DREParams(Schema):
    year: int


class DRELine(Schema):
    key: str  # 'group:<group>', 'subgroup:<id>' or a result key
    label: str
    kind: Literal['info', 'group', 'subgroup', 'result']
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


class DRETableParams(Schema):
    view: Literal['monthly', 'years', 'month'] = 'monthly'
    year: int
    month: int | None = Field(None, ge=1, le=12)  # required by the "month" view
    percent: bool = False  # export only: share of revenue instead of R$


class DRETableColumn(Schema):
    label: str
    kind: Literal['value', 'delta', 'delta_percent']


class DRETableLine(Schema):
    key: str
    label: str
    kind: Literal['info', 'group', 'subgroup', 'result']
    better: Literal['up', 'down'] | None  # good direction for the variation colors
    values: list[Decimal | None]  # one per column
    percents: list[Decimal | None]  # share of operating revenue; None on variation columns


class DRETableOut(Schema):
    title: str
    columns: list[DRETableColumn]
    lines: list[DRETableLine]


class DelinquencyMonth(Schema):
    month: int | None  # None = year total
    due: Decimal
    overdue: Decimal
    count: int
    rate: Decimal | None  # overdue / due


class DelinquencyOut(Schema):
    months: list[DelinquencyMonth]
    total: DelinquencyMonth


class AnalysisParams(Schema):
    month: dt.date  # reference month (any day)
    group: list[str] | None = None
    subgroup_id: list[int] | None = None
    company_id: list[int] | None = None
    status: list[Literal['planned', 'realized']] | None = None


class AnalysisCompany(Schema):
    id: int
    name: str
    months: list[Decimal]  # same 12 months as AnalysisOut.months


class AnalysisOut(Schema):
    month: dt.date
    kind: Literal['revenue', 'cost', 'mixed']  # cost: going up is worse
    months: list[dt.date]   # 12 months up to the reference
    current: list[Decimal]  # totals of those months
    previous: list[Decimal]  # the 12 months before (same months, previous year)
    companies: list[AnalysisCompany]


class SavedReportIn(Schema):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['dre', 'cash_flow', 'analysis', 'transactions', 'commissions', 'investments']
    params: dict = {}


class SavedReportOut(Schema):
    id: int
    name: str
    kind: str
    params: dict
