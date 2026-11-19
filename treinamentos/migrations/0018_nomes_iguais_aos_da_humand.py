import unicodedata

from django.db import migrations

# Deixa resorts e RH com os mesmos nomes da Humand, para ligarem sozinhos (sem tabela de correspondências).
# Ninguém perde acesso: quem via o resort "Magna/CM" passa a ver "CM" e "Magna" (o administrador ajusta depois).


def key(name):
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().strip().casefold()


def apply(apps, schema_editor):
    Department = apps.get_model("treinamentos", "Department")
    Resort = apps.get_model("treinamentos", "Resort")
    HumandAlias = apps.get_model("treinamentos", "HumandAlias")
    UserProfile = apps.get_model("treinamentos", "UserProfile")
    TrainingVideo = apps.get_model("treinamentos", "TrainingVideo")

    Department.objects.filter(code="rh").update(name="Recursos Humanos")  # só o nome: pasta do Drive e dados intactos
    Resort.objects.filter(code="taiba").update(name="Taíba")

    both = Resort.objects.filter(code="magna-cm").first()
    if both is not None and not Resort.objects.filter(code="cm").exists():
        both.name, both.code = "CM", "cm"
        both.save(update_fields=["name", "code"])
        magna, _ = Resort.objects.get_or_create(code="magna", defaults={"name": "Magna", "order": both.order, "active": both.active})
        for profile in UserProfile.objects.filter(resorts=both):
            profile.resorts.add(magna)
        for video in TrainingVideo.objects.filter(resorts=both):
            video.resorts.add(magna)

    # os nomes agora são iguais: as correspondências antigas deixam de ser necessárias
    HumandAlias.objects.filter(name_key__in=[key("CM"), key("Magna"), key("Recursos Humanos")]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("treinamentos", "0017_funcao_e_dados_escolhidos"),
    ]

    operations = [
        migrations.RunPython(apply, migrations.RunPython.noop),
    ]
