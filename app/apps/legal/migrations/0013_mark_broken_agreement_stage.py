from django.db import migrations


def mark(apps, schema_editor):
    apps.get_model('legal', 'LegalStage').objects.filter(name__icontains='descumprido').update(breaks_agreement=True)


class Migration(migrations.Migration):
    dependencies = [('legal', '0012_stage_breaks_agreement')]
    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
