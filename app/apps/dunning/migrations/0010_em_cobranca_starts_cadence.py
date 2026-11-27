from django.db import migrations


def mark(apps, schema_editor):
    """The cadence starts when the card is moved to "Em cobrança" (first stage if there is none by that name)."""
    Stage = apps.get_model('dunning', 'Stage')
    stage = Stage.objects.filter(name__iexact='Em cobrança').first() or Stage.objects.order_by('position', 'id').first()
    if stage:
        Stage.objects.filter(pk=stage.pk).update(starts_cadence=True)
        # open cards still before it: their cadence waits for the move (steps already created stay, not repeated)
        apps.get_model('dunning', 'Card').objects.filter(closed_at__isnull=True, stage__position__lt=stage.position) \
            .update(cadence_start=None)


class Migration(migrations.Migration):
    dependencies = [('dunning', '0009_cadence_by_stage')]
    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
