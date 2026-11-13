from ninja import Query, Router

from api.schemas.reports_dto import CashFlowOut, CashFlowParams, DREOut, DREParams
from api.schemas.transactions_dto import ReportFilters
from apps.finance import selectors
from apps.users.permissions import VIEW, require_permission

router = Router(tags=['Reports'])


@router.get('/reports/dre', response=DREOut)
@require_permission('reports', VIEW)
def dre_endpoint(request, params: Query[DREParams], filters: Query[ReportFilters]):
    return selectors.dre_selector(user=request.user, year=params.year, **filters.dict())


@router.get('/reports/cash-flow', response=CashFlowOut)
@require_permission('reports', VIEW)
def cash_flow_endpoint(request, params: Query[CashFlowParams], filters: Query[ReportFilters]):
    return selectors.cash_flow_selector(user=request.user, **params.dict(), **filters.dict())
