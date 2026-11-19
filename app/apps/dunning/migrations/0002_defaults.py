from django.db import migrations

STAGES = [  # PDF 10.1
    ('Nova pendência', 'open'), ('Em cobrança', 'open'), ('Em negociação', 'open'),
    ('Acordo realizado', 'open'), ('Aguardando pagamento', 'open'),
    ('Resolvido', 'resolved'), ('Encaminhado ao jurídico', 'legal'),
]
FIRST = ('Olá, {cliente}! Tudo bem? Identificamos que a parcela de {valor} com vencimento em {vencimento} '
         'ainda está em aberto. Pode nos confirmar a previsão de pagamento?')
SECOND = ('Olá, {cliente}. Retomando nosso contato: há {parcelas} parcela(s) em aberto, total de {valor}, '
          'vencida(s) há {dias} dia(s). Podemos ajudar com uma forma de pagamento?')
STEPS = [  # PDF 10.3
    (1, 'message', 'Enviar mensagem inicial', FIRST),
    (3, 'call', 'Tentativas de ligação', ''),
    (4, 'message', 'Enviar segunda mensagem', SECOND),
    (5, 'call', 'Novo contato', ''),
]


def seed(apps, schema_editor):
    Stage = apps.get_model('dunning', 'Stage')
    CadenceStep = apps.get_model('dunning', 'CadenceStep')
    for i, (name, kind) in enumerate(STAGES):
        Stage.objects.create(name=name, kind=kind, position=i)
    for day, kind, title, template in STEPS:
        CadenceStep.objects.create(day=day, kind=kind, title=title, template=template)


class Migration(migrations.Migration):
    dependencies = [('dunning', '0001_initial')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
