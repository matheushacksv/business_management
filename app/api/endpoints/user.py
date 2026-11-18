from ninja import Router

from api.schemas.users_dto import ChangePasswordDTO, CreateUserDTO, MeOut, PatchUserDTO, UserOut
from apps.users import services
from apps.users.permissions import CHANGE, CREATE, DELETE, VIEW, require_permission

router = Router(tags=['Users'])


@router.get('/me', response=MeOut)
def me_endpoint(request):
    return request.user


@router.post('/me/password', response={204: None})
def change_password_endpoint(request, data: ChangePasswordDTO):
    services.change_password_service(
        user=request.user, current_password=data.current_password, new_password=data.new_password
    )
    return 204, None


@router.post('/user', response={201: UserOut})
@require_permission('users', CREATE)
def create_user_endpoint(request, data: CreateUserDTO):
    return 201, services.create_user_service(**data.dict(exclude={'repeat_password'}))


@router.get('/user', response=list[UserOut])
@require_permission('users', VIEW)
def list_users_endpoint(request):
    return services.list_users_service()


@router.get('/user/{user_id}', response=UserOut)
@require_permission('users', VIEW)
def get_user_endpoint(request, user_id: int):
    return services.get_user_service(user_id=user_id)


@router.patch('/user/{user_id}', response=UserOut)
@require_permission('users', CHANGE)
def update_user_endpoint(request, user_id: int, data: PatchUserDTO):
    return services.update_user_service(
        requested_by=request.user, user_id=user_id, **data.dict(exclude_unset=True, exclude_none=True)
    )


@router.post('/user/deactivate/{user_id}', response={204: None})
@require_permission('users', DELETE)
def deactivate_user_endpoint(request, user_id: int):
    services.deactivate_user_service(requested_by=request.user, user_id=user_id)
    return 204, None
