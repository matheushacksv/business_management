from django.http import HttpResponse
from django.utils import timezone
from ninja import Query, Router

from api.schemas.investments_dto import (
    CreateInvestment, CreateMovement, InvestmentFilters, InvestmentOut, MovementOut, PatchInvestment,
)
from apps.finance.exporter import XLSX_CONTENT_TYPE
from apps.investments import services
from apps.investments.exporter import investments_xlsx
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Investments'])


@router.get('/investment', response=list[InvestmentOut])
@require_permission('investments', VIEW)
def list_investments_endpoint(request, filters: Query[InvestmentFilters]):
    return services.list_investments_service(user=request.user, **filters.dict())


@router.get('/investment/export')
@require_permission('investments', VIEW)
def export_investments_endpoint(request, filters: Query[InvestmentFilters]):
    response = HttpResponse(investments_xlsx(services.list_investments_service(user=request.user, **filters.dict())),
                            content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = f'attachment; filename="investimentos-{timezone.localdate():%Y-%m-%d}.xlsx"'
    return response


@router.post('/investment', response={201: InvestmentOut})
@require_permission('investments', CREATE)
def create_investment_endpoint(request, data: CreateInvestment):
    return 201, services.create_investment_service(user=request.user, **data.dict())


@router.get('/investment/{investment_id}', response=InvestmentOut)
@require_permission('investments', VIEW)
def get_investment_endpoint(request, investment_id: int):
    return services.get_investment_service(user=request.user, investment_id=investment_id)


@router.patch('/investment/{investment_id}', response=InvestmentOut)
@require_permission('investments', CHANGE)
def update_investment_endpoint(request, investment_id: int, data: PatchInvestment):
    return services.update_investment_service(user=request.user, investment_id=investment_id,
                                              **data.dict(exclude_unset=True, exclude_none=True))


@router.delete('/investment/{investment_id}', response={204: None})
@require_permission('investments', DELETE)
def delete_investment_endpoint(request, investment_id: int):
    services.delete_investment_service(user=request.user, investment_id=investment_id)
    return 204, None


@router.get('/investment/{investment_id}/movements', response=list[MovementOut])
@require_permission('investments', VIEW)
def list_movements_endpoint(request, investment_id: int):
    inv = services.get_investment_service(user=request.user, investment_id=investment_id)
    return inv.movements.select_related('transaction__account').order_by('-date', '-id')  # type:ignore


@router.post('/investment/{investment_id}/movements', response={201: MovementOut})
@require_permission('investments', CHANGE)
def create_movement_endpoint(request, investment_id: int, data: CreateMovement):
    return 201, services.create_movement_service(user=request.user, investment_id=investment_id, **data.dict())


@router.delete('/investment-movement/{movement_id}', response={204: None})
@require_permission('investments', CHANGE)
def delete_movement_endpoint(request, movement_id: int):
    services.delete_movement_service(user=request.user, movement_id=movement_id)
    return 204, None
