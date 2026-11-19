import unicodedata

from django.db import migrations


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().casefold()


def apply(apps, schema_editor):
    """Na Humand o grupo 'Carmel Cumbuco' é o resort Wind."""
    Resort = apps.get_model("treinamentos", "Resort")
    HumandAlias = apps.get_model("treinamentos", "HumandAlias")
    wind = Resort.objects.filter(code="wind").first()
    if wind is not None:
        HumandAlias.objects.get_or_create(name_key=key("Cumbuco"), defaults={"name": "Cumbuco", "resort": wind})


class Migration(migrations.Migration):

    dependencies = [
        ("treinamentos", "0018_nomes_iguais_aos_da_humand"),
    ]

    operations = [
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
