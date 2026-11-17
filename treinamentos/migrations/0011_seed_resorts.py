from django.db import migrations

RESORTS = [
    ("magna-cm", "Magna/CM"),
    ("charme", "Charme"),
    ("wind", "Wind"),
    ("taiba", "Taiba"),
    ("icaraizinho", "Icaraizinho"),
]


def create_resorts(apps, schema_editor):
    Resort = apps.get_model("treinamentos", "Resort")
    for order, (code, name) in enumerate(RESORTS, start=1):
        # get_or_create: rodar de novo não duplica nem desfaz ajustes feitos no painel
        Resort.objects.get_or_create(code=code, defaults={"name": name, "order": order})


class Migration(migrations.Migration):

    dependencies = [
        ("treinamentos", "0010_resorts"),
    ]

    operations = [
        # sem reverso: desfazer a migração anterior já apaga a tabela
        migrations.RunPython(create_resorts, migrations.RunPython.noop),
    ]
