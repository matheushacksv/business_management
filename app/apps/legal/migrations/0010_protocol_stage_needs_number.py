from django.db import migrations


def mark(apps, schema_editor):
    apps.get_model('legal', 'LegalStage').objects.filter(name='Ação Protocolada').update(requires_process_number=True)


class Migration(migrations.Migration):
    dependencies = [('legal', '0009_process_number')]
    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
