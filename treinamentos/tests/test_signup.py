"""Cadastro por CPF + nascimento validado na Humand (simulada: nenhum teste chama a API real)."""

import httpx
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from ..models import HumandAlias, Resort, UserProfile
from ..services import humand
from .base import BaseTestCase

CPF = "529.982.247-25"  # CPF válido de exemplo (dígitos verificadores corretos)
CPF_DIGITS = "52998224725"
SIGNUP_KEY = "signup_person"
REAL_POSITION_MAP = humand.position_map
REAL_POSITION_NAMES = humand.position_names
REAL_GET = humand._get  # a consulta de verdade; cada FakeHumand a troca por uma com respostas prontas


def person(**extra):
    data = {
        "id": 1, "employeeInternalId": CPF_DIGITS, "firstName": "Maria", "lastName": "da Silva",
        "email": "maria@carmel.com", "birthdate": "1990-05-17", "status": "ACTIVE", "deleted": False,
        "segmentations": [{"group": "Carmel Taíba", "item": "Governança"}, {"group": "Hotéis", "item": "Taíba"}],
    }
    data.update(extra)
    return data


from contextlib import contextmanager


@contextmanager
def override_env(**values):
    """Define variáveis de ambiente só durante o bloco."""
    import os
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class FakeHumand:
    """
    Troca a consulta HTTP por respostas prontas e registra o que foi pedido (só GET).
    `payload`/`status` respondem a /users/{cpf}; `positions` é {nome do cargo: [CPFs]} para /job-positions.
    """

    def __init__(self, test, payload=None, status=200, positions=None):
        self.requests = []
        self.positions = positions or {}
        ids = {name: str(n) for n, name in enumerate(self.positions, start=1)}

        def handler(request):
            self.requests.append(request)
            path = request.url.path.removeprefix("/api")
            if path == "/job-positions":
                items = [{"id": ids[n], "name": n, "usersCount": len(c)} for n, c in self.positions.items()]
                return httpx.Response(200, json={"items": items, "totalPages": 1})
            if path.startswith("/job-positions/"):
                name = next(n for n, i in ids.items() if i == path.split("/")[2])
                return httpx.Response(200, json={"items": [{"employeeInternalId": c} for c in self.positions[name]],
                                                 "totalPages": 1})
            return httpx.Response(status, json=payload if payload is not None else {})

        self.transport = httpx.MockTransport(handler)
        test.enterContext(override_settings(HUMAND_API_KEY="chave-teste", HUMAND_BASE_URL="https://humand.test/api"))
        cache.clear()
        humand._get = lambda path, params=None, transport=None: REAL_GET(path, params, self.transport)
        test.addCleanup(setattr, humand, "_get", REAL_GET)


class HumandServiceTests(SimpleTestCase):
    def test_cpf_validation(self):
        self.assertEqual(humand.clean_cpf(CPF), CPF_DIGITS)
        for bad in ("", "123", "11111111111", "52998224726", "abc"):
            self.assertIsNone(humand.clean_cpf(bad))

    def test_birthdate_parsing(self):
        self.assertEqual(humand.parse_birthdate("17/05/1990").isoformat(), "1990-05-17")
        self.assertEqual(humand.parse_birthdate("17051990").isoformat(), "1990-05-17")
        for bad in ("", "31/02/1990", "17/05/2999", "x"):
            self.assertIsNone(humand.parse_birthdate(bad))

    def test_hash_hides_the_cpf_and_is_stable(self):
        self.assertNotIn(CPF_DIGITS, humand.cpf_hash(CPF_DIGITS))
        self.assertEqual(humand.cpf_hash(CPF_DIGITS), humand.cpf_hash(CPF_DIGITS))

    def test_segmentations_split_resorts_from_departments(self):
        resorts, departments = humand.split_segmentations([
            {"group": "Hotéis", "item": "Wind"}, {"group": "Carmel Taíba", "item": "Cozinha"},
            {"group": "Gestores/ Líderes", "item": "CM"}, {"group": "CM", "item": ""}, "lixo"])
        self.assertEqual((resorts, departments), (["Wind"], ["Cozinha"]))


class SignupTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.taiba = Resort.objects.get(code="taiba")
        self.gov.name = "Governança"
        self.gov.save()

    def identify(self, **extra):
        data = {"cpf": CPF, "birthdate": "17/05/1990", "website": ""}
        data.update(extra)
        return self.client.post(reverse("signup"), data)

    def finish(self, password="segredo123", password2=None):
        return self.client.post(reverse("signup_confirm"),
                                {"password": password, "password2": password2 or password})

    def register(self):
        self.identify()
        return self.finish()

    # ---- fluxo feliz ----
    def test_step_one_shows_the_humand_data_and_creates_nothing_yet(self):
        FakeHumand(self, person(), positions={"ELETRICISTA": [CPF_DIGITS], "GERENTE": ["99999999999"]})
        resp = self.identify()
        self.assertRedirects(resp, reverse("signup_confirm"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())
        page = self.client.get(reverse("signup_confirm")).content.decode()
        for expected in ("Maria da Silva", "ELETRICISTA", "Governança", "Taíba"):
            self.assertIn(expected, page)
        self.assertNotIn(CPF_DIGITS, page)       # o CPF não volta para a tela
        self.assertNotIn("maria@carmel.com", page)  # só o essencial: sem e-mail, nascimento, telefone

    def test_confirming_creates_the_account_with_cpf_as_login(self):
        FakeHumand(self, person())
        self.identify()
        resp = self.finish()
        self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False)
        user = User.objects.get(username=CPF_DIGITS)
        self.assertTrue(user.is_active)
        self.assertEqual((user.first_name, user.last_name, user.email), ("Maria", "da Silva", "maria@carmel.com"))
        self.assertEqual(user.profile.role, UserProfile.ROLE_COLABORADOR)
        self.assertEqual(user.profile.department, self.gov)
        self.assertEqual(list(user.profile.resorts.all()), [self.taiba])
        self.assertEqual(self.client.session["_auth_user_id"], str(user.id))
        self.assertNotIn(CPF_DIGITS, user.profile.cpf_hash)
        self.assertNotIn(SIGNUP_KEY, self.client.session)  # dados da Humand saem da sessão

    def test_login_accepts_the_cpf_with_or_without_punctuation(self):
        FakeHumand(self, person())
        self.register()
        self.client.logout()
        for typed in (CPF, CPF_DIGITS, f"  {CPF} "):
            resp = self.client.post(reverse("login"), {"username": typed, "password": "segredo123"})
            self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False, msg_prefix=typed)
            self.client.logout()
        resp = self.client.post(reverse("login"), {"username": CPF, "password": "errada"})
        self.assertContains(resp, "inválidos")

    def test_old_usernames_still_log_in(self):
        resp = self.client.post(reverse("login"), {"username": "colab", "password": "x123456"})
        self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False)

    def test_position_is_optional(self):
        FakeHumand(self, person(), positions={"GERENTE": ["99999999999"]})  # o cargo dela não está em nenhuma lista
        self.identify()
        self.assertContains(self.client.get(reverse("signup_confirm")), 'name="position"')  # pode escolher...
        self.assertRedirects(self.finish(), reverse("home"), fetch_redirect_response=False)  # ...ou deixar em branco
        self.assertEqual(User.objects.get(username=CPF_DIGITS).profile.position, "")

    def test_only_reads_the_humand_never_writes(self):
        fake = FakeHumand(self, person(), positions={"GERENTE": [CPF_DIGITS]})
        self.register()
        self.assertEqual({r.method for r in fake.requests}, {"GET"})
        self.assertEqual(fake.requests[0].url.path, f"/api/users/{CPF_DIGITS}")
        self.assertTrue(all(r.headers["Authorization"] == "Basic chave-teste" for r in fake.requests))

    def test_positions_are_looked_up_once_and_kept_for_the_next_signups(self):
        fake = FakeHumand(self, person(), positions={"GERENTE": [CPF_DIGITS]})
        self.identify()
        first = len(fake.requests)
        self.assertIn("/api/job-positions", [r.url.path for r in fake.requests])
        humand.position_map()  # a segunda consulta vem da memória, sem ir à Humand de novo
        self.assertEqual(len(fake.requests), first)

    def test_failure_to_read_positions_does_not_block_the_signup(self):
        FakeHumand(self, person())
        humand.position_map = lambda: (_ for _ in ()).throw(humand.HumandUnavailable("fora do ar"))
        self.addCleanup(setattr, humand, "position_map", REAL_POSITION_MAP)
        self.identify()
        self.assertNotContains(self.client.get(reverse("signup_confirm")), "Função")
        self.assertRedirects(self.finish(), reverse("home"), fetch_redirect_response=False)

    def test_aliases_link_humand_names_that_differ(self):
        magna = Resort.objects.get(code="magna-cm")
        self.assertTrue(HumandAlias.objects.filter(resort=magna, name="CM").exists())  # já vem da migração
        HumandAlias.objects.create(name="Governança Taíba", department=self.rh)
        FakeHumand(self, person(segmentations=[
            {"group": "Hotéis", "item": "CM"}, {"group": "Hotéis", "item": "Magna"},
            {"group": "Carmel Taíba", "item": "Governança Taíba"}]))
        self.register()
        profile = User.objects.get(username=CPF_DIGITS).profile
        self.assertEqual(list(profile.resorts.all()), [magna])
        self.assertEqual(profile.department, self.rh)

    def test_new_collaborator_lands_on_the_catalog_of_their_own_sector(self):
        from ..models import TrainingVideo
        TrainingVideo.objects.filter(department=self.gov).update(title="Vídeo da Governança")
        FakeHumand(self, person(segmentations=[{"group": "Hotéis", "item": "Taíba"},
                                               {"group": "Carmel Taíba", "item": "Governança"}]))
        self.register()
        page = self.client.get(reverse("home")).content.decode()
        self.assertIn("Vídeo da Governança", page)  # o do setor dele
        self.assertNotIn("Vídeo RH", page)          # e só ele

    def test_humand_sector_with_the_same_name_links_by_itself(self):
        from ..models import Department
        cozinha = Department.objects.create(code="cozinha", name="Cozinha")
        FakeHumand(self, person(segmentations=[{"group": "Carmel Taíba", "item": "Cozinha"},
                                               {"group": "Hotéis", "item": "Taíba"}]))
        self.register()
        self.assertEqual(User.objects.get(username=CPF_DIGITS).profile.department, cozinha)

    def test_unknown_department_makes_the_person_choose_it(self):
        FakeHumand(self, person(segmentations=[{"group": "Hotéis", "item": "Taíba"}, {"group": "X", "item": "Setor Novo"}]))
        self.identify()
        page = self.client.get(reverse("signup_confirm")).content.decode()
        self.assertIn('name="department"', page)   # o setor da Humand não existe no portal: ela escolhe
        self.assertNotIn("Setor Novo", page)
        self.assertEqual(self.finish().status_code, 200)  # sem escolher, não conclui
        resp = self.client.post(reverse("signup_confirm"),
                                {"password": "segredo123", "password2": "segredo123", "department": self.gov.id})
        self.assertEqual(resp.status_code, 302)
        profile = User.objects.get(username=CPF_DIGITS).profile
        self.assertEqual(profile.department, self.gov)
        self.assertEqual(list(profile.resorts.all()), [self.taiba])  # o resort veio da Humand

    # ---- recusas ----
    def test_wrong_birthdate_inactive_deleted_and_unknown_are_all_the_same_refusal(self):
        cases = [(person(), {"birthdate": "01/01/2000"}, 200), (person(status="INACTIVE"), {}, 200),
                 (person(deleted=True), {}, 200), ({}, {}, 404)]
        for payload, extra, status in cases:
            cache.clear()
            FakeHumand(self, payload, status=status)
            self.assertContains(self.identify(**extra), "Não foi possível validar seus dados", msg_prefix=str(extra))
            self.assertNotIn(SIGNUP_KEY, self.client.session)
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())

    def test_invalid_cpf_or_date_never_reach_the_humand(self):
        fake = FakeHumand(self, person())
        self.assertContains(self.identify(cpf="111.111.111-11"), "CPF inválido")
        self.assertContains(self.identify(birthdate="99/99/9999"), "Data inválida")
        self.assertEqual(fake.requests, [])

    def test_already_registered_cpf_is_refused(self):
        FakeHumand(self, person())
        self.register()
        self.client.logout()
        self.assertContains(self.identify(), "já possui cadastro")

    def test_too_many_wrong_attempts_lock_the_signup(self):
        fake = FakeHumand(self, person())
        for _ in range(5):
            self.identify(birthdate="01/01/2000")
        count = len(fake.requests)
        self.assertContains(self.identify(), "Muitas tentativas")  # até a data certa é recusada
        self.assertEqual(len(fake.requests), count)

    def test_humand_down_is_not_counted_as_the_persons_mistake(self):
        FakeHumand(self, {}, status=500)
        for _ in range(7):
            resp = self.identify()
        self.assertContains(resp, "consultar o cadastro agora")

    def test_password_rules_apply_on_step_two(self):
        FakeHumand(self, person())
        self.identify()
        self.assertContains(self.finish("segredo123", "outra"), "As senhas não são iguais")
        self.assertContains(self.finish("123", "123"), "muito curta")
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())
        self.assertRedirects(self.finish(), reverse("home"), fetch_redirect_response=False)  # ainda dá para corrigir

    def test_step_two_needs_a_validated_step_one(self):
        self.assertRedirects(self.client.get(reverse("signup_confirm")), reverse("signup"), fetch_redirect_response=False)
        resp = self.client.post(reverse("signup_confirm"), {"password": "segredo123", "password2": "segredo123"})
        self.assertRedirects(resp, reverse("signup"), fetch_redirect_response=False)
        self.assertEqual(User.objects.filter(username=CPF_DIGITS).count(), 0)

    def test_step_two_expires(self):
        FakeHumand(self, person())
        self.identify()
        session = self.client.session
        session[SIGNUP_KEY]["at"] -= 16 * 60
        session.save()
        self.assertRedirects(self.finish(), reverse("signup"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())

    def test_honeypot_blocks_robots_and_form_cannot_set_role_or_sector(self):
        FakeHumand(self, person())
        self.assertEqual(self.identify(website="http://spam").status_code, 200)
        self.assertNotIn(SIGNUP_KEY, self.client.session)
        self.identify(role="admin", is_superuser="on", department=self.rh.id)
        self.client.post(reverse("signup_confirm"), {"password": "segredo123", "password2": "segredo123",
                                                     "role": "admin", "is_superuser": "on", "department": self.rh.id})
        user = User.objects.get(username=CPF_DIGITS)
        self.assertEqual(user.profile.role, UserProfile.ROLE_COLABORADOR)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.profile.department, self.gov)  # setor vem da Humand, não do formulário

    def test_password_fields_have_a_show_hide_button(self):
        FakeHumand(self, person())
        self.identify()
        page = self.client.get(reverse("signup_confirm")).content.decode()
        self.assertEqual(page.count("data-pw-toggle"), 2)  # senha e confirmação
        self.assertEqual(page.count('type="password"'), 2)  # começam ocultas
        self.assertIn("password-toggle.js", page)
        with override_settings(HUMAND_API_KEY="k"):
            login = self.client.get(reverse("login")).content.decode()
        self.assertEqual(login.count("data-pw-toggle"), 1)
        self.assertIn("password-toggle.js", login)

    def test_signup_is_off_without_key_or_when_disabled(self):
        for name in ("signup", "signup_confirm"):
            with override_settings(HUMAND_API_KEY=""):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)
            with override_settings(HUMAND_API_KEY="k", SIGNUP_ENABLED=False):
                self.assertEqual(self.client.get(reverse(name)).status_code, 404)
        with override_settings(HUMAND_API_KEY=""):
            self.assertNotContains(self.client.get(reverse("login")), "Criar cadastro")

    def test_pages_render_and_login_asks_for_cpf(self):
        with override_settings(HUMAND_API_KEY="k"):
            self.assertContains(self.client.get(reverse("signup")), 'name="birthdate"')
            login = self.client.get(reverse("login"))
            self.assertContains(login, "Criar cadastro")
            self.assertContains(login, "CPF ou usuário")
            self.assertContains(login, "cpf-mask.js")
            self.assertContains(self.client.get(reverse("signup")), 'maxlength="14"')
            self.client.force_login(self.colab)
            self.assertRedirects(self.client.get(reverse("signup")), reverse("home"), fetch_redirect_response=False)


