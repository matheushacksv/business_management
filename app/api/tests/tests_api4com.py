from datetime import date
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.dunning.models import Activity, Card, Stage
from apps.finance.models import Contact
from apps.integrations.models import Call, PhoneLine, WebhookEvent
from apps.users.models import User


class FakeApi4com:
    """Stands in for api4com.request: records calls, answers like the API. `fail` = {path: HTTP code}."""

    def __init__(self):
        self.calls, self.fail = [], {}

    def __call__(self, token, method, path, body=None, **query):
        self.calls.append((token, method, path, body, query))
        if path in self.fail:
            code = self.fail.pop(path)
            raise ValidationError(f'HTTP {code}', code=str(code))
        if path == '/users/login':
            return {'id': 'login-token'}
        if path == '/users/accessTokens':
            return {'id': 'forever-token'}
        if path == '/integrations' and method == 'GET':
            gateway = query['filter[where][gateway]']
            return [{'id': 5821, 'metadata': {'username': '1012'}}] if gateway == 'sippulse' else []
        return {'status': '200', 'id': 'x'}

    def made(self, method, path):
        return [c for c in self.calls if c[1] == method and c[2] == path]


class Api4comTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        company = Company.objects.create(name='A', cnpj='81585365000127')
        self.contact = contact = Contact.objects.create(name='Cliente X', phone='(51) 99999-0000')
        card = Card.objects.create(company=company, contact=contact, stage=Stage.objects.first(), overdue_since=date(2026, 11, 1))
        self.activity = Activity.objects.create(card=card, kind='call', title='Ligar', due_date=date(2026, 11, 25))
        self.fake = FakeApi4com()
        patcher = patch('apps.integrations.api4com.request', self.fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def api(self, method, path, body=None):
        return getattr(self.client, method)(f'/api{path}', data=body, content_type='application/json',
                                            headers={'Authorization': f'Bearer {AccessToken.for_user(self.admin)}'})  # type:ignore

    def connect(self):
        r = self.api('put', f'/integrations/api4com/{self.admin.pk}', {'email': 'a@x.com', 'password': 'secret'})
        self.assertEqual(r.status_code, 200, r.content)
        return PhoneLine.objects.get(user=self.admin)

    def hook(self, line, payload):
        return self.client.post(f'/api/webhooks/api4com/{line.webhook_secret}', data=payload, content_type='application/json')

    def test_connect_keeps_token_not_password(self):
        line = self.connect()
        self.assertEqual((line.token, line.extension, line.valid), ('forever-token', '1012', True))
        self.assertEqual(self.fake.made('POST', '/users/accessTokens')[0][0], 'login-token')
        webhook = self.fake.made('PATCH', '/integrations')[0][3]
        self.assertTrue(webhook['metadata']['webhookUrl'].endswith(f'/api/webhooks/api4com/{line.webhook_secret}'))
        self.assertNotIn('id', webhook)  # created, not updated
        listed = self.api('get', '/integrations/api4com').json()
        self.assertNotIn('token', listed[0])
        self.assertTrue(self.api('get', '/me').json()['has_phone_line'])

    def test_call_answered_completes_activity(self):
        line = self.connect()
        r = self.api('post', f'/dunning/activity/{self.activity.pk}/call')
        self.assertEqual(r.status_code, 201, r.content)
        body = self.fake.made('POST', '/calls')[0][3]
        self.assertEqual((body['called'], body['extension'], body['metadata']['callRef']), ('+5551999990000', '1012', str(r.json()['id'])))

        meta = body['metadata']
        self.assertEqual(self.hook(line, {'eventType': 'channel-answer', 'id': 'u1', 'metadata': meta}).json()['status'], 'processed')
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.done_at)  # only once the call ends with a real conversation

        self.hook(line, {'eventType': 'channel-hangup', 'id': 'u1', 'answeredAt': '2026-11-25 10:00:05', 'duration': 42,
                         'hangupCause': 'NORMAL_CLEARING', 'recordUrl': 'https://listener.api4com.com/files/listen/u1.mp3',
                         'metadata': meta})
        self.activity.refresh_from_db()
        self.assertTrue(self.activity.done_at and self.activity.answered)
        self.assertEqual(self.activity.done_by, self.admin)
        call = Call.objects.get()
        self.assertEqual((call.duration, call.external_id, call.record_url), (42, 'u1', 'https://listener.api4com.com/files/listen/u1.mp3'))
        listed = self.api('get', f'/contact/{self.contact.pk}/calls').json()
        self.assertEqual((listed[0]['duration'], listed[0]['activity_title']), (42, 'Ligar'))
        self.assertIsNotNone(self.api('get', f'/call/{call.pk}').json()['ended_at'])

    def test_short_answered_call_keeps_activity_open(self):
        line = self.connect()
        call_id = self.api('post', f'/dunning/activity/{self.activity.pk}/call').json()['id']
        self.hook(line, {'eventType': 'channel-hangup', 'id': 'u3', 'answeredAt': '2026-11-25 10:00:05', 'duration': 4,
                         'metadata': {'gateway': 'gestao-enriquecedor', 'callRef': str(call_id)}})
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.done_at)  # picked up and hung up / dropped: call again
        self.assertIsNotNone(Call.objects.get().answered_at)

    def test_call_without_activity(self):
        line = self.connect()
        r = self.api('post', f'/contact/{self.contact.pk}/call')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertIsNone(r.json()['activity_id'])
        self.hook(line, {'eventType': 'channel-hangup', 'id': 'u4', 'answeredAt': 'x', 'duration': 60,
                         'metadata': {'gateway': 'gestao-enriquecedor', 'callRef': str(r.json()['id'])}})
        self.assertEqual(Call.objects.get().duration, 60)
        other = User.objects.create_user(email='b@test.com', password='Str@ngPassw8rd2026')
        r = self.client.get(f'/api/call/{r.json()["id"]}', headers={'Authorization': f'Bearer {AccessToken.for_user(other)}'})  # type:ignore
        self.assertEqual(r.status_code, 404)  # someone else's call

    def test_unanswered_call_keeps_activity_open(self):
        line = self.connect()
        call_id = self.api('post', f'/dunning/activity/{self.activity.pk}/call').json()['id']
        self.hook(line, {'eventType': 'channel-hangup', 'id': 'u2', 'answeredAt': '', 'duration': 0, 'hangupCause': 'NO_ANSWER',
                         'recordUrl': 'https://evil.com/x.mp3', 'metadata': {'gateway': 'gestao-enriquecedor', 'callRef': str(call_id)}})
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.done_at)
        call = Call.objects.get()
        self.assertEqual((call.hangup_cause, call.record_url, call.answered_at), ('NO_ANSWER', '', None))

    def test_webhook_rejects_wrong_secret_and_other_users_calls(self):
        line = self.connect()
        self.assertEqual(self.client.post('/api/webhooks/api4com/nope', data={}, content_type='application/json').status_code, 401)
        other = User.objects.create_user(email='b@test.com', password='Str@ngPassw8rd2026')
        foreign = Call.objects.create(activity=self.activity, user=other, called='+5551999990000')
        r = self.hook(line, {'eventType': 'channel-answer', 'metadata': {'gateway': 'gestao-enriquecedor', 'callRef': str(foreign.pk)}})
        self.assertEqual(r.json()['status'], 'ignored')
        self.activity.refresh_from_db()
        self.assertIsNone(self.activity.done_at)

    def test_call_errors(self):
        self.assertEqual(self.api('post', f'/dunning/activity/{self.activity.pk}/call').status_code, 400)  # not connected
        line = self.connect()
        self.fake.fail['/calls'] = 404  # extension changed: fetched again, retried once
        self.assertEqual(self.api('post', f'/dunning/activity/{self.activity.pk}/call').status_code, 201)
        self.assertEqual(len(self.fake.made('POST', '/calls')), 2)
        self.fake.fail['/calls'] = 401  # token gone: line invalid, call not kept
        self.assertEqual(self.api('post', f'/dunning/activity/{self.activity.pk}/call').status_code, 400)
        line.refresh_from_db()
        self.assertFalse(line.valid)
        self.assertEqual(Call.objects.count(), 1)
        self.assertEqual(WebhookEvent.objects.count(), 0)
