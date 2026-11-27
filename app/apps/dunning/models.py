"""Collection funnel of the finance team (PDF section 10).

A card is one customer of one company with overdue installments: opened automatically on the
first day late, resolved automatically when nothing is overdue anymore. Each new card gets the
activities of the cadence (message on day 1, call on day 3...).
"""

import pghistory
from django.db import models


class Severity(models.TextChoices):
    """Traffic light of PDF section 15 (green = nothing late, not stored)."""

    ATTENTION = 'attention', 'Atenção'
    CRITICAL = 'critical', 'Crítico'


class Outcome(models.TextChoices):
    """Like won/lost on Pipedrive: closed cards leave the board, the filter brings them back."""

    OPEN = 'open', 'Em aberto'
    RESOLVED = 'resolved', 'Resolvido'  # only when nothing is overdue (or paid off: automatic)
    LEGAL = 'legal', 'Jurídico'  # opens a legal case
    RENEGOTIATED = 'renegotiated', 'Renegociado'  # open installments replaced by new terms
    DISMISSED = 'dismissed', 'Excluído'  # hidden; the customer comes back only with a newer late installment


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Stage(models.Model):
    """Configurable funnel column. New cards enter the first one."""

    name = models.CharField(max_length=60)
    position = models.PositiveSmallIntegerField(default=0)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.ATTENTION)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name


class ActivityKind(models.TextChoices):
    MESSAGE = 'message', 'Mensagem'
    CALL = 'call', 'Ligação'
    TASK = 'task', 'Tarefa'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Cadence(models.Model):
    """Activities a card gets while in `stage`, one at a time: each step is created when the previous one is done
    (the 1st when the card enters the stage). Moving to another stage stops it; coming back restarts it."""

    name = models.CharField(max_length=80)
    stage = models.OneToOneField(Stage, on_delete=models.CASCADE, related_name='cadence')
    skip_weekends = models.BooleanField(default=True)  # due dates move to Monday
    skip_holidays = models.BooleanField(default=True)  # national holidays + Carnival and Corpus Christi
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['stage__position', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class CadenceStep(models.Model):
    """Placeholders in `template`: see TEMPLATE_VARIABLES in the frontend ({primeiro_nome}, {valor}, {link}...)."""

    cadence = models.ForeignKey(Cadence, on_delete=models.CASCADE, related_name='steps')
    position = models.PositiveSmallIntegerField(default=0)
    interval_days = models.PositiveSmallIntegerField(default=0)  # after the previous step was done (1st: after entering)
    kind = models.CharField(max_length=10, choices=ActivityKind.choices)
    title = models.CharField(max_length=120)
    template = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['position', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Card(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='dunning_cards')
    contact = models.ForeignKey('finance.Contact', on_delete=models.PROTECT, related_name='dunning_cards')
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name='cards')
    assignee = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    overdue_since = models.DateField()  # oldest overdue due date when the card opened
    cadence = models.ForeignKey(Cadence, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')  # running now
    cadence_started_at = models.DateTimeField(null=True, blank=True)  # this run's steps: created from then on
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.OPEN)
    closed_at = models.DateField(null=True, blank=True)  # when the outcome was set
    legal_case = models.ForeignKey('legal.CollectionCase', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['overdue_since', 'id']
        constraints = [models.UniqueConstraint(
            'company', 'contact', condition=models.Q(closed_at__isnull=True), name='unique_open_dunning_card',
        )]


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Activity(models.Model):
    """To-do of a card (the card's assignee does it). `message` is the template copied at creation."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='activities')
    step = models.ForeignKey(CadenceStep, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')  # null = by hand
    kind = models.CharField(max_length=10, choices=ActivityKind.choices)
    title = models.CharField(max_length=120)
    message = models.TextField(blank=True)
    due_date = models.DateField()
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    answered = models.BooleanField(null=True, blank=True)  # did the customer answer? (no answer = "sem retorno")
    skipped = models.BooleanField(default=False)  # cadence step deleted by hand: hidden, and not created again
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class CardNote(models.Model):
    """Team notes on a card."""

    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name='notes')
    author = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class Config(models.Model):
    """Single row. Installments due before `start_date` stay out of the funnel (old backlog)."""

    start_date = models.DateField(null=True, blank=True)
    critical_days = models.PositiveSmallIntegerField(default=30)  # late this long = red
    attention_days = models.PositiveSmallIntegerField(default=1)  # late this long = yellow
    legal_critical = models.BooleanField(default=True)  # open legal case = red

    @classmethod
    def get(cls) -> 'Config':
        return cls.objects.get_or_create(pk=1)[0]