class MissingDataDropdownTests(BaseTestCase):
    """Quando a Humand não traz setor, resort ou função, a pessoa escolhe em dropdowns e os vídeos já aparecem."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.gov.name = "Governança"
        self.gov.save()
        self.taiba = Resort.objects.get(code="taiba")
        self.wind = Resort.objects.get(code="wind")

    def start(self, segmentations=()):
        FakeHumand(self, person(segmentations=list(segmentations)), positions={"GERENTE": ["99999999999"], "CAMAREIRA": []})
        self.client.post(reverse("signup"), {"cpf": CPF, "birthdate": "17/05/1990", "website": ""})

    def confirm(self, **data):
        return self.client.post(reverse("signup_confirm"),
                                {"password": "segredo123", "password2": "segredo123", **data})

    def test_dropdowns_appear_for_what_the_humand_did_not_bring(self):
        self.start()
        page = self.client.get(reverse("signup_confirm")).content.decode()
        for name in ('name="department"', 'name="resort"', 'name="position"'):
            self.assertIn(name, page)
        self.assertIn("Governança", page)   # opções vindas do portal
        self.assertIn("Wind", page)
        self.assertIn("GERENTE", page)      # opções vindas dos cargos da Humand

    def test_nothing_is_asked_when_the_humand_brought_everything(self):
        FakeHumand(self, person(), positions={"ANALISTA": [CPF_DIGITS]})
        self.client.post(reverse("signup"), {"cpf": CPF, "birthdate": "17/05/1990", "website": ""})
        page = self.client.get(reverse("signup_confirm")).content.decode()
        for name in ('name="department"', 'name="resort"', 'name="position"'):
            self.assertNotIn(name, page)

    def test_only_the_missing_dropdown_appears(self):
        self.start([{"group": "Hotéis", "item": "Taíba"}])  # tem resort, falta setor
        page = self.client.get(reverse("signup_confirm")).content.decode()
        self.assertIn('name="department"', page)
        self.assertNotIn('name="resort"', page)

    def test_chosen_values_give_access_to_that_sectors_videos(self):
        from ..models import TrainingVideo
        TrainingVideo.objects.filter(department=self.gov).update(title="Vídeo da Governança")
        self.start()
        resp = self.confirm(department=self.gov.id, resort=self.wind.id, position="GERENTE")
        self.assertRedirects(resp, reverse("home"), fetch_redirect_response=False)
        profile = User.objects.get(username=CPF_DIGITS).profile
        self.assertEqual((profile.department, list(profile.resorts.all()), profile.position),
                         (self.gov, [self.wind], "GERENTE"))
        self.assertTrue(profile.self_declared)  # marcado para o administrador conferir
        page = self.client.get(reverse("home")).content.decode()
        self.assertIn("Vídeo da Governança", page)
        self.assertNotIn("Vídeo RH", page)

    def test_setor_and_resort_are_required_when_asked_but_position_is_optional(self):
        self.start()
        resp = self.confirm()
        self.assertContains(resp, "Este campo é obrigatório")
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())
        self.assertRedirects(self.confirm(department=self.gov.id, resort=self.wind.id),
                             reverse("home"), fetch_redirect_response=False)

    def test_invalid_choices_are_refused(self):
        self.start()
        self.assertContains(self.confirm(department=99999, resort=self.wind.id), "escolha válida")
        self.assertContains(self.confirm(department=self.gov.id, resort=self.wind.id, position="DIRETOR GERAL INVENTADO"),
                            "escolha válida")
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())

    def test_what_the_humand_brought_cannot_be_overridden_by_the_form(self):
        FakeHumand(self, person(), positions={"ANALISTA": [CPF_DIGITS]})
        self.client.post(reverse("signup"), {"cpf": CPF, "birthdate": "17/05/1990", "website": ""})
        self.confirm(department=self.rh.id, resort=self.wind.id, position="GERENTE")  # tentativa de trocar
        profile = User.objects.get(username=CPF_DIGITS).profile
        self.assertEqual(profile.department, self.gov)                 # vem da Humand (Governança)
        self.assertEqual(list(profile.resorts.all()), [self.taiba])    # vem da Humand (Taíba)
        self.assertEqual(profile.position, "ANALISTA")                 # vem da Humand
        self.assertFalse(profile.self_declared)

    def test_failure_loading_positions_just_hides_that_dropdown(self):
        FakeHumand(self, person(segmentations=[]))
        humand.position_names = lambda: []
        self.addCleanup(setattr, humand, "position_names", REAL_POSITION_NAMES)
        self.client.post(reverse("signup"), {"cpf": CPF, "birthdate": "17/05/1990", "website": ""})
        page = self.client.get(reverse("signup_confirm")).content.decode()
        self.assertNotIn('name="position"', page)
        self.assertIn('name="department"', page)


class SectorsMigrationTests(BaseTestCase):
    """Migração 0016: setores do portal passam a ter os nomes da Humand, sem mexer no RH nem perder dados."""

    def run_migration(self):
        from importlib import import_module
        from django.apps import apps
        import_module("treinamentos.migrations.0016_setores_da_humand").apply(apps, None)

    def setUp(self):
        super().setUp()
        from ..models import Department
        self.rh.name, self.rh.code, self.rh.drive_folder_id = "Recursos Humanos & Cultura", "rh", "pasta-rh"
        self.rh.save()
        self.gov.delete()
        Department.objects.create(code="governanca", name="Governança & Rouparia", drive_folder_id="pasta-gov")
        Department.objects.create(code="alimentos_bebidas", name="Alimentos & Bebidas")
        Department.objects.create(code="experiencias", name="Lazer & Experiências")

    def test_rh_is_untouched_and_existing_sectors_keep_their_data(self):
        from ..models import Department
        self.run_migration()
        rh = Department.objects.get(code="rh")
        self.assertEqual((rh.name, rh.drive_folder_id), ("Recursos Humanos & Cultura", "pasta-rh"))
        gov = Department.objects.get(code="governanca")
        self.assertEqual((gov.name, gov.drive_folder_id), ("Governança", "pasta-gov"))  # só o nome muda

    def test_all_humand_sectors_exist_afterwards_and_the_unused_one_is_gone(self):
        from ..models import Department
        from importlib import import_module
        self.run_migration()
        names = set(Department.objects.values_list("name", flat=True))
        for wanted in import_module("treinamentos.migrations.0016_setores_da_humand").HUMAND_SECTORS:
            self.assertIn(wanted, names)
        self.assertTrue(Department.objects.filter(code="bar-e-restaurante", name="Bar e Restaurante").exists())
        self.assertFalse(Department.objects.filter(code__in=("alimentos_bebidas", "experiencias")).exists())

    def test_sector_with_content_is_never_deleted(self):
        from ..models import Department
        Department.objects.filter(code="experiencias").update(drive_folder_id="pasta-lazer")
        self.run_migration()
        self.assertTrue(Department.objects.filter(code="experiencias").exists())

    def test_old_aliases_go_away_and_rh_stays_linked_to_recursos_humanos(self):
        from ..models import Department
        magna = HumandAlias.objects.filter(resort__isnull=False).count()
        HumandAlias.objects.create(name="Cozinha", department=Department.objects.get(code="governanca"))  # erro antigo
        self.run_migration()
        self.assertFalse(HumandAlias.objects.filter(name="Cozinha").exists())
        self.assertEqual(HumandAlias.objects.get(name="Recursos Humanos").department.code, "rh")
        self.assertEqual(HumandAlias.objects.filter(resort__isnull=False).count(), magna)  # resorts intactos

    def test_running_twice_changes_nothing_more(self):
        from ..models import Department
        self.run_migration()
        total = Department.objects.count()
        self.run_migration()
        self.assertEqual(Department.objects.count(), total)

    def test_fresh_database_without_the_seed_is_left_alone(self):
        from ..models import Department
        Department.objects.all().delete()
        self.run_migration()
        self.assertEqual(Department.objects.count(), 0)


class AdminAccessTests(BaseTestCase):
    """Login por CPF (com ou sem pontuação) vale também no /admin/login/, e promote_admin dá acesso de administrador."""

    def make_person(self, cpf=CPF_DIGITS, **flags):
        user = User.objects.create_user(cpf, password="segredo123", first_name="Maria", **flags)
        return user

    def test_admin_login_accepts_cpf_with_punctuation(self):
        user = self.make_person(is_staff=True, is_superuser=True)
        resp = self.client.post("/admin/login/", {"username": CPF, "password": "segredo123", "next": "/admin/"})
        self.assertRedirects(resp, "/admin/", fetch_redirect_response=False)
        self.assertEqual(self.client.session["_auth_user_id"], str(user.id))

    def test_plain_usernames_still_work_in_both_logins(self):
        self.assertEqual(self.client.post("/admin/login/", {"username": "admin", "password": "x123456"}).status_code, 302)
        self.client.logout()
        self.assertEqual(self.client.post(reverse("login"), {"username": "gestor", "password": "x123456"}).status_code, 302)

    def test_promote_admin_gives_staff_superuser_and_global_role(self):
        from django.core.management import call_command
        user = self.make_person()
        self.assertFalse(user.is_staff)
        call_command("promote_admin", CPF)  # aceita o CPF formatado
        user.refresh_from_db()
        self.assertTrue(user.is_staff and user.is_superuser and user.is_active)
        self.assertEqual(user.profile.role, UserProfile.ROLE_ADMIN)
        self.assertTrue(user.profile.is_global)
        self.client.force_login(user)
        self.assertEqual(self.client.get("/admin/").status_code, 200)

    def test_promote_admin_reads_the_env_var_and_ignores_unknown_people(self):
        from django.core.management import call_command
        user = self.make_person()
        with override_env(ADMIN_LOGINS=f"{CPF}; 00000000000 , colab"):
            call_command("promote_admin")  # quem ainda não existe é só avisado, sem erro
        user.refresh_from_db()
        self.colab.refresh_from_db()
        self.assertTrue(user.is_superuser)
        self.assertTrue(self.colab.is_superuser)   # nome de usuário comum também vale
        self.assertFalse(User.objects.get(username="semsetor").is_staff)  # ninguém além dos citados

    def test_promote_admin_without_arguments_or_env_changes_nothing(self):
        from django.core.management import call_command
        before = list(User.objects.filter(is_staff=True).values_list("id", flat=True))
        with override_env(ADMIN_LOGINS=""):
            call_command("promote_admin")
        self.assertEqual(list(User.objects.filter(is_staff=True).values_list("id", flat=True)), before)

    def test_signup_alone_never_grants_admin(self):
        FakeHumand(self, person())
        self.client.post(reverse("signup"), {"cpf": CPF, "birthdate": "17/05/1990", "website": ""})
        self.client.post(reverse("signup_confirm"), {"password": "segredo123", "password2": "segredo123",
                                                     "department": self.rh.id, "resort": 1})
        user = User.objects.get(username=CPF_DIGITS)
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertEqual(self.client.get("/admin/").status_code, 302)  # vai para o login do admin
