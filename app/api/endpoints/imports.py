import json

from django.core.exceptions import ValidationError
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile

from apps.finance.importer import import_upload_service

router = Router(tags=['Import'])


class SkippedRow(Schema):
    row: int
    reason: str


class ImportOut(Schema):
    committed: bool
    company_names: list[str]        # names found in the "Empresa" column
    unmapped_companies: list[str]   # must be mapped before committing
    transactions_found: int
    sales_found: int
    subgroups_created: int
    contacts_created: int
    products_created: int
    transactions_created: int
    sales_created: int
    skipped: list[SkippedRow]


@router.post('/import', response=ImportOut)
def import_endpoint(
    request,
    file: File[UploadedFile],
    default_company_id: Form[int],
    companies: Form[str] = '{}',
    commit: Form[bool] = False,
):
    """Preview (commit=false, default) or run the legacy spreadsheet import.

    `companies` is a JSON object mapping each name of the "Empresa" column to a company id,
    e.g. {"O HENRIQUECEDOR": 2}. Rows with an empty company go to `default_company_id`.
    """
    try:
        mapping = json.loads(companies)
        if not isinstance(mapping, dict) or not all(isinstance(v, int) for v in mapping.values()):
            raise ValueError
    except ValueError:
        raise ValidationError('companies must be a JSON object of {"NAME": company_id}')
    return import_upload_service(
        user=request.user, file=file, default_company_id=default_company_id,
        companies=mapping, commit=commit,
    )
