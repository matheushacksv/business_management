from django.http import HttpResponse
from django.utils import timezone
from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.sales_dto import (
    AdjustmentOut,
    CreateAdjustment,
    PayAdjustments,
    CommissionFilters,
    CommissionOut,
    CreateCommission,
    PatchCommission,
    PayCommissions,
    PaySalary,
    ShareStatement,
    StatementPassword,
    StatementShareOut,
    StatementOut,
    StatementParams,
    CreateSale,
    GenerateReceivables,
    NamedCreate,
    PatchSale,
    PlanCreate,
    PlanOut,
    PlanPatch,
    ProductOut,
    ProductPatch,
    SaleFilters,
    SaleOut,
    SalespersonCreate,
    SalespersonOut,
    SalespersonPatch,
    SalesReportOut,
    SalesReportParams,
    SalesConfigIO,
    MonthTaxOut,
    MonthTaxParams,
    SetMonthTax,
)
from api.schemas.transactions_dto import TransactionOut
from apps.finance.exporter import XLSX_CONTENT_TYPE
from apps.sales import selectors, services
from apps.sales.models import SalesConfig
from apps.sales.exporter import commissions_xlsx, sales_report_xlsx
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, check_permission, require_permission

router = Router(tags=['Sales'])


# Products

@router.get('/product', response=list[ProductOut])
@require_permission('sales', VIEW)
def list_products_endpoint(request, active: bool | None = None):
    return services.list_products_service(active=active)


@router.post('/product', response={201: ProductOut})
@require_permission('sales', CREATE)
def create_product_endpoint(request, data: NamedCreate):
    return 201, services.create_product_service(name=data.name)


@router.patch('/product/{product_id}', response=ProductOut)
@require_permission('sales', CHANGE)
def update_product_endpoint(request, product_id: int, data: ProductPatch):
    return services.update_product_service(product_id=product_id, **data.dict(exclude_unset=True, exclude_none=True))


@router.delete('/product/{product_id}', response={204: None})
@require_permission('sales', DELETE)
def delete_product_endpoint(request, product_id: int):
    services.delete_product_service(product_id=product_id)
    return 204, None


# Plans (Pipedrive "plano"): the product NF-e items

@router.get('/plan', response=list[PlanOut])
@require_permission('sales', VIEW)
def list_plans_endpoint(request, active: bool | None = None):
    return services.list_plans_service(active=active)


@router.post('/plan', response={201: PlanOut})
@require_permission('sales', CREATE)
def create_plan_endpoint(request, data: PlanCreate):
    return 201, services.create_plan_service(**data.dict())


@router.patch('/plan/{plan_id}', response=PlanOut)
@require_permission('sales', CHANGE)
def update_plan_endpoint(request, plan_id: int, data: PlanPatch):
    return services.update_plan_service(plan_id=plan_id, **data.dict(exclude_unset=True, exclude_none=True))


@router.delete('/plan/{plan_id}', response={204: None})
@require_permission('sales', DELETE)
def delete_plan_endpoint(request, plan_id: int):
    services.delete_plan_service(plan_id=plan_id)
    return 204, None


# Salespeople

@router.get('/salesperson', response=list[SalespersonOut])
@require_permission('sales', VIEW)
def list_salespeople_endpoint(request, active: bool | None = None):
    return services.list_salespeople_service(active=active)


@router.post('/salesperson', response={201: SalespersonOut})
@require_permission('sales', CREATE)
def create_salesperson_endpoint(request, data: SalespersonCreate):
    return 201, services.create_salesperson_service(**data.dict())


@router.patch('/salesperson/{salesperson_id}', response=SalespersonOut)
@require_permission('sales', CHANGE)
def update_salesperson_endpoint(request, salesperson_id: int, data: SalespersonPatch):
    fields = data.dict(exclude_unset=True)
    for field in ('name', 'active', 'monthly_salary'):  # only user_id may be nulled (unlink login)
        if fields.get(field, ...) is None:
            fields.pop(field)
    return services.update_salesperson_service(salesperson_id=salesperson_id, **fields)


