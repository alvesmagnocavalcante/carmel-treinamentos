from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import IntegrityError, transaction

from .models import UserProfile
from .services import humand

INVALID_DATA = "Não foi possível validar seus dados. Confira o CPF e a data de nascimento."
ALREADY_REGISTERED = "Este CPF já possui cadastro. Entre com o seu CPF e senha."


class IdentifyForm(forms.Form):
    """
    Passo 1 do primeiro acesso: CPF + data de nascimento, conferidos na Humand. O nascimento existe para que só o
    próprio colaborador veja os dados dele (o CPF sozinho não é segredo). Em caso de sucesso, `person` fica preenchida.
    """

    cpf = forms.CharField(label="CPF", max_length=20)
    birthdate = forms.CharField(label="Data de nascimento", max_length=12)
    website = forms.CharField(required=False)  # armadilha para robôs: pessoas não veem nem preenchem

    def __init__(self, *args, ip="", transport=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.ip, self.transport = ip or "?", transport
        self.person = None
        self.cpf_digits = None

    # --- limite de tentativas erradas (por IP e por CPF) ---
    def _keys(self):
        keys = [f"signup-fail:ip:{self.ip}"]
        if self.cpf_digits:
            keys.append(f"signup-fail:cpf:{humand.cpf_hash(self.cpf_digits)}")
        return keys

    def _locked(self) -> bool:
        return any((cache.get(k) or 0) >= settings.SIGNUP_MAX_ATTEMPTS for k in self._keys())

    def _fail(self):
        for key in self._keys():
            try:
                cache.add(key, 0, settings.SIGNUP_LOCK_MINUTES * 60)
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, settings.SIGNUP_LOCK_MINUTES * 60)

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Cadastro inválido.")
        return ""

    def clean(self):
        data = super().clean()
        if self.errors or "cpf" not in data or "birthdate" not in data:
            return data
        self.cpf_digits = humand.clean_cpf(data["cpf"])
        born = humand.parse_birthdate(data["birthdate"])
        if self._locked():
            raise forms.ValidationError("Muitas tentativas. Aguarde alguns minutos e tente de novo.")
        if not self.cpf_digits:
            self._fail()
            self.add_error("cpf", "CPF inválido.")
            return data
        if not born:
            self._fail()
            self.add_error("birthdate", "Data inválida. Use DD/MM/AAAA.")
            return data
        try:
            self.person = humand.lookup_person(self.cpf_digits, born, self.transport)
        except humand.HumandUnavailable:
            raise forms.ValidationError("Não foi possível consultar o cadastro agora. Tente novamente em instantes.")
        if self.person is None:
            self._fail()
            raise forms.ValidationError(INVALID_DATA)
        if (UserProfile.objects.filter(cpf_hash=humand.cpf_hash(self.cpf_digits)).exists()
                or User.objects.filter(username=self.cpf_digits).exists()):
            raise forms.ValidationError(ALREADY_REGISTERED)
        return data


class PasswordForm(forms.Form):
    """Passo 2: a pessoa confere os dados que vieram da Humand e cria a senha. O login é o CPF."""

    password = forms.CharField(label="Crie uma senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar senha", widget=forms.PasswordInput)

    def clean(self):
        data = super().clean()
        password, password2 = data.get("password"), data.get("password2")
        if password and password2 and password != password2:
            self.add_error("password2", "As senhas não são iguais.")
        elif password:
            try:
                validate_password(password)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return data


@transaction.atomic
def create_account(person: "humand.HumandPerson", password: str) -> User:
    """Conta do colaborador: usuário = CPF (só dígitos); nome, e-mail, setor e resorts vindos da Humand; sempre colaborador."""
    department, resorts = humand.match_portal(person)
    first, _, last = person.name.partition(" ")
    try:
        with transaction.atomic():
            user = User.objects.create_user(person.cpf, email=person.email, password=password,
                                            first_name=first, last_name=last)
            profile = user.profile  # criado pelo sinal; quem promove é o administrador
            profile.department, profile.role = department, UserProfile.ROLE_COLABORADOR
            profile.cpf_hash = humand.cpf_hash(person.cpf)
            profile.save()
    except IntegrityError as exc:  # dois cadastros do mesmo CPF ao mesmo tempo
        raise forms.ValidationError(ALREADY_REGISTERED) from exc
    profile.resorts.set(resorts)
    return user
