from django.db import connection
from django.db.utils import OperationalError
from ninja_extra import NinjaExtraAPI
from ninja_jwt.authentication import JWTAuth
from ninja_jwt.controller import NinjaJWTDefaultController

from api.endpoints.companies import router as company_router
from api.endpoints.user import router as user_router
from api.exceptions_handlers import register_exception_handlers

api = NinjaExtraAPI(title='API GP', version='1.0.0', auth=JWTAuth())

api.register_controllers(NinjaJWTDefaultController)

register_exception_handlers(api)


@api.get('/health', auth=None, tags=['Health'], response={200: dict, 503: dict})
def health(request):
    try:
        connection.ensure_connection()
    except OperationalError:
        return 503, {'status': 'error', 'database': 'unreachable'}
    return 200, {'status': 'ok'}


# Routers
api.add_router('/', user_router)
api.add_router('/', company_router)