@router.delete('/salesperson/{salesperson_id}', response={204: None})
@require_permission('sales', DELETE)
def delete_salesperson_endpoint(request, salesperson_id: int):
    services.delete_salesperson_service(salesperson_id=salesperson_id)
    return 204, None


# Sales

@router.post('/sale', response={201: SaleOut})
@require_permission('sales', CREATE)
def create_sale_endpoint(request, data: CreateSale):
    return 201, services.create_sale_service(user=request.user, **data.dict())


@router.get('/sale', response=list[SaleOut])
@paginate(PageNumberPagination, page_size=50)
@require_permission('sales', VIEW)
def list_sales_endpoint(request, filters: Query[SaleFilters]):
    return services.list_sales_service(user=request.user, **filters.dict())


@router.get('/sale/{sale_id}', response=SaleOut)
@require_permission('sales', VIEW)
def get_sale_endpoint(request, sale_id: int):
    return services.get_sale_service(user=request.user, sale_id=sale_id)


@router.patch('/sale/{sale_id}', response=SaleOut)
@require_permission('sales', CHANGE)
def update_sale_endpoint(request, sale_id: int, data: PatchSale):
    return services.update_sale_service(user=request.user, sale_id=sale_id, **data.dict(exclude_unset=True))


@router.delete('/sale/{sale_id}', response={204: None})
@require_permission('sales', DELETE)
def delete_sale_endpoint(request, sale_id: int):
    services.delete_sale_service(user=request.user, sale_id=sale_id)
    return 204, None


@router.get('/sale/{sale_id}/receivables', response=list[TransactionOut])
@require_permission('sales', VIEW)
def list_receivables_endpoint(request, sale_id: int):
    check_permission(request.user, 'transactions', VIEW)
    sale = services.get_sale_service(user=request.user, sale_id=sale_id)
    return sale.receivables.select_related('company', 'subgroup', 'account', 'contact').order_by('date', 'id')


@router.post('/sale/{sale_id}/receivables', response={201: list[TransactionOut]})
@require_permission('sales', CHANGE)
def generate_receivables_endpoint(request, sale_id: int, data: GenerateReceivables):
    check_permission(request.user, 'transactions', CREATE)  # creates transactions too
    return 201, services.generate_receivables_service(user=request.user, sale_id=sale_id, **data.dict())


# Commissions

@router.get('/sale/{sale_id}/commissions', response=list[CommissionOut])
@require_permission('sales', VIEW)
def list_sale_commissions_endpoint(request, sale_id: int):
    return services.list_sale_commissions_service(user=request.user, sale_id=sale_id)


@router.post('/sale/{sale_id}/commissions', response={201: CommissionOut})
@require_permission('sales', CHANGE)
def create_commission_endpoint(request, sale_id: int, data: CreateCommission):
    return 201, services.create_commission_service(user=request.user, sale_id=sale_id, **data.dict())


@router.get('/commission', response=list[CommissionOut])
@require_permission('sales', VIEW)
def list_commissions_endpoint(request, filters: Query[CommissionFilters]):
    return services.list_commissions_service(user=request.user, **filters.dict())


@router.get('/commission/export')
@require_permission('sales', VIEW)
def export_commissions_endpoint(request, filters: Query[CommissionFilters]):
    response = HttpResponse(
        commissions_xlsx(services.list_commissions_service(user=request.user, **filters.dict())),
        content_type=XLSX_CONTENT_TYPE,
    )
    response['Content-Disposition'] = f'attachment; filename="comissoes-{timezone.localdate():%Y-%m-%d}.xlsx"'
    return response


@router.post('/commission/pay', response=list[TransactionOut])
@require_permission('sales', CHANGE)
def pay_commissions_endpoint(request, data: PayCommissions):
    check_permission(request.user, 'transactions', CREATE)  # creates the outflows
    return services.pay_commissions_service(user=request.user, **data.dict())


@router.get('/commission/statement', response=StatementOut)
@require_permission('sales', VIEW)
def commission_statement_endpoint(request, params: Query[StatementParams]):
    return services.salary_statement_service(user=request.user, **params.dict())


