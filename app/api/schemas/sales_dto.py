import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import ModelSchema, Schema
from pydantic import Field, model_validator

from apps.sales.models import CommissionDue, CommissionKind, Product, Sale, Salesperson, SaleStatus


class NamedCreate(Schema):
    name: str = Field(min_length=1)


class ProductPatch(Schema):
    name: str | None = Field(None, min_length=1)
    active: bool | None = None


class SalespersonCreate(NamedCreate):
    user_id: int | None = None
    monthly_salary: Decimal = Field(Decimal('0'), ge=0, max_digits=14, decimal_places=2)


class SalespersonPatch(ProductPatch):
    user_id: int | None = None
    monthly_salary: Decimal | None = Field(None, ge=0, max_digits=14, decimal_places=2)


class ProductOut(ModelSchema):
    class Meta:
        model = Product
        fields = ['id', 'name', 'active']


class SalespersonOut(ModelSchema):
    user_id: int | None

    class Meta:
        model = Salesperson
        fields = ['id', 'name', 'active', 'monthly_salary']


class CreateSale(Schema):
    company_id: int
    date: dt.date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    contact_id: int | None = None
    product_id: int | None = None
    salesperson_id: int | None = None
    delivery_responsible_id: int | None = None
    payment_method: str = ''
    payment_terms: str = ''
    installments_count: int | None = Field(None, ge=1)
    status: SaleStatus = SaleStatus.ACTIVE
    notes: str = ''


class PatchSale(Schema):
    date: dt.date | None = None
    amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    contact_id: int | None = None
    product_id: int | None = None
    salesperson_id: int | None = None
    delivery_responsible_id: int | None = None
    payment_method: str | None = None
    payment_terms: str | None = None
    installments_count: int | None = Field(None, ge=1)
    status: SaleStatus | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def reject_null_on_required(self):
        for field in ('date', 'amount', 'payment_method', 'payment_terms', 'status', 'notes'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null')
        return self


class SaleOut(ModelSchema):
    company_id: int
    contact_id: int | None
    contact_name: str | None = Field(None, alias='contact.name')
    product_id: int | None
    product_name: str | None = Field(None, alias='product.name')
    salesperson_id: int | None
    salesperson_name: str | None = Field(None, alias='salesperson.name')
    delivery_responsible_id: int | None
    received_amount: Decimal   # realized receivables
    scheduled_amount: Decimal  # planned receivables
    pending_amount: Decimal    # sale amount - received

    class Meta:
        model = Sale
        fields = ['id', 'date', 'amount', 'payment_method', 'payment_terms', 'installments_count',
                  'status', 'notes', 'created_at', 'updated_at']

    @staticmethod
    def resolve_pending_amount(obj: Sale) -> Decimal:
        return obj.amount - obj.received_amount  # type:ignore


class SaleFilters(Schema):
    company_id: list[int] | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    status: list[SaleStatus] | None = None
    product_id: list[int] | None = None
    salesperson_id: list[int] | None = None
    delivery_responsible_id: list[int] | None = None
    contact_id: list[int] | None = None
    search: str | None = None
    ordering: Literal['date', '-date', 'amount', '-amount', 'created_at', '-created_at'] | None = None


class GenerateReceivables(Schema):
    subgroup_id: int
    first_date: dt.date
    installments: int = Field(ge=1, le=120)
    down_payment: Decimal = Field(Decimal('0'), ge=0, max_digits=14, decimal_places=2)
    down_payment_date: dt.date | None = None
    account_id: int | None = None


class SalesReportParams(Schema):
    start: dt.date
    end: dt.date


class SalesReportPeriod(Schema):
    period: dt.date
    sold: Decimal
    sales_count: int
    received: Decimal


class SalesReportOut(Schema):
    start: dt.date
    end: dt.date
    total_sold: Decimal
    total_received: Decimal
    sales_count: int
    periods: list[SalesReportPeriod]


class CreateCommission(Schema):
    salesperson_id: int
    kind: CommissionKind
    percent: Decimal | None = Field(None, gt=0, le=100, max_digits=5, decimal_places=2)
    fixed_amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    description: str = ''


class PatchCommission(Schema):
    salesperson_id: int | None = None
    kind: CommissionKind | None = None
    percent: Decimal | None = Field(None, gt=0, le=100, max_digits=5, decimal_places=2)
    fixed_amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)
    description: str | None = None

    @model_validator(mode='after')
    def reject_null_on_required(self):
        for field in ('salesperson_id', 'kind', 'description'):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f'{field} cannot be null')
        return self


