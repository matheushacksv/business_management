"""Role-based permissions per module (PDF section 13).

Two layers:
- module/action: what a role can do (this file), checked at the API layer;
- company scope: which CNPJs a user sees (User.companies), enforced by the services.
Admins (role or superuser) can do everything on every company.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.users.models import Role, User

VIEW, CREATE, CHANGE, DELETE = 'view', 'create', 'change', 'delete'
ALL = frozenset({VIEW, CREATE, CHANGE, DELETE})
READ = frozenset({VIEW})

MODULES = ('users', 'companies', 'subgroups', 'contacts', 'accounts', 'transactions', 'reports', 'sales', 'legal', 'dunning')

# ponytail: fixed matrix in code; move to DB (Django Groups) if the client needs custom roles
PERMISSIONS: dict[str, dict[str, frozenset[str]]] = {
    Role.FINANCE: {
        'companies': READ, 'subgroups': READ, 'contacts': ALL, 'accounts': ALL,
        'transactions': ALL, 'reports': READ, 'sales': ALL, 'legal': ALL, 'dunning': ALL,
    },
    Role.ACCOUNTANT: {
        'companies': READ, 'subgroups': READ, 'contacts': READ, 'accounts': READ,
        'transactions': READ, 'reports': READ, 'sales': READ,
    },
    Role.MANAGER: {'companies': READ, 'subgroups': READ, 'reports': READ, 'sales': READ, 'legal': READ, 'dunning': READ},
    Role.LEGAL: {'companies': READ, 'contacts': READ, 'sales': READ, 'legal': ALL},  # contracts of their cases
}


def has_permission(user: User, module: str, action: str) -> bool:
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_admin:
        return True
    return action in PERMISSIONS.get(user.role, {}).get(module, frozenset())


def check_permission(user: User, module: str, action: str) -> None:
    if not has_permission(user, module, action):
        raise PermissionDenied(f'No permission to {action} {module}')


def permissions_for(user: User) -> dict[str, list[str]]:
    return {
        module: sorted(a for a in ALL if has_permission(user, module, a)) for module in MODULES
    }


def require_permission(module: str, action: str):
    """Endpoint decorator; keep it below the router decorator."""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            check_permission(request.user, module, action)
            return func(request, *args, **kwargs)
        return wrapper
    return decorator
