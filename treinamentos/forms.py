from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.db import IntegrityError, transaction

from .models import UserProfile
from .services import humand

INVALID_DATA = "Não foi possível validar seus dados. Confira o CPF e a data de nascimento."


class SignupForm(forms.Form):
    """
    Cadastro feito pela própria pessoa: CPF + data de nascimento, conferidos na Humand. Quem passa entra na hora, como
    colaborador; nome, e-mail, setor e resort vêm da Humand.
    """

    cpf = forms.CharField(label="CPF", max_length=20)
    birthdate = forms.CharField(label="Data de nascimento", max_length=12)
    username = forms.CharField(label="Escolha um usuário", max_length=150)
    password = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar senha", widget=forms.PasswordInput)
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

    # --- campos ---
    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not username.replace(".", "").replace("_", "").replace("-", "").isalnum():
            raise forms.ValidationError("Use só letras, números, ponto, hífen ou sublinhado.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Este usuário já está em uso.")
        return username

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Cadastro inválido.")
        return ""

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
        if self.errors or "cpf" not in data or "birthdate" not in data:
            return data  # só consulta a Humand quando o restante está certo

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
        if UserProfile.objects.filter(cpf_hash=humand.cpf_hash(self.cpf_digits)).exists():
            raise forms.ValidationError("Este CPF já possui cadastro. Entre com o seu usuário e senha.")
        return data

    @transaction.atomic
    def save(self) -> User:
        data, person = self.cleaned_data, self.person
        department, resorts = humand.match_portal(person)
        first, _, last = person.name.partition(" ")
        user = User.objects.create_user(
            data["username"], email=person.email, password=data["password"], first_name=first, last_name=last,
        )
        profile = user.profile  # criado pelo sinal; sempre colaborador, quem promove é o administrador
        profile.department, profile.role = department, UserProfile.ROLE_COLABORADOR
        profile.cpf_hash = humand.cpf_hash(self.cpf_digits)
        try:
            with transaction.atomic():
                profile.save()
        except IntegrityError as exc:  # dois cadastros do mesmo CPF ao mesmo tempo
            raise forms.ValidationError("Este CPF já possui cadastro. Entre com o seu usuário e senha.") from exc
        profile.resorts.set(resorts)
        return user
