from datetime import date
from decimal import Decimal

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from ninja_jwt.tokens import AccessToken

from apps.attachments import services as attachment_services
from apps.attachments.models import Attachment, AttachmentEvent
from apps.companies.models import Company
from apps.finance import services
from apps.finance.models import Group, TransactionType
from apps.users.models import Role, User

MEMORY_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


def pdf(name='nota.pdf', content=b'%PDF-1.4 fake'):
    return SimpleUploadedFile(name, content, content_type='application/pdf')


@override_settings(STORAGES=MEMORY_STORAGES)
class AttachmentEndpointTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.finance = User.objects.create_user(email='fin@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.accountant = User.objects.create_user(email='acc@test.com', password='Str@ngPassw8rd2026', role=Role.ACCOUNTANT)
        self.manager = User.objects.create_user(email='man@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.other_company = Company.objects.create(name='B', cnpj='11222333000181')
        for user in (self.finance, self.accountant, self.manager):
            user.companies.add(self.company)
        subgroup = services.create_subgroup_service(name='Rent', group=Group.FIXED_COSTS)
        self.tx = self.create_tx(self.company, subgroup)
        self.other_tx = self.create_tx(self.other_company, subgroup)
        self.contact = services.create_contact_service(name='Landlord')

    def create_tx(self, company, subgroup):
        return services.create_transaction_service(
            user=self.admin, company_id=company.pk, subgroup_id=subgroup.pk,
            date=date(2026, 1, 10), amount=Decimal('100'), type=TransactionType.OUTFLOW,
        )

    def upload(self, user, target='transaction', target_id=None, file=None):
        return self.client.post('/api/attachment', data={
            'target': target, 'target_id': target_id or self.tx.pk, 'file': file or pdf(),
        }, headers=auth_for(user))

    def attach(self, parent=None, user=None, file=None):
        parent = parent or self.tx
        target = 'contact' if parent is self.contact else 'transaction'
        with self.captureOnCommitCallbacks(execute=True):
            return attachment_services.upload_attachment_service(
                user=user or self.admin, target=target, target_id=parent.pk, file=file or pdf()
            )

    # Upload

    def test_upload_to_transaction(self):
        response = self.upload(self.finance)

        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data['name'], 'nota.pdf')
        self.assertEqual(data['target'], 'transaction')
        self.assertEqual(data['target_id'], self.tx.pk)
        self.assertEqual(data['size'], len(b'%PDF-1.4 fake'))
        self.assertEqual(data['uploaded_by_id'], self.finance.pk)
        attachment = Attachment.objects.get()
        self.assertTrue(default_storage.exists(attachment.file.name))

    def test_stored_name_is_random_not_the_original(self):
        self.upload(self.finance, file=pdf(name='../../etc/passwd.pdf'))

        attachment = Attachment.objects.get()
        self.assertEqual(attachment.name, 'passwd.pdf')
        self.assertTrue(attachment.file.name.startswith('attachments/transaction/'))
        self.assertNotIn('passwd', attachment.file.name)

    def test_upload_to_contact(self):
        response = self.upload(self.finance, target='contact', target_id=self.contact.pk)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.contact.attachments.count(), 1)

    def test_upload_to_legal_action(self):
        from apps.legal.models import CollectionCase
        case = CollectionCase.objects.create(company=self.company, contact=self.contact)
        legal = User.objects.create_user(email='jur@test.com', password='Str@ngPassw8rd2026', role=Role.LEGAL)
        legal.companies.add(self.company)

        response = self.upload(legal, target='collection_case', target_id=case.pk)

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(case.attachments.count(), 1)
        self.assertEqual(self.upload(self.manager, target='collection_case', target_id=case.pk).status_code, 403)
        listed = self.client.get(f'/api/attachment?target=collection_case&target_id={case.pk}', headers=auth_for(legal))
        self.assertEqual([a['name'] for a in listed.json()], ['nota.pdf'])

    def test_upload_without_change_permission_returns_403(self):
        for user in (self.accountant, self.manager):
            with self.subTest(role=user.role):
                self.assertEqual(self.upload(user).status_code, 403)
        self.assertFalse(Attachment.objects.exists())

    def test_upload_to_not_linked_company_returns_404(self):
        response = self.upload(self.finance, target_id=self.other_tx.pk)

        self.assertEqual(response.status_code, 404)

    def test_upload_to_non_existing_record_returns_404(self):
        self.assertEqual(self.upload(self.finance, target_id=999999).status_code, 404)

    def test_upload_invalid_target_returns_422(self):
        self.assertEqual(self.upload(self.finance, target='company').status_code, 422)

    def test_upload_invalid_files_return_400(self):
        cases = {
            'executable': SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream'),
            'no extension': SimpleUploadedFile('file', b'data'),
            'empty': SimpleUploadedFile('empty.pdf', b'', content_type='application/pdf'),
        }
        for name, file in cases.items():
            with self.subTest(case=name):
                self.assertEqual(self.upload(self.finance, file=file).status_code, 400)
        self.assertFalse(Attachment.objects.exists())

    def test_upload_too_large_returns_400(self):
        big = SimpleUploadedFile('big.pdf', b'0' * (attachment_services.MAX_SIZE + 1))

        self.assertEqual(self.upload(self.finance, file=big).status_code, 400)

    def test_upload_allowed_types(self):
        for name in ('nf.xml', 'scan.JPG', 'planilha.xlsx', 'boleto.png'):
            with self.subTest(file=name):
                file = SimpleUploadedFile(name, b'content')
                self.assertEqual(self.upload(self.finance, file=file).status_code, 201)

    def test_upload_requires_authentication(self):
        response = self.client.post('/api/attachment', data={'target': 'transaction', 'target_id': self.tx.pk, 'file': pdf()})

        self.assertEqual(response.status_code, 401)

    # List

    def test_list_attachments_of_record(self):
        a = self.attach()
        self.attach(parent=self.other_tx)
        self.attach(parent=self.contact)

        response = self.client.get(
            f'/api/attachment?target=transaction&target_id={self.tx.pk}', headers=auth_for(self.accountant)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([x['id'] for x in response.json()], [a.pk])

    def test_list_without_view_permission_returns_403(self):
        response = self.client.get(
            f'/api/attachment?target=transaction&target_id={self.tx.pk}', headers=auth_for(self.manager)
        )

        self.assertEqual(response.status_code, 403)

    def test_list_of_not_linked_company_returns_404(self):
        response = self.client.get(
            f'/api/attachment?target=transaction&target_id={self.other_tx.pk}', headers=auth_for(self.finance)
        )

        self.assertEqual(response.status_code, 404)

    # Download

    def test_download(self):
        attachment = self.attach(file=pdf(name='Nota Fiscal.pdf', content=b'%PDF-1.4 real bytes'))

        response = self.client.get(f'/api/attachment/{attachment.pk}/download', headers=auth_for(self.accountant))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'%PDF-1.4 real bytes')
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment; filename="Nota Fiscal.pdf"', response['Content-Disposition'])

    def test_download_from_not_linked_company_returns_404(self):
        attachment = self.attach(parent=self.other_tx)

        response = self.client.get(f'/api/attachment/{attachment.pk}/download', headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 404)

    def test_download_without_permission_returns_403(self):
        attachment = self.attach()

        response = self.client.get(f'/api/attachment/{attachment.pk}/download', headers=auth_for(self.manager))

        self.assertEqual(response.status_code, 403)

    def test_download_non_existing_returns_404(self):
        self.assertEqual(
            self.client.get('/api/attachment/999999/download', headers=auth_for(self.finance)).status_code, 404
        )

    # Delete

    def test_delete_removes_row_and_file(self):
        attachment = self.attach()
        stored = attachment.file.name

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.delete(f'/api/attachment/{attachment.pk}', headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 204)
        self.assertFalse(Attachment.objects.exists())
        self.assertFalse(default_storage.exists(stored))

    def test_delete_without_change_permission_returns_403(self):
        attachment = self.attach()

        response = self.client.delete(f'/api/attachment/{attachment.pk}', headers=auth_for(self.accountant))

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())

    def test_delete_from_not_linked_company_returns_404(self):
        attachment = self.attach(parent=self.other_tx)

        response = self.client.delete(f'/api/attachment/{attachment.pk}', headers=auth_for(self.finance))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(Attachment.objects.filter(pk=attachment.pk).exists())

    def test_deleting_transaction_cascades_attachments_and_files(self):
        attachment = self.attach()
        stored = attachment.file.name

        with self.captureOnCommitCallbacks(execute=True):
            services.delete_transaction_service(user=self.admin, transaction_id=self.tx.pk)

        self.assertFalse(Attachment.objects.exists())
        self.assertFalse(default_storage.exists(stored))

    # History

    def test_history_records_upload_and_delete(self):
        attachment = self.attach()
        with self.captureOnCommitCallbacks(execute=True):
            attachment_services.delete_attachment_service(user=self.admin, attachment_id=attachment.pk)

        labels = list(AttachmentEvent.objects.order_by('pgh_id').values_list('pgh_label', flat=True))
        self.assertEqual(labels, ['insert', 'delete'])
