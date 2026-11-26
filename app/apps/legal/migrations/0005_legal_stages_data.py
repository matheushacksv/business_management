from django.db import migrations


STAGES = [  # the former fixed stages: (code, name, requires_agreement, requires_checklist)
    ('new', 'Nova Ação', False, False),
    ('stand_by', 'Stand By', False, False),
    ('requested', 'Solicitada ao Jurídico', False, False),
    ('filed', 'Ação Protocolada', False, True),
    ('in_progress', 'Em andamento', False, True),
    ('agreement', 'Acordo ou Sentença', True, True),
    ('awaiting_judge', 'Aguardando Juiz', False, True),
]


def seed(apps, schema_editor):
    Stage = apps.get_model('legal', 'LegalStage')
    Case = apps.get_model('legal', 'CollectionCase')
    by_code = {code: Stage.objects.create(name=name, position=i, requires_agreement=agreement, requires_checklist=checklist)
               for i, (code, name, agreement, checklist) in enumerate(STAGES)}
    Event = apps.get_model('legal', 'CollectionCaseEvent')
    for code, stage in {**by_code, 'done': by_code['awaiting_judge']}.items():
        Case.objects.filter(stage=code).update(stage_new=stage)
        Event.objects.filter(stage=code).update(stage_new=stage)  # audit history keeps its stages
    # "Concluída" is no longer a stage: concluded date + last column (the real previous stage was not kept)
    for case in Case.objects.filter(stage='done'):  # already moved to the last column above
        Case.objects.filter(pk=case.pk).update(closed_at=case.updated_at.date())



class Migration(migrations.Migration):
    """Own migration: Postgres refuses ALTER TABLE / CREATE INDEX after updating rows in the same transaction."""

    dependencies = [
        ('legal', '0004_legal_stages'),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
