from django.db import migrations
from django.db.models import Q


def mark(apps, schema_editor):
    """Cases already with an agreement (stage or text): their linked installments are the agreement's."""
    Transaction = apps.get_model('finance', 'Transaction')
    Transaction.objects.filter(
        Q(collection_case__stage__requires_agreement=True) | ~Q(collection_case__agreement=''),
        collection_case__isnull=False,
    ).update(agreement_installment=True)


class Migration(migrations.Migration):
    dependencies = [
        ('finance', '0022_transaction_agreement_installment'),
        ('legal', '0007_claimed_amount_and_config'),
    ]

    operations = [migrations.RunPython(mark, migrations.RunPython.noop)]
