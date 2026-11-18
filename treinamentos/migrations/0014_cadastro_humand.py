import django.db.models.deletion
from django.db import migrations, models

# Nomes da Humand que não são iguais aos do portal: 'CM' e 'Magna' são o resort Magna/CM.
ALIASES = [("CM", "magna-cm"), ("Magna", "magna-cm")]


def seed_aliases(apps, schema_editor):
    Resort = apps.get_model("treinamentos", "Resort")
    HumandAlias = apps.get_model("treinamentos", "HumandAlias")
    import unicodedata
    for name, code in ALIASES:
        resort = Resort.objects.filter(code=code).first()
        if resort:
            key = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().casefold()
            HumandAlias.objects.get_or_create(name_key=key, defaults={"name": name, "resort": resort})


class Migration(migrations.Migration):

    dependencies = [
        ('treinamentos', '0013_imagem_dimensoes'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='cpf_hash',
            field=models.CharField(
                blank=True, editable=False, max_length=64, null=True, unique=True, verbose_name='CPF (hash)',
                help_text='Impressão digital do CPF validado na Humand no cadastro. Impede duas contas para a mesma '
                          'pessoa; o CPF em si não é guardado.'),
        ),
        migrations.CreateModel(
            name='HumandAlias',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, verbose_name='Nome na Humand')),
                ('name_key', models.CharField(editable=False, max_length=150, unique=True)),
                ('department', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='humand_aliases', to='treinamentos.department', verbose_name='Setor do portal')),
                ('resort', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                    related_name='humand_aliases', to='treinamentos.resort', verbose_name='Resort do portal')),
            ],
            options={
                'verbose_name': 'Correspondência com a Humand',
                'verbose_name_plural': 'Correspondências com a Humand',
                'ordering': ['name'],
            },
        ),
        migrations.RunPython(seed_aliases, migrations.RunPython.noop),
    ]
