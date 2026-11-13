from ninja import Query, Router

from api.schemas.reports_dto import CashFlowOut, CashFlowParams, DREOut, DREParams
from api.schemas.transactions_dto import ReportFilters
from apps.finance import selectors

router = Router(tags=['Reports'])


@router.get('/reports/dre', response=DREOut)
def dre_endpoint(request, params: Query[DREParams], filters: Query[ReportFilters]):
    return selectors.dre_selector(user=request.user, year=params.year, **filters.dict())


@router.get('/reports/cash-flow', response=CashFlowOut)
def cash_flow_endpoint(request, params: Query[CashFlowParams], filters: Query[ReportFilters]):
    return selectors.cash_flow_selector(user=request.user, **params.dict(), **filters.dict())
