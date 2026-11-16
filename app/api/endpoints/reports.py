from django.http import HttpResponse
from django.utils import timezone
from ninja import Query, Router

from api.schemas.reports_dto import CashFlowOut, CashFlowParams, DREOut, DREParams, DRETableOut, DRETableParams
from api.schemas.transactions_dto import ReportFilters
from apps.companies.services import list_companies_service
from apps.finance import selectors
from apps.finance.exporter import XLSX_CONTENT_TYPE, cash_flow_xlsx, dre_xlsx
from apps.finance.models import TransactionStatus
from apps.users.permissions import VIEW, require_permission

router = Router(tags=['Reports'])


@router.get('/reports/dre', response=DREOut)
@require_permission('reports', VIEW)
def dre_endpoint(request, params: Query[DREParams], filters: Query[ReportFilters]):
    return selectors.dre_selector(user=request.user, year=params.year, **filters.dict())


def _dre_table(request, params: DRETableParams, filters: ReportFilters) -> dict:
    return selectors.dre_table_selector(
        user=request.user, view=params.view, year=params.year, month=params.month, **filters.dict()
    )


@router.get('/reports/dre/table', response=DRETableOut)
@require_permission('reports', VIEW)
def dre_table_endpoint(request, params: Query[DRETableParams], filters: Query[ReportFilters]):
    """DRE in one of its views (monthly, year vs previous year, month vs previous/last year)."""
    return _dre_table(request, params, filters)


def _filters_subtitle(request, filters: ReportFilters) -> str:
    """Human description of the filters, printed on the exported sheet."""
    companies = list_companies_service(user=request.user)
    if filters.company_id:
        companies = companies.filter(pk__in=filters.company_id)
    names = ', '.join(c.name for c in companies) if filters.company_id else 'Consolidado (todas as empresas)'
    status = ', '.join(TransactionStatus(s).label for s in filters.status) if filters.status else 'Previsto e realizado'
    return f'{names} · {status} · gerado em {timezone.localtime():%d/%m/%Y %H:%M}'


def _xlsx_response(content: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(content, content_type=XLSX_CONTENT_TYPE)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@router.get('/reports/dre/export')
@require_permission('reports', VIEW)
def dre_export_endpoint(request, params: Query[DRETableParams], filters: Query[ReportFilters]):
    """Excel with exactly the DRE view on screen (same params as /reports/dre/table)."""
    table = _dre_table(request, params, filters)
    suffix = f'{params.year}-{params.month:02d}' if params.view == 'month' else str(params.year)
    return _xlsx_response(
        dre_xlsx(table, _filters_subtitle(request, filters), percent=params.percent),
        f'dre-{params.view}-{suffix}.xlsx',
    )


@router.get('/reports/cash-flow', response=CashFlowOut)
@require_permission('reports', VIEW)
def cash_flow_endpoint(request, params: Query[CashFlowParams], filters: Query[ReportFilters]):
    return selectors.cash_flow_selector(user=request.user, **params.dict(), **filters.dict())


@router.get('/reports/cash-flow/export')
@require_permission('reports', VIEW)
def cash_flow_export_endpoint(request, params: Query[CashFlowParams], filters: Query[ReportFilters]):
    flow = selectors.cash_flow_selector(user=request.user, **params.dict(), **filters.dict())
    return _xlsx_response(
        cash_flow_xlsx(flow, _filters_subtitle(request, filters)),
        f'fluxo-de-caixa-{params.start:%Y-%m-%d}-a-{params.end:%Y-%m-%d}.xlsx',
    )
