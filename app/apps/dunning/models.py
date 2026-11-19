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


class StageKind(models.TextChoices):
    OPEN = 'open', 'Em andamento'
    RESOLVED = 'resolved', 'Resolvido'  # closes the card; only when nothing is overdue
    LEGAL = 'legal', 'Jurídico'  # closes the card and opens a legal case


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Stage(models.Model):
    """Configurable funnel column. New cards enter the first 'open' one."""

    name = models.CharField(max_length=60)
    position = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=StageKind.choices, default=StageKind.OPEN)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.ATTENTION)  # open stages

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name


class ActivityKind(models.TextChoices):
    MESSAGE = 'message', 'Mensagem'
    CALL = 'call', 'Ligação'
    TASK = 'task', 'Tarefa'


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class CadenceStep(models.Model):
    """Activity created on each new card, on the `day`-th day late.
    Template placeholders: {cliente} {empresa} {valor} {parcelas} {vencimento} {dias}."""

    day = models.PositiveSmallIntegerField()
    kind = models.CharField(max_length=10, choices=ActivityKind.choices)
    title = models.CharField(max_length=120)
    template = models.TextField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['day', 'id']


@pghistory.track(pghistory.InsertEvent(), pghistory.UpdateEvent(), pghistory.DeleteEvent())
class Card(models.Model):
    company = models.ForeignKey('companies.Company', on_delete=models.PROTECT, related_name='dunning_cards')
    contact = models.ForeignKey('finance.Contact', on_delete=models.PROTECT, related_name='dunning_cards')
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name='cards')
    assignee = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    overdue_since = models.DateField()  # oldest overdue due date when the card opened
    closed_at = models.DateField(null=True, blank=True)  # resolved or sent to legal
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
    kind = models.CharField(max_length=10, choices=ActivityKind.choices)
    title = models.CharField(max_length=120)
    message = models.TextField(blank=True)
    due_date = models.DateField()
    done_at = models.DateTimeField(null=True, blank=True)
    done_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    answered = models.BooleanField(null=True, blank=True)  # did the customer answer? (no answer = "sem retorno")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'id']


class Config(models.Model):
    """Single row. Installments due before `start_date` stay out of the funnel (old backlog)."""

    start_date = models.DateField(null=True, blank=True)
    critical_days = models.PositiveSmallIntegerField(default=30)  # late this long = red

    @classmethod
    def get(cls) -> 'Config':
        return cls.objects.get_or_create(pk=1)[0]
