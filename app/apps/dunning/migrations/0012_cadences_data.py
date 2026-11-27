from django.db.models import Min
from django.db import migrations
from django.utils import timezone


def forward(apps, schema_editor):
    """The single day-based cadence becomes the cadence of the stage that started it ("Em cobrança"): steps in day
    order, each one `interval_days` after the previous. Open cards in that stage keep running it."""
    Stage, Cadence = apps.get_model('dunning', 'Stage'), apps.get_model('dunning', 'Cadence')
    Step, Card, Activity = apps.get_model('dunning', 'CadenceStep'), apps.get_model('dunning', 'Card'), apps.get_model('dunning', 'Activity')
    StepEvent = apps.get_model('dunning', 'CadenceStepEvent')
    steps = list(Step.objects.order_by('day', 'id'))
    stage = (Stage.objects.filter(starts_cadence=True).order_by('position', 'id').first()
             or Stage.objects.filter(name__iexact='Em cobrança').first() or Stage.objects.order_by('position', 'id').first())
    if not steps or stage is None:
        Step.objects.all().delete()  # nothing to attach them to (the column becomes required next)
        StepEvent.objects.all().delete()
        return
    cadence = Cadence.objects.create(name='Cadência de cobrança', stage=stage)
    previous = 1
    for i, step in enumerate(steps):
        step.cadence, step.position, step.interval_days = cadence, i, max((step.day or 1) - previous, 0)
        previous = step.day or previous
        step.save(update_fields=['cadence', 'position', 'interval_days'])
    StepEvent.objects.filter(cadence__isnull=True).update(cadence=cadence)  # audit rows of the old steps
    for card in Card.objects.filter(closed_at__isnull=True, stage=stage):
        started = Activity.objects.filter(card=card, step__isnull=False).aggregate(m=Min('created_at'))['m']
        card.cadence, card.cadence_started_at = cadence, started or timezone.now()
        card.save(update_fields=['cadence', 'cadence_started_at'])


class Migration(migrations.Migration):
    dependencies = [('dunning', '0011_cadences')]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
