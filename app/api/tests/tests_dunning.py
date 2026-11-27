import datetime as dt
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from ninja_jwt.tokens import AccessToken

from apps.companies.models import Company
from apps.dunning import services
from apps.dunning.models import Activity, Card, Config, Outcome, Stage
from apps.finance import services as finance
from apps.finance.models import Contact, Group, Transaction, TransactionStatus, TransactionType
from apps.legal.models import CollectionCase
from apps.users.models import Role, User

TODAY = dt.date(2026, 11, 20)


def auth_for(user):
    return {'Authorization': f'Bearer {AccessToken.for_user(user)}'}  # type:ignore


@patch('django.utils.timezone.localdate', lambda *a: TODAY)
class DunningTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(email='admin@test.com', password='Str@ngPassw8rd2026')
        self.company = Company.objects.create(name='A', cnpj='81585365000127')
        self.subgroup = finance.create_subgroup_service(name='Assessorias', group=Group.OPERATING_REVENUE)
        self.client_ = Contact.objects.create(name='Cliente X', phone='51999990000')
        Config.objects.update(start_date=None)

    def api(self, method, path, body=None, user=None):
        return getattr(self.client, method)(f'/api{path}', data=body, content_type='application/json',
                                            headers=auth_for(user or self.admin))

    def installment(self, date, amount='1000', status=TransactionStatus.PLANNED):
        return Transaction.objects.create(company=self.company, subgroup=self.subgroup, contact=self.client_, date=date,
                                          amount=Decimal(amount), type=TransactionType.INFLOW, status=status)

    def cards(self, outcome='open'):
        r = self.api('get', f'/dunning/card?outcome={outcome}')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_card_opens_on_first_day_late_once_with_cadence(self):
        self.installment(TODAY)  # due today: not late yet
        self.assertEqual(self.cards(), [])
        self.installment(dt.date(2026, 11, 19))
        self.installment(dt.date(2026, 11, 10), '500')
        cards = self.cards()
        self.assertEqual(len(cards), 1)  # one card per customer, several installments
        card = cards[0]
        self.assertEqual((Decimal(card['overdue_amount']), card['overdue_count']), (Decimal('1500'), 2))
        self.assertEqual(card['stage_id'], Stage.objects.first().pk)
        self.assertEqual(card['oldest_overdue'], '2026-11-10')
        # backlog (10/11) starts the cadence today; each step is created when its day comes
        dues = lambda: sorted(Activity.objects.values_list('due_date', flat=True))  # noqa: E731
        self.assertEqual(dues(), [TODAY])
        self.cards()
        self.assertEqual(Card.objects.count(), 1)
        services.sync_cards_service(today=TODAY + dt.timedelta(days=3))  # day 4: steps of days 3 and 4
        services.sync_cards_service(today=TODAY + dt.timedelta(days=3))
        self.assertEqual(dues(), [TODAY, TODAY + dt.timedelta(days=2), TODAY + dt.timedelta(days=3)])

    def test_team_notes(self):
        self.installment(dt.date(2026, 11, 19))
        card = self.cards()[0]
        r = self.api('post', f'/dunning/card/{card["id"]}/notes', {'text': '  prometeu pagar sexta  '})
        self.assertEqual(r.status_code, 201, r.content)
        notes = self.api('get', f'/dunning/card/{card["id"]}/notes').json()
        self.assertEqual([(n['text'], n['author_name']) for n in notes], [('prometeu pagar sexta', 'admin@test.com')])
        manager = User.objects.create_user(email='m@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.assertEqual(self.api('post', f'/dunning/card/{card["id"]}/notes', {'text': 'x'}, user=manager).status_code, 403)

    def test_paid_off_resolves_and_new_delay_opens_new_card(self):
        tx = self.installment(dt.date(2026, 11, 19))
        self.cards()
        tx.status = TransactionStatus.REALIZED
        tx.save()
        self.assertEqual(self.cards(), [])  # leaves the board
        card = self.cards('resolved')[0]
        self.assertEqual((card['closed_at'], card['outcome']), ('2026-11-20', 'resolved'))
        self.installment(dt.date(2026, 11, 15))
        self.cards()
        self.assertEqual(Card.objects.count(), 2)

    def test_payment_closes_card_at_once_with_note(self):
        tx = self.installment(dt.date(2026, 11, 19), '1500')
        tx.reference = '3/10'
        tx.save()
        self.cards()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api('patch', f'/transaction/{tx.pk}', {'status': 'realized', 'date': '2026-11-20'})
        self.assertEqual(r.status_code, 200, r.content)
        card = Card.objects.get()  # closed without loading the board
        self.assertEqual(card.outcome, Outcome.RESOLVED)
        self.assertEqual(card.notes.get().text, 'Resolvido automaticamente: 3/10 de R$ 1.500,00 paga em 20/11/2026')

    def test_resolve_by_hand_needs_nothing_overdue(self):
        self.installment(dt.date(2026, 11, 19))
        card = self.cards()[0]
        self.assertEqual(self.api('patch', f'/dunning/card/{card["id"]}', {'outcome': 'resolved'}).status_code, 400)

    def test_resolve_with_payment_date_settles_late_installments(self):
        tx = self.installment(dt.date(2026, 11, 19), '2000')
        card = self.cards()[0]
        with self.captureOnCommitCallbacks(execute=True):
            r = self.api('patch', f'/dunning/card/{card["id"]}', {'outcome': 'resolved', 'paid_on': '2026-11-20'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['outcome'], 'resolved')
        tx.refresh_from_db()
        self.assertEqual((tx.status, tx.date), (TransactionStatus.REALIZED, dt.date(2026, 11, 20)))
        self.assertEqual(Card.objects.get().notes.get().text, 'Baixa ao resolver: parcela de R$ 2.000,00 paga em 20/11/2026')

    def test_legal_stage_opens_case_and_closes_card(self):
        self.installment(dt.date(2026, 11, 19))
        future = self.installment(dt.date(2026, 12, 19))
        card = self.cards()[0]
        # the legal form comes first: every field is required to enter the legal funnel
        self.assertEqual(self.api('patch', f'/dunning/card/{card["id"]}', {'outcome': 'legal'}).status_code, 400)
        r = self.api('post', '/collection-case', {
            'company_id': self.company.pk, 'contact_id': self.client_.pk, 'client_company': 'X Ltda', 'contact_info': 'zap',
            'delivered': 'mentoria', 'proposal_amount': '5000', 'paid_amount': '1000', 'summary': 'parou de pagar',
            'drive_link': 'https://drive.google.com/x'})
        self.assertEqual(r.status_code, 201, r.content)
        case = CollectionCase.objects.get()
        r = self.api('patch', f'/dunning/card/{card["id"]}', {'outcome': 'legal', 'legal_case_id': case.pk})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['legal_case_id'], r.json()['closed_at']), (case.pk, '2026-11-20'))
        future.refresh_from_db()
        self.assertEqual(future.collection_case_id, case.pk)
        self.assertEqual(self.cards(), [])
        self.assertEqual([c['id'] for c in self.cards('legal')], [card['id']])
        self.assertEqual(Card.objects.count(), 1)  # with the legal team now: no new card

    def test_activities_and_productivity(self):
        self.installment(dt.date(2026, 11, 19))
        card = self.cards()[0]
        self.api('patch', f'/dunning/card/{card["id"]}', {'assignee_id': self.admin.pk})
        acts = self.api('get', f'/dunning/card/{card["id"]}/activities').json()
        first = acts[0]
        r = self.api('patch', f'/dunning/activity/{first["id"]}', {'done': True, 'answered': False, 'notes': 'não atendeu'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['done_by_name'], 'admin@test.com')
        self.assertEqual(self.api('get', '/dunning/agenda').json(), [])  # day 1 done, the rest is in the future
        p = self.api('get', '/dunning/productivity?start=2026-11-01&end=2026-11-30').json()
        me = p['people'][0]
        self.assertEqual((me['done'], me['messages'], me['no_answer'], me['pending']), (1, 1, 1, 0))  # later steps not created yet
        self.assertEqual((p['open_cards'], Decimal(p['overdue_amount'])), (1, Decimal('1000')))

    def test_assignee_must_be_able_to_collect(self):
        self.installment(dt.date(2026, 11, 19))
        card = self.cards()[0]
        manager = User.objects.create_user(email='m@test.com', password='Str@ngPassw8rd2026', role=Role.MANAGER)
        self.assertEqual(self.api('patch', f'/dunning/card/{card["id"]}', {'assignee_id': manager.pk}).status_code, 400)

    def test_stages(self):
        self.assertEqual(Stage.objects.count(), 5)  # resolved / legal are outcomes, not stages
        tx = self.installment(dt.date(2026, 11, 19))
        stage = Stage.objects.get(pk=self.cards()[0]['stage_id'])
        self.assertEqual(self.api('delete', f'/dunning/stage/{stage.pk}').status_code, 400)  # has an open card
        tx.status = TransactionStatus.REALIZED
        tx.save()
        self.cards()
        self.assertEqual(self.api('delete', f'/dunning/stage/{stage.pk}').status_code, 204)  # closed cards move
        for s in Stage.objects.all()[1:]:
            s.delete()
        self.assertEqual(self.api('delete', f'/dunning/stage/{Stage.objects.get().pk}').status_code, 400)  # the last one

    def test_dismiss_until_a_newer_installment_is_late(self):
        self.installment(dt.date(2026, 11, 10))
        card = self.cards()[0]
        self.assertEqual(self.api('delete', f'/dunning/card/{card["id"]}').status_code, 204)
        self.assertEqual(self.cards(), [])
        self.assertEqual(Card.objects.get().outcome, Outcome.DISMISSED)
        self.installment(dt.date(2026, 11, 25))
        services.sync_cards_service(today=dt.date(2026, 11, 26))  # a newer one fell due: back, only with it
        reopened = Card.objects.get(closed_at__isnull=True)
        self.assertEqual(reopened.overdue_since, dt.date(2026, 11, 25))

    def test_other_company_hidden(self):
        self.installment(dt.date(2026, 11, 19))
        member = User.objects.create_user(email='f@test.com', password='Str@ngPassw8rd2026', role=Role.FINANCE)
        self.assertEqual(self.api('get', '/dunning/card', user=member).json(), [])
        services.sync_cards_service(today=TODAY)

    def test_start_date_ignores_older_backlog(self):
        self.assertEqual(self.api('put', '/dunning/config', {'start_date': '2026-11-15'}).status_code, 200)
        self.installment(dt.date(2026, 11, 10))
        self.assertEqual(self.cards(), [])
        self.installment(dt.date(2026, 11, 16), '700')
        card = self.cards()[0]
        self.assertEqual((Decimal(card['overdue_amount']), card['overdue_since']), (Decimal('700'), '2026-11-16'))

    def test_send_by_hand_takes_old_installments(self):
        Config.objects.update(start_date=dt.date(2026, 11, 15))
        self.assertEqual(self.api('post', f'/dunning/send/{self.client_.pk}').status_code, 400)  # nothing late
        self.installment(dt.date(2026, 10, 1), '400')  # before the start date: no automatic card
        self.assertEqual(self.cards(), [])
        r = self.api('post', f'/dunning/send/{self.client_.pk}')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((Decimal(r.json()[0]['overdue_amount']), r.json()[0]['overdue_since']), (Decimal('400'), '2026-10-01'))
        self.assertEqual(len(self.cards()), 1)  # sync keeps it open (old installment still late)
        self.assertEqual(self.api('post', f'/dunning/send/{self.client_.pk}').json()[0]['id'], r.json()[0]['id'])
        Transaction.objects.update(status=TransactionStatus.REALIZED)
        self.assertIsNotNone(self.cards('resolved')[0]['closed_at'])

    def test_situation_traffic_light(self):
        from apps.dunning.services import situations_service
        from apps.legal.models import CollectionCase
        Config.objects.update(critical_days=30)
        situation = lambda: situations_service(user=self.admin)[self.client_.pk]  # noqa: E731
        tx = self.installment(dt.date(2026, 12, 10))  # not due yet
        self.assertEqual(situation(), 'ok')
        tx.date = dt.date(2026, 11, 10)
        tx.save()
        self.assertEqual(situation(), 'attention')
        self.assertEqual(self.api('get', f'/contact/{self.client_.pk}/summary').json()['situation'], 'attention')
        tx.date = dt.date(2026, 10, 10)  # 41 days late
        tx.save()
        self.assertEqual(situation(), 'critical')
        tx.date = dt.date(2026, 11, 10)
        tx.save()
        card = self.cards()[0]
        self.assertFalse(card['critical'])
        Stage.objects.filter(pk=card['stage_id']).update(severity='critical')
        self.assertEqual(situation(), 'critical')
        self.assertTrue(self.cards()[0]['critical'])
        Stage.objects.update(severity='attention')
        CollectionCase.objects.create(company=self.company, contact=self.client_)
        self.assertEqual(situation(), 'critical')
        listed = {c['id']: c['situation'] for c in self.api('get', '/contact').json()}
        self.assertEqual(listed[self.client_.pk], 'critical')
        self.assertEqual(len(self.api('get', f'/dunning/card?contact_id={self.client_.pk}').json()), 1)
        self.assertEqual(self.api('get', f'/dunning/card?contact_id={self.client_.pk + 999}').json(), [])
        self.assertEqual(len(self.api('get', f'/dunning/card?outcome=all&contact_id={self.client_.pk}').json()), 1)
        body = {'start_date': None, 'critical_days': 30, 'attention_days': 5, 'legal_critical': False}
        self.assertEqual(self.api('put', '/dunning/config', body).status_code, 200)
        self.assertEqual(situation(), 'attention')  # legal case now yellow
        self.assertEqual(self.api('put', '/dunning/config', {**body, 'attention_days': 31}).status_code, 400)

    def test_unrecoverable_is_a_separate_mark(self):
        from apps.legal.models import CollectionCase
        case = CollectionCase.objects.create(company=self.company, contact=self.client_)
        r = self.api('patch', f'/collection-case/{case.pk}', {'unrecoverable': True})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['unrecoverable_at'], r.json()['unrecoverable_by_name'], r.json()['stage_name']),
                         ('2026-11-20', 'admin@test.com', 'Nova Ação'))
        r = self.api('patch', f'/collection-case/{case.pk}', {'unrecoverable': False})
        self.assertIsNone(r.json()['unrecoverable_at'])
