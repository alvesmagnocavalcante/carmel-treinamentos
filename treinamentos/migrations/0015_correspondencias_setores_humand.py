import unicodedata

from django.db import migrations

# Nome do setor na Humand -> código do setor no portal. Pode ser ajustado depois em Admin → Correspondências Humand.
# Setores da Humand sem equivalente no portal (Comercial, Administração, Financeiro, TI...) ficam de fora de propósito.
SETORES = {
    "Bar e Restaurante": "alimentos_bebidas",
    "Cozinha": "alimentos_bebidas",
    "Governança": "governanca",
    "Recepção": "recepcao",
    "Portaria": "recepcao",
    "Reservas": "recepcao",
    "Manutenção": "manutencao",
    "Recursos Humanos": "rh",
    "Setor pessoal": "rh",
}


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().casefold()


def seed(apps, schema_editor):
    Department = apps.get_model("treinamentos", "Department")
    HumandAlias = apps.get_model("treinamentos", "HumandAlias")
    for name, code in SETORES.items():
        department = Department.objects.filter(code=code).first()
        if department:  # setor que não existe neste banco é simplesmente pulado
            # get_or_create: não sobrescreve o que o painel já tiver ajustado
            HumandAlias.objects.get_or_create(name_key=key(name), defaults={"name": name, "department": department})


class Migration(migrations.Migration):

    dependencies = [
        ("treinamentos", "0014_cadastro_humand"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