@router.post('/commission/statement/share', response=StatementShareOut)
@require_permission('sales', CHANGE)
def share_statement_endpoint(request, data: ShareStatement):
    share, password = services.share_statement_service(user=request.user, **data.dict())
    return {'token': share.token, 'password': password, 'expires_at': share.expires_at}


@router.post('/public/statement/{token}', auth=None, response=StatementOut)
def public_statement_endpoint(request, token: str, data: StatementPassword):
    return services.public_statement_service(token=token, password=data.password)


@router.post('/adjustment', response={201: AdjustmentOut})
@require_permission('sales', CHANGE)
def create_adjustment_endpoint(request, data: CreateAdjustment):
    return 201, services.create_adjustment_service(user=request.user, **data.dict())


@router.post('/adjustment/pay', response=list[TransactionOut])
@require_permission('sales', CHANGE)
def pay_adjustments_endpoint(request, data: PayAdjustments):
    check_permission(request.user, 'transactions', CREATE)  # creates the outflow/reversal
    return services.pay_adjustments_service(user=request.user, **data.dict())


@router.delete('/adjustment/{adjustment_id}', response={204: None})
@require_permission('sales', CHANGE)
def delete_adjustment_endpoint(request, adjustment_id: int):
    services.delete_adjustment_service(user=request.user, adjustment_id=adjustment_id)
    return 204, None


@router.post('/salary/pay', response=TransactionOut)
@require_permission('sales', CHANGE)
def pay_salary_endpoint(request, data: PaySalary):
    check_permission(request.user, 'transactions', CREATE)  # creates the outflow
    return services.pay_salary_service(user=request.user, **data.dict())


@router.get('/commission/tax', response=list[MonthTaxOut])
@require_permission('sales', VIEW)
def list_month_taxes_endpoint(request, params: Query[MonthTaxParams]):
    return services.list_month_taxes_service(user=request.user, month=params.month)


@router.put('/commission/tax', response={204: None})
@require_permission('sales', CHANGE)
def set_month_tax_endpoint(request, data: SetMonthTax):
    services.set_month_tax_service(user=request.user, **data.dict())
    return 204, None


@router.get('/commission/config', response=SalesConfigIO)
@require_permission('sales', VIEW)
def get_sales_config_endpoint(request):
    return SalesConfig.get()


@router.put('/commission/config', response=SalesConfigIO)
@require_permission('sales', CHANGE)
def update_sales_config_endpoint(request, data: SalesConfigIO):
    config = SalesConfig.get()
    config.commission_due = data.commission_due
    config.save()
    return config


@router.patch('/commission/{commission_id}', response=CommissionOut)
@require_permission('sales', CHANGE)
def update_commission_endpoint(request, commission_id: int, data: PatchCommission):
    return services.update_commission_service(
        user=request.user, commission_id=commission_id, **data.dict(exclude_unset=True)
    )


@router.delete('/commission/{commission_id}', response={204: None})
@require_permission('sales', CHANGE)
def delete_commission_endpoint(request, commission_id: int):
    services.delete_commission_service(user=request.user, commission_id=commission_id)
    return 204, None


# Report

@router.get('/reports/sales', response=SalesReportOut)
@require_permission('reports', VIEW)
def sales_report_endpoint(request, params: Query[SalesReportParams], filters: Query[SaleFilters]):
    check_permission(request.user, 'sales', VIEW)
    return selectors.sales_report_selector(user=request.user, **params.dict(), **filters.dict())


@router.get('/reports/sales/export')
@require_permission('reports', VIEW)
def export_sales_report_endpoint(request, params: Query[SalesReportParams], filters: Query[SaleFilters]):
    check_permission(request.user, 'sales', VIEW)
    report = selectors.sales_report_selector(user=request.user, **params.dict(), **filters.dict())
    response = HttpResponse(sales_report_xlsx(report), content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = f'attachment; filename="vendas-recebido-{params.start:%Y-%m}-{params.end:%Y-%m}.xlsx"'
    return response