class CommissionFilters(Schema):
    month: dt.date | None = None  # month the commission is due (sales of the previous month)
    salesperson_id: list[int] | None = None
    company_id: list[int] | None = None
    status: Literal['pending', 'paid'] | None = None


class PayCommissions(Schema):
    ids: list[int] = Field(min_length=1, max_length=1000)
    date: dt.date
    subgroup_id: int


class CommissionOut(Schema):
    id: int
    sale_id: int
    sale_date: dt.date = Field(alias='sale.date')
    sale_amount: Decimal = Field(alias='sale.amount')
    contact_name: str | None = Field(None, alias='sale.contact.name')
    company_id: int = Field(alias='sale.company_id')
    company_name: str = Field(alias='sale.company.name')
    tax_rate: Decimal  # of the sale's month
    salesperson_id: int
    salesperson_name: str = Field(alias='salesperson.name')
    kind: CommissionKind
    percent: Decimal | None
    fixed_amount: Decimal | None
    description: str
    amount: Decimal
    payment_id: int | None
    paid_on: dt.date | None = Field(None, alias='payment.date')
    first_payment: dt.date | None = None  # customer's first payment: releases the commission

    @staticmethod
    def resolve_amount(obj) -> Decimal:
        from apps.sales.services import commission_amount
        return commission_amount(obj)

    @staticmethod
    def resolve_tax_rate(obj) -> Decimal:
        from apps.sales.services import tax_rate_for
        return tax_rate_for(obj)


class CreateAdjustment(Schema):
    salesperson_id: int
    month: dt.date
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(max_digits=14, decimal_places=2)


class AdjustmentOut(Schema):
    id: int
    salesperson_id: int
    month: dt.date
    description: str
    amount: Decimal
    payment_id: int | None
    paid_on: dt.date | None = Field(None, alias='payment.date')


class PayAdjustments(Schema):
    salesperson_id: int
    month: dt.date
    date: dt.date
    company_id: int
    subgroup_id: int


class StatementParams(Schema):
    salesperson_id: int
    month: dt.date


class StatementOut(Schema):
    salesperson: SalespersonOut
    month: dt.date
    sales_month: dt.date
    salary: Decimal
    salary_payment_id: int | None
    salary_paid_on: dt.date | None
    adjustments: list[AdjustmentOut]
    commissions: list[CommissionOut]


class PaySalary(Schema):
    salesperson_id: int
    month: dt.date
    date: dt.date
    company_id: int
    subgroup_id: int
    amount: Decimal | None = Field(None, gt=0, max_digits=14, decimal_places=2)


class ShareStatement(Schema):
    salesperson_id: int
    month: dt.date


class StatementShareOut(Schema):
    token: str
    password: str
    expires_at: dt.datetime


class StatementPassword(Schema):
    password: str = Field(min_length=1, max_length=64)


class SalesConfigIO(Schema):
    commission_due: CommissionDue


class MonthTaxOut(Schema):
    company_id: int
    company_name: str
    default_rate: Decimal
    rate: Decimal | None  # None = default


class MonthTaxParams(Schema):
    month: dt.date


class SetMonthTax(Schema):
    company_id: int
    month: dt.date
    rate: Decimal | None = Field(None, ge=0, le=100, max_digits=5, decimal_places=2)
