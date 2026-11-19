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
REAL_FETCH = humand._fetch  # a consulta de verdade; cada FakeHumand a troca por uma com respostas prontas


def person(**extra):
    data = {
        "id": 1, "employeeInternalId": CPF_DIGITS, "firstName": "Maria", "lastName": "da Silva",
        "email": "maria@carmel.com", "birthdate": "1990-05-17", "status": "ACTIVE", "deleted": False,
        "fields": [{"id": "2b6041ca-27d0-412d-b385-dda2fd082e7d", "name": None, "value": "Eletricista"}],
        "segmentations": [{"group": "Carmel Taíba", "item": "Governança"}, {"group": "Hotéis", "item": "Taíba"}],
    }
    data.update(extra)
    return data


class FakeHumand:
    """Troca a consulta HTTP por respostas prontas e registra o que foi pedido (só GET)."""

    def __init__(self, test, payload=None, status=200):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx.Response(status, json=payload if payload is not None else {})

        self.transport = httpx.MockTransport(handler)
        test.enterContext(override_settings(HUMAND_API_KEY="chave-teste", HUMAND_BASE_URL="https://humand.test/api"))
        humand._fetch = lambda cpf, transport=None: REAL_FETCH(cpf, self.transport)
        test.addCleanup(setattr, humand, "_fetch", REAL_FETCH)


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
        FakeHumand(self, person())
        resp = self.identify()
        self.assertRedirects(resp, reverse("signup_confirm"), fetch_redirect_response=False)
        self.assertFalse(User.objects.filter(username=CPF_DIGITS).exists())
        page = self.client.get(reverse("signup_confirm")).content.decode()
        for expected in ("Maria da Silva", "Eletricista", "Governança", "Taíba"):
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
        FakeHumand(self, person(fields=[]))
        self.identify()
        self.assertNotContains(self.client.get(reverse("signup_confirm")), "Função")
        self.assertRedirects(self.finish(), reverse("home"), fetch_redirect_response=False)

    def test_only_reads_the_humand_never_writes(self):
        fake = FakeHumand(self, person())
        self.register()
        self.assertEqual([(r.method, r.url.path) for r in fake.requests], [("GET", f"/api/users/{CPF_DIGITS}")])
        self.assertEqual(fake.requests[0].headers["Authorization"], "Basic chave-teste")

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

    def test_humand_sector_names_are_linked_to_portal_sectors_out_of_the_box(self):
        from ..models import Department
        # em banco com os setores do seed, os nomes da Humand já apontam para o setor certo
        for code, name in (("alimentos_bebidas", "Alimentos & Bebidas"), ("recepcao", "Recepção & Concierge")):
            Department.objects.get_or_create(code=code, defaults={"name": name})
        from importlib import import_module
        migration = import_module("treinamentos.migrations.0015_correspondencias_setores_humand")
        from django.apps import apps
        migration.seed(apps, None)
        for humand_name, code in (("Cozinha", "alimentos_bebidas"), ("Portaria", "recepcao"), ("Bar e Restaurante", "alimentos_bebidas")):
            alias = HumandAlias.objects.get(name=humand_name)
            self.assertEqual(alias.department.code, code)
        self.assertFalse(HumandAlias.objects.filter(name="Comercial").exists())  # sem equivalente: de fora

    def test_unknown_department_still_creates_the_account_without_sector(self):
        FakeHumand(self, person(segmentations=[{"group": "Hotéis", "item": "Taíba"}, {"group": "X", "item": "Setor Novo"}]))
        self.assertEqual(self.register().status_code, 302)
        profile = User.objects.get(username=CPF_DIGITS).profile
        self.assertIsNone(profile.department)
        self.assertEqual(list(profile.resorts.all()), [self.taiba])

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
            self.assertContains(login, "<label for=\"username\">CPF</label>")
            self.client.force_login(self.colab)
            self.assertRedirects(self.client.get(reverse("signup")), reverse("home"), fetch_redirect_response=False)
