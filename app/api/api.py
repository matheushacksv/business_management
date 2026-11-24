from django.db import connection
from django.db.utils import OperationalError
from ninja_extra import NinjaExtraAPI

from api.endpoints.accounts import router as account_router
from api.authentication import CookieJWTAuth
from api.endpoints.attachments import router as attachment_router
from api.endpoints.auth import router as auth_router
from api.endpoints.companies import router as company_router
from api.endpoints.contacts import router as contact_router
from api.endpoints.dunning import router as dunning_router
from api.endpoints.history import router as history_router
from api.endpoints.imports import router as import_router
from api.endpoints.integrations import router as integrations_router
from api.endpoints.invoices import router as invoice_router
from api.endpoints.investments import router as investment_router
from api.endpoints.legal import router as legal_router
from api.endpoints.reports import router as report_router
from api.endpoints.sales import router as sales_router
from api.endpoints.subgroups import router as subgroup_router
from api.endpoints.transactions import router as transaction_router
from api.endpoints.user import router as user_router
from api.exceptions_handlers import register_exception_handlers

api = NinjaExtraAPI(title='API GP', version='1.0.0', auth=CookieJWTAuth())

register_exception_handlers(api)


@api.get('/health', auth=None, tags=['Health'], response={200: dict, 503: dict})
def health(request):
    try:
        connection.ensure_connection()
    except OperationalError:
        return 503, {'status': 'error', 'database': 'unreachable'}
    return 200, {'status': 'ok'}


# Routers
api.add_router('/', auth_router)
api.add_router('/', user_router)
api.add_router('/', company_router)
api.add_router('/', subgroup_router)
api.add_router('/', contact_router)
api.add_router('/', account_router)
api.add_router('/', transaction_router)
api.add_router('/', report_router)
api.add_router('/', attachment_router)
api.add_router('/', invoice_router)
api.add_router('/', sales_router)
api.add_router('/', import_router)
api.add_router('/', history_router)
api.add_router('/', legal_router)
api.add_router('/', investment_router)
api.add_router('/', dunning_router)
api.add_router('/', integrations_router)
