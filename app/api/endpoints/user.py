from ninja import Router

from api.schemas.users_dto import CreateUserDTO, UserOut
from apps.users import services

router = Router(tags=['Auth'])


@router.post('/user', response={201: UserOut})
def create_user_endpoint(request, data: CreateUserDTO):
    return 201, services.create_user_service(email=data.email, password=data.password)


@router.get('/me', response=UserOut)
def me_endpoint(request):
    return request.user


@router.post('/user/deactivate/{user_id}', response={204: None})
def deactivate_user_endpoint(request, user_id: int):
    return 204, services.deactivate_user_service(
        requested_by=request.user, user_id=user_id
    )
