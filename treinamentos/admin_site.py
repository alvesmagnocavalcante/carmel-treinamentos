"""Painel de administração da Carmel: página inicial com resumo e menu lateral organizado por assunto."""
from django.contrib import admin
from django.db.models import Count, Q
from django.urls import reverse

from .models import Department, TrainingVideo

Status = TrainingVideo.Status

# Como os modelos aparecem no menu e no painel: (nome do modelo, ícone, título, descrição).
NAV_GROUPS = [
    ("Pessoas e acessos", [
        ("User", "users", "Usuários", "Crie contas e defina o setor e o nível de acesso de cada pessoa."),
        ("Group", "shield-check", "Grupos", "Permissões avançadas. Raramente é preciso mexer aqui."),
    ]),
    ("Conteúdo", [
        ("Department", "building-2", "Setores", "Pasta do Drive, avatar e voz de cada setor."),
        ("TrainingVideo", "clapperboard", "Vídeos de treinamento", "Roteiros, andamento e vídeos publicados."),
        ("VideoProgress", "eye", "Visualizações", "Quem assistiu e quem concluiu cada vídeo."),
    ]),
    ("Sistema", [
        ("SystemSetting", "settings", "Configurações", "Ajustes gerais do sistema."),
    ]),
]


class CarmelAdminSite(admin.AdminSite):
    site_header = "Carmel Treinamentos"
    site_title = "Carmel Treinamentos"
    index_title = "Painel de gestão"

    def _nav(self, request, app_list):
        """Agrupa os modelos que o usuário pode ver, com ícone, título e endereços."""
        models = {m["object_name"]: m for app in app_list for m in app["models"]}
        groups = []
        for title, entries in NAV_GROUPS:
            items = []
            for object_name, icon, label, description in entries:
                model = models.get(object_name)
                if not model or not model.get("admin_url"):
                    continue
                items.append({
                    "name": label, "icon": icon, "description": description,
                    "url": model["admin_url"], "add_url": model.get("add_url"),
                    "active": request.path.startswith(model["admin_url"]),
                })
            if items:
                groups.append({"title": title, "items": items})
        return groups

    def each_context(self, request):
        context = super().each_context(request)
        context["carmel_nav"] = self._nav(request, context["available_apps"])
        return context

    def index(self, request, extra_context=None):
        extra = dict(extra_context or {})
        user = request.user

        if user.has_perm("treinamentos.view_trainingvideo"):
            counts = TrainingVideo.objects.aggregate(
                published=Count("id", filter=Q(status=Status.COMPLETED)),
                review=Count("id", filter=Q(status=Status.AWAITING_REVIEW)),
                waiting=Count("id", filter=Q(status=Status.AWAITING_VIDEO)),
                running=Count("id", filter=Q(status__in=[Status.PENDING, Status.PARSING, Status.GENERATING_HEYGEN])),
                failed=Count("id", filter=Q(status=Status.FAILED)),
            )
            changelist = reverse("admin:treinamentos_trainingvideo_changelist")
            extra["kpis"] = [
                {"label": "Vídeos publicados", "value": counts["published"], "tone": "ok", "icon": "circle-check",
                 "hint": "Disponíveis no catálogo", "url": f"{changelist}?status__exact={Status.COMPLETED}"},
                {"label": "Aguardando revisão", "value": counts["review"], "tone": "warn", "icon": "file-search",
                 "hint": "Um gestor precisa aprovar o roteiro", "url": f"{changelist}?status__exact={Status.AWAITING_REVIEW}"},
                {"label": "Aguardando vídeo", "value": counts["waiting"], "tone": "warn", "icon": "hourglass",
                 "hint": "Roteiro aprovado, vídeo ainda não gerado", "url": f"{changelist}?status__exact={Status.AWAITING_VIDEO}"},
                {"label": "Em andamento", "value": counts["running"], "tone": "info", "icon": "loader",
                 "hint": "Sendo lidos ou gerados agora", "url": changelist},
                {"label": "Com falha", "value": counts["failed"], "tone": "err" if counts["failed"] else "neutral",
                 "icon": "triangle-alert", "hint": "Precisam de atenção", "url": f"{changelist}?status__exact={Status.FAILED}"},
            ]

        if user.has_perm("treinamentos.view_department"):
            sectors = Department.objects.annotate(
                published=Count("videos", filter=Q(videos__status=Status.COMPLETED)),
                waiting=Count("videos", filter=Q(videos__status__in=[Status.AWAITING_REVIEW, Status.AWAITING_VIDEO])),
            ).order_by("name")
            extra["sectors"] = [
                {"name": d.name, "published": d.published, "waiting": d.waiting, "has_drive": bool(d.drive_folder_id),
                 "url": reverse("admin:treinamentos_department_change", args=[d.pk])}
                for d in sectors
            ]
            extra["sectors_without_drive"] = sum(1 for d in extra["sectors"] if not d["has_drive"])

        return super().index(request, extra)
