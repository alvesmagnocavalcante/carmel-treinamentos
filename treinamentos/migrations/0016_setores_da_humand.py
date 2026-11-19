import unicodedata

from django.db import migrations
from django.utils.text import slugify

# Os setores do portal passam a ter os mesmos nomes da Humand (e das pastas do Drive), para ligarem sozinhos no cadastro.
# O RH (código "rh") não é tocado: já está configurado.
HUMAND_SECTORS = [
    "Administração", "Almoxarifado", "Bar e Restaurante", "Comercial", "Compras", "Contabilidade", "Controladoria",
    "Cozinha", "Financeiro", "Governança", "Logística", "Manutenção", "Marketing", "Portaria", "Qualidade",
    "Recepção", "Reservas", "RM", "Setor pessoal", "Tecnologia da Informação",
]
# Setores que já existem (do seed) e só mudam de nome, mantendo vídeos, pessoas e pasta do Drive: código -> nome novo.
RENAME = {"governanca": "Governança", "recepcao": "Recepção", "manutencao": "Manutenção"}
# Ligações antigas (migração 0015) que agora são desnecessárias ou erradas: cada um desses nomes tem setor próprio.
OBSOLETE_ALIASES = ["Bar e Restaurante", "Cozinha", "Governança", "Recepção", "Portaria", "Reservas", "Manutenção",
                    "Setor pessoal"]


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().casefold()


def is_empty(department):
    return not (department.videos.exists() or department.members.exists() or department.drive_folder_id)


def apply(apps, schema_editor):
    Department = apps.get_model("treinamentos", "Department")
    HumandAlias = apps.get_model("treinamentos", "HumandAlias")
    rh = Department.objects.filter(code="rh").first()
    if rh is None:
        return  # banco novo, sem os setores do seed: nada a ajustar (o seed_carmel já cria a lista nova)

    for code, name in RENAME.items():
        Department.objects.filter(code=code).update(name=name)

    # "Alimentos & Bebidas" vira "Bar e Restaurante" (a Humand separa em Bar e Restaurante / Cozinha), mantendo os dados
    food = Department.objects.filter(code="alimentos_bebidas").first()
    if food and not Department.objects.filter(code="bar-e-restaurante").exists():
        food.name, food.code = "Bar e Restaurante", "bar-e-restaurante"
        food.save(update_fields=["name", "code"])

    # "Lazer & Experiências" não existe na Humand: sai só se estiver vazio (sem vídeos, pessoas nem pasta)
    leisure = Department.objects.filter(code="experiencias").first()
    if leisure and is_empty(leisure):
        leisure.delete()

    for name in HUMAND_SECTORS:
        # se já existe um setor com esse nome (de qualquer código), não cria outro
        exists = any(key(d.name) == key(name) for d in Department.objects.all())
        if not exists:
            Department.objects.create(code=slugify(name), name=name)

    HumandAlias.objects.filter(name_key__in=[key(n) for n in OBSOLETE_ALIASES]).delete()
    # o RH tem nome diferente na Humand ("Recursos Humanos"): continua ligado por correspondência
    HumandAlias.objects.get_or_create(name_key=key("Recursos Humanos"), defaults={"name": "Recursos Humanos", "department": rh})


class Migration(migrations.Migration):

    dependencies = [
        ("treinamentos", "0015_correspondencias_setores_humand"),
    ]

    operations = [
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
