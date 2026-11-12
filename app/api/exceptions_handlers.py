from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError

def register_exception_handlers(api):

    @api.exception_handler(ValidationError)
    def validation_error_treatment(request, exc: ValidationError):
        return api.create_response(request, {'detail': exc.messages}, status=400)

    @api.exception_handler(PermissionDenied)
    def permission_denied_treatment(request, exc: PermissionDenied):
        return api.create_response(request, {'detail': str(exc) or 'No permission'}, status=403)

    @api.exception_handler(ObjectDoesNotExist)
    def object_not_exist_treatment(request, exc: ObjectDoesNotExist):
        return api.create_response(request, {'detail': str(exc) or 'Not found'}, status=404)