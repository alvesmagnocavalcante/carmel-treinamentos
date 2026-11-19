"""
Validação de colaboradores na Humand, SOMENTE LEITURA (nunca cria, altera nem apaga nada lá).

A pessoa informa CPF + data de nascimento; o portal consulta `GET /users/{cpf}` (na Humand o CPF é o
`employeeInternalId`) e só libera quando o usuário existe, está ativo e a data de nascimento confere.
Nome, e-mail, setor e resort vêm da Humand, nunca do que a pessoa digitou.
"""

import hashlib
import hmac
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import httpx
from django.conf import settings
from django.core.cache import cache

from .storage import name_key

logger = logging.getLogger(__name__)

HOTEL_ITEM_GROUPS = {"hoteis", "novos admitidos"}  # grupos da Humand cujos itens são hotéis
IGNORED_GROUPS = {"gestores/ lideres", "gestores/lideres"}  # grupos que não dizem setor nem resort


class HumandUnavailable(Exception):
    """A Humand não respondeu (chave ausente, rede, erro do servidor). Não é culpa da pessoa."""


@dataclass
class HumandPerson:
    name: str
    email: str
    resort_names: list = field(default_factory=list)
    department_names: list = field(default_factory=list)
    position: str = ""        # função/cargo, quando a Humand tem
    cpf: str = ""


def clean_cpf(value: str) -> Optional[str]:
    """Só os 11 dígitos, ou None se o CPF é inválido (tamanho, repetido ou dígitos verificadores)."""
    cpf = re.sub(r"\D", "", value or "")
    if len(cpf) != 11 or len(set(cpf)) == 1:
        return None

    def digit(part: str) -> str:
        rest = sum(int(n) * w for n, w in zip(part, range(len(part) + 1, 1, -1))) % 11
        return str(0 if rest < 2 else 11 - rest)

    return cpf if cpf[-2:] == digit(cpf[:9]) + digit(cpf[:10]) else None


def parse_birthdate(value: str) -> Optional[date]:
    """DD/MM/AAAA (ou DDMMAAAA) -> data, ou None se inválida ou no futuro."""
    digits = re.sub(r"\D", "", value or "")
    try:
        born = datetime.strptime(digits, "%d%m%Y").date()
    except ValueError:
        return None
    return born if born <= date.today() else None


def cpf_hash(cpf: str) -> str:
    """Impressão digital do CPF (HMAC com a chave secreta do projeto): permite impedir contas repetidas sem guardar o CPF."""
    return hmac.new(settings.SECRET_KEY.encode(), f"cpf:{cpf}".encode(), hashlib.sha256).hexdigest()


def is_configured() -> bool:
    return bool(settings.HUMAND_API_KEY)


def _get(path: str, params: Optional[dict] = None, transport: Optional[httpx.BaseTransport] = None):
    """GET na Humand. Devolve o JSON, ou None se a Humand diz que não existe (400/404). Qualquer outra falha vira HumandUnavailable."""
    if not is_configured():
        raise HumandUnavailable("HUMAND_API_KEY não configurada.")
    try:
        with httpx.Client(
            base_url=settings.HUMAND_BASE_URL, timeout=15, transport=transport,
            headers={"Authorization": f"Basic {settings.HUMAND_API_KEY}", "Accept": "application/json"},
        ) as client:
            response = client.get(path, params=params)
    except httpx.RequestError as exc:
        logger.warning("Humand: falha de conexão (%s: %s)", exc.__class__.__name__, exc)
        raise HumandUnavailable(f"Falha de conexão com a Humand: {exc.__class__.__name__}") from exc
    if response.status_code in (400, 404):
        return None
    if response.is_error:
        # sem o CPF no log; o corpo da resposta ajuda a achar o motivo (chave recusada, limite de uso...)
        logger.warning("Humand respondeu HTTP %s: %s", response.status_code, response.text[:200])
        raise HumandUnavailable(f"Humand respondeu HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        logger.warning("Humand: resposta não é JSON (HTTP %s): %s", response.status_code, response.text[:200])
        raise HumandUnavailable("Resposta inválida da Humand.") from exc


def _fetch(cpf: str) -> Optional[dict]:
    data = _get(f"/users/{cpf}")
    return data if isinstance(data, dict) else None


def _items(path: str, params: Optional[dict] = None) -> list:
    """Todos os itens de uma lista paginada da Humand (campo `items`)."""
    found, page = [], 1
    while True:
        data = _get(path, {**(params or {}), "limit": 50, "page": page})
        batch = data.get("items", []) if isinstance(data, dict) else []
        found += batch
        if len(batch) < 50 or page >= (data.get("totalPages") or page):
            return found
        page += 1


POSITIONS_CACHE_KEY = "humand:positions"
POSITIONS_CACHE_SECONDS = 6 * 3600


def position_map() -> dict:
    """
    {CPF: nome do cargo} de todos os colaboradores. A Humand só diz o cargo pela lista de membros de cada cargo
    (não vem no cadastro da pessoa), então o mapa é montado uma vez e guardado por algumas horas.
    """
    mapping = cache.get(POSITIONS_CACHE_KEY)
    if mapping is not None:
        return mapping
    positions = [p for p in _items("/job-positions") if p.get("usersCount") and not p.get("deletedAt")]

    def members_of(position):
        try:
            return position, _items(f"/job-positions/{position['id']}/members")
        except HumandUnavailable:
            return position, None  # um cargo que falha não derruba os outros

    mapping, failed = {}, 0
    with ThreadPoolExecutor(max_workers=10) as pool:  # ~65 cargos a ~0,7 s cada: em série seriam ~45 s
        for position, members in pool.map(members_of, positions):
            if members is None:
                failed += 1
                continue
            name = " ".join(str(position.get("name", "")).split())
            mapping.update({str(m.get("employeeInternalId")): name for m in members})
    # mapa incompleto vale por pouco tempo, para a próxima pessoa tentar de novo
    cache.set(POSITIONS_CACHE_KEY, mapping, 300 if failed else POSITIONS_CACHE_SECONDS)
    return mapping


POSITION_NAMES_CACHE_KEY = "humand:position-names"


def position_names() -> list:
    """Nomes dos cargos da Humand, para a pessoa escolher quando a Humand não traz o dela. Vazio se a consulta falhar."""
    names = cache.get(POSITION_NAMES_CACHE_KEY)
    if names is None:
        try:
            found = {" ".join(str(p.get("name", "")).split()) for p in _items("/job-positions") if not p.get("deletedAt")}
        except HumandUnavailable:
            return []
        names = sorted(n for n in found if n)
        cache.set(POSITION_NAMES_CACHE_KEY, names, POSITIONS_CACHE_SECONDS)
    return names


def find_position(cpf: str) -> str:
    """Cargo da pessoa, ou vazio. É só um detalhe da tela de conferência: se a consulta falhar, o cadastro segue sem ele."""
    try:
        return position_map().get(cpf, "")
    except HumandUnavailable:
        return ""


def hotel_name(text: str) -> str:
    """'Carmel Taíba' -> 'Taíba'. O prefixo 'Carmel' é tirado para comparar com o nome do resort."""
    text = text.strip()
    return text[len("carmel"):].strip() if name_key(text).startswith("carmel ") else text


def split_segmentations(segmentations) -> tuple:
    """
    (hotéis, setores) citados pela pessoa. Nos grupos 'Hotéis' e 'Novos admitidos' o item é o hotel. Nos grupos de cada
    hotel (Carmel Taíba, Carmel Cumbuco, CM, Magna...) o nome do grupo é o hotel e o item é o setor.
    """
    resorts, departments = [], []
    for seg in segmentations or []:
        if not isinstance(seg, dict):
            continue
        group, item = name_key(seg.get("group") or ""), (seg.get("item") or "").strip()
        if not item or group in IGNORED_GROUPS:
            continue
        if group in HOTEL_ITEM_GROUPS:
            resorts.append(hotel_name(item))
        else:
            resorts.append(hotel_name(seg["group"]))
            departments.append(item)
    return list(dict.fromkeys(resorts)), departments


def lookup_person(cpf: str, birthdate: date) -> Optional[HumandPerson]:
    """
    A pessoa da Humand, ou None se não existe, está inativa/excluída ou a data de nascimento não confere.
    (Os três casos são iguais para quem chamou: não revelamos qual deles aconteceu.)
    """
    data = _fetch(cpf)
    if not data or data.get("deleted") or str(data.get("status", "")).upper() != "ACTIVE":
        return None
    if str(data.get("birthdate") or "")[:10] != birthdate.isoformat():
        return None
    resorts, departments = split_segmentations(data.get("segmentations"))
    name = " ".join(p for p in (data.get("firstName"), data.get("lastName")) if p).strip()
    return HumandPerson(name=name, email=(data.get("email") or "").strip().lower(),
                        resort_names=resorts, department_names=departments,
                        position=find_position(cpf), cpf=cpf)


def match_portal(person: HumandPerson) -> tuple:
    """
    (setor, resorts) do portal para os nomes da Humand. Liga por nome igual (sem acento/maiúscula) ou pela tabela
    de correspondências do painel. O que não for reconhecido é ignorado (a pessoa entra e o admin completa).
    """
    from ..models import Department, HumandAlias, Resort

    aliases = {a.name_key: a for a in HumandAlias.objects.select_related("department", "resort")}
    resort_by_key = {name_key(r.name): r for r in Resort.objects.filter(active=True)}
    department_by_key = {name_key(d.name): d for d in Department.objects.all()}

    def resolve(raw, by_key, attr):
        alias = aliases.get(name_key(raw))
        return getattr(alias, attr) if alias and getattr(alias, attr) else by_key.get(name_key(raw))

    resorts = []
    for raw in person.resort_names:
        found = resolve(raw, resort_by_key, "resort")
        if found and found not in resorts:
            resorts.append(found)
    department = next((d for d in (resolve(r, department_by_key, "department") for r in person.department_names) if d), None)
    return department, resorts
