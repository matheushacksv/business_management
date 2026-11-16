from ninja import Query, Router
from ninja.pagination import PageNumberPagination, paginate

from api.schemas.sales_dto import (
    CreateSale,
    GenerateReceivables,
    NamedCreate,
    PatchSale,
    ProductOut,
    ProductPatch,
    SaleFilters,
    SaleOut,
    SalespersonCreate,
    SalespersonOut,
    SalespersonPatch,
    SalesReportOut,
    SalesReportParams,
)
from api.schemas.transactions_dto import TransactionOut
from apps.sales import selectors, services
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
    for field in ('name', 'active'):  # only user_id may be nulled (unlink login)
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


# Report

@router.get('/reports/sales', response=SalesReportOut)
@require_permission('reports', VIEW)
def sales_report_endpoint(request, params: Query[SalesReportParams], filters: Query[SaleFilters]):
    check_permission(request.user, 'sales', VIEW)
    return selectors.sales_report_selector(user=request.user, **params.dict(), **filters.dict())
