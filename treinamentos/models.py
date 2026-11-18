from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse

from .services.storage import name_key as normalize_name


class Resort(models.Model):
    """
    Resort da rede (Magna/CM, Charme, Wind, Taiba, Icaraizinho).
    Pessoas e vídeos podem ser ligados a vários resorts. Vídeo sem resort vale para todos.
    """
    code = models.SlugField("Código / Identificador", max_length=50, unique=True)
    name = models.CharField("Nome do Resort", max_length=150)
    order = models.PositiveSmallIntegerField("Ordem na lista", default=0)
    active = models.BooleanField("Ativo", default=True, help_text="Desmarque para tirar o resort das listas de escolha.")
    created_at = models.DateTimeField("Data de Criação", auto_now_add=True)

    class Meta:
        verbose_name = "Resort"
        verbose_name_plural = "Resorts"
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Department(models.Model):
    """
    Setor da empresa (RH, Recepção, Governança, etc.).
    Cada setor possui seu próprio grupo de permissão no Django e sua pasta no Google Drive.
    """
    code = models.SlugField("Código / Identificador", max_length=50, unique=True)
    name = models.CharField("Nome do Setor", max_length=150)
    drive_folder_id = models.CharField("ID da Pasta do Setor no Google Drive", max_length=200, blank=True,
                                       help_text="Pasta do setor; deve conter (ou receberá) as subpastas Roteiros e Vídeos.")
    avatar_id = models.CharField("Avatar HeyGen Padrão", max_length=100, blank=True, help_text="Vazio = usa DEFAULT_AVATAR_ID do .env")
    voice_id = models.CharField("Voz HeyGen Padrão", max_length=100, blank=True, help_text="Vazio = usa DEFAULT_VOICE_ID do .env")
    created_at = models.DateTimeField("Data de Criação", auto_now_add=True)

    class Meta:
        verbose_name = "Setor / Departamento"
        verbose_name_plural = "Setores / Departamentos"
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_videos(self):
        return self.videos.filter(status=TrainingVideo.Status.COMPLETED).count()


class UserProfile(models.Model):
    """
    Perfil estendido para controle de acesso granular de cada colaborador.
    """
    ROLE_COLABORADOR = 'colaborador'
    ROLE_GESTOR = 'gestor'
    ROLE_ADMIN = 'admin'
    ROLE_CHOICES = [
        (ROLE_COLABORADOR, 'Colaborador (Visualiza apenas treinamentos do seu setor)'),
        (ROLE_GESTOR, 'Gestor de Setor (Aprova roteiros e gerencia os vídeos do seu setor)'),
        (ROLE_ADMIN, 'Administrador Geral (Acesso total a todos os setores)'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="Usuário")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='members', verbose_name="Setor Principal")
    role = models.CharField("Nível de Acesso", max_length=20, choices=ROLE_CHOICES, default=ROLE_COLABORADOR)
    resorts = models.ManyToManyField(Resort, blank=True, related_name='members', verbose_name="Resorts",
                                     help_text="Resorts que a pessoa acessa. Sem nenhum, ela vê só os vídeos válidos para todos os resorts.")

    cpf_hash = models.CharField(
        "CPF (hash)", max_length=64, unique=True, null=True, blank=True, editable=False,
        help_text="Impressão digital do CPF validado na Humand no cadastro. Impede duas contas para a mesma pessoa; "
                  "o CPF em si não é guardado.")

    class Meta:
        verbose_name = "Perfil de Usuário"
        verbose_name_plural = "Perfis de Usuários"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"

    @property
    def is_global(self) -> bool:
        """Administrador geral: enxerga e gerencia todos os setores."""
        return self.user.is_superuser or self.role == self.ROLE_ADMIN

    @property
    def can_manage(self) -> bool:
        """Pode revisar roteiros, sincronizar o Drive e reprocessar vídeos."""
        return self.is_global or (self.role == self.ROLE_GESTOR and self.department_id is not None)

    def manageable_resorts(self):
        """Resorts que a pessoa pode escolher ao aprovar um roteiro: todos (administrador) ou só os dela."""
        if self.is_global:
            return Resort.objects.filter(active=True)
        return self.resorts.filter(active=True)

    def visible_departments(self):
        if self.is_global:
            return Department.objects.all()
        if self.department_id:
            return Department.objects.filter(id=self.department_id)
        return Department.objects.none()


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class HumandAlias(models.Model):
    """
    Liga um nome da Humand (grupo de segmentação) a um setor ou resort do portal. Nomes iguais (sem diferenciar
    acento e maiúscula) já são ligados sozinhos; use esta tabela para os que diferem ('CM' -> Magna/CM).
    """
    name = models.CharField("Nome na Humand", max_length=150)
    name_key = models.CharField(max_length=150, unique=True, editable=False)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='humand_aliases', verbose_name="Setor do portal")
    resort = models.ForeignKey(Resort, on_delete=models.CASCADE, null=True, blank=True,
                               related_name='humand_aliases', verbose_name="Resort do portal")

    class Meta:
        verbose_name = "Correspondência com a Humand"
        verbose_name_plural = "Correspondências com a Humand"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} → {self.department or self.resort}"

    def clean(self):
        from django.core.exceptions import ValidationError
        if bool(self.department_id) == bool(self.resort_id):
            raise ValidationError("Escolha um setor OU um resort.")

    def save(self, *args, **kwargs):
        self.name_key = normalize_name(self.name)
        super().save(*args, **kwargs)


class DriveImage(models.Model):
    """
    Imagem encontrada na subpasta Imagens do setor no Drive (preenchida pela sincronização).
    O roteiro cita a imagem pelo nome; aqui ficam o arquivo do Drive e se ele pode ser usado.
    """
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='images', verbose_name="Setor")
    name = models.CharField("Nome do arquivo", max_length=250)
    name_key = models.CharField("Nome normalizado", max_length=250, db_index=True)
    drive_file_id = models.CharField("ID da imagem no Google Drive", max_length=200, unique=True)
    mime_type = models.CharField("Tipo", max_length=100, blank=True)
    size_bytes = models.BigIntegerField("Tamanho em bytes", default=0)
    too_large = models.BooleanField("Grande demais", default=False, help_text="Passou do limite de tamanho: não é usada nos vídeos.")
    width = models.PositiveIntegerField("Largura (px)", default=0, help_text="0 = o Drive não informou.")
    height = models.PositiveIntegerField("Altura (px)", default=0, help_text="0 = o Drive não informou.")
    modified_at = models.CharField("Última alteração no Drive", max_length=40, blank=True)
    updated_at = models.DateTimeField("Atualizada em", auto_now=True)

    class Meta:
        verbose_name = "Imagem do Drive"
        verbose_name_plural = "Imagens do Drive"
        ordering = ['department', 'name']

    def __str__(self):
        return f"[{self.department.name}] {self.name}"

    def save(self, *args, **kwargs):
        self.name_key = normalize_name(self.name)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'name' in update_fields:
            kwargs['update_fields'] = {*update_fields, 'name_key'}
        super().save(*args, **kwargs)


class TrainingVideoQuerySet(models.QuerySet):
    def visible_to(self, profile):
        """
        Vídeos que a pessoa pode ver: do setor dela E de pelo menos um resort dela.
        Vídeo sem resort vale para todos. Administrador geral vê tudo.
        """
        if profile.is_global:
            return self
        resort_ids = list(profile.resorts.values_list('id', flat=True))
        return self.filter(department__in=profile.visible_departments()).filter(
            models.Q(resorts__isnull=True) | models.Q(resorts__in=resort_ids)
        ).distinct()


class TrainingVideo(models.Model):
    """
    Documento transformado em Vídeo com Avatar Digital da HeyGen.
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Na Fila'
        PARSING = 'PARSING', 'Lendo Documento'
        AWAITING_REVIEW = 'AWAITING_REVIEW', 'Aguardando Revisão do Roteiro'
        AWAITING_VIDEO = 'AWAITING_VIDEO', 'Aguardando Vídeo'
        GENERATING_HEYGEN = 'GENERATING_HEYGEN', 'HeyGen Renderizando'
        COMPLETED = 'COMPLETED', 'Concluído & Disponível'
        FAILED = 'FAILED', 'Falha no Processamento'

    IN_PROGRESS = (Status.PENDING, Status.PARSING, Status.GENERATING_HEYGEN)

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='videos', verbose_name="Setor")
    resorts = models.ManyToManyField(Resort, blank=True, related_name='videos', verbose_name="Resorts",
                                     help_text="Resorts para os quais o vídeo vale. Vazio = todos os resorts.")
    title =models.CharField("Título do Treinamento", max_length=250)
    file_name = models.CharField("Nome do Arquivo Original", max_length=250)
    source_path = models.CharField("Caminho do Arquivo no Servidor", max_length=500, blank=True)
    drive_file_id = models.CharField("ID do Roteiro no Google Drive", max_length=200, blank=True, db_index=True)
    drive_modified_at = models.CharField("Última alteração do roteiro no Drive", max_length=40, blank=True)
    drive_video_id = models.CharField("ID do Vídeo no Google Drive", max_length=200, blank=True)
    status = models.CharField("Status do Pipeline", max_length=30, choices=Status.choices, default=Status.PENDING)
    status_message = models.TextField("Mensagem de Status", blank=True)

    script_text = models.TextField("Roteiro (texto narrado pelo avatar)", blank=True)
    scenes = models.JSONField(
        "Cenas", default=list, blank=True,
        help_text="Lista de {ordem, texto, imagem}. Vazio = uma cena só, sem imagem (o próprio roteiro).",
    )

    heygen_video_id = models.CharField("ID do Vídeo no HeyGen", max_length=150, blank=True)
    video_url = models.URLField("URL do Vídeo MP4", max_length=1000, blank=True)
    thumbnail_url = models.URLField("URL da Thumbnail", max_length=1000, blank=True)
    duration_seconds = models.FloatField("Duração em Segundos", default=0.0)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviado por")
    created_at = models.DateTimeField("Data de Envio", auto_now_add=True)
    completed_at = models.DateTimeField("Data de Conclusão", null=True, blank=True)

    objects = TrainingVideoQuerySet.as_manager()

    class Meta:
        verbose_name = "Vídeo de Treinamento"
        verbose_name_plural = "Vídeos de Treinamento"
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.department.name}] {self.title}"

    @property
    def play_url(self) -> str:
        """Vídeos salvos no Drive tocam pelo portal (cópia permanente); os demais, pelo link da HeyGen."""
        if self.drive_video_id:
            return reverse('stream_video', args=[self.id])
        return self.video_url

    @property
    def scene_list(self) -> list:
        """Cenas do vídeo. Sem cenas gravadas (vídeos antigos ou sem marcação), é uma cena só, sem imagem."""
        if self.scenes:
            return self.scenes
        text = (self.script_text or "").strip()
        return [{"ordem": 1, "texto": self.script_text, "imagem": ""}] if text else []

    @property
    def has_images(self) -> bool:
        return any(scene.get("imagem") for scene in self.scenes or [])

    @property
    def is_in_progress(self) -> bool:
        return self.status in self.IN_PROGRESS

    @property
    def duration_formatted(self):
        total = int(self.duration_seconds or 0)
        return f"{total // 60}:{total % 60:02d}"

    def set_status(self, status: str, message: str = "", **fields):
        self.status = status
        self.status_message = message
        for key, value in fields.items():
            setattr(self, key, value)
        self.save(update_fields=['status', 'status_message', *fields.keys()])


class VideoProgress(models.Model):
    """
    Rastreamento de visualizações e conclusão dos treinamentos por colaborador.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='video_views', verbose_name="Colaborador")
    video = models.ForeignKey(TrainingVideo, on_delete=models.CASCADE, related_name='views', verbose_name="Vídeo")
    watched_at = models.DateTimeField("Assistido em", auto_now_add=True)
    completed = models.BooleanField("Treinamento Concluído", default=False)
    completed_at = models.DateTimeField("Concluído em", null=True, blank=True)

    class Meta:
        verbose_name = "Registro de Visualização"
        verbose_name_plural = "Registros de Visualizações"
        unique_together = ('user', 'video')

    def __str__(self):
        return f"{self.user.username} — {self.video.title}"


class SystemSetting(models.Model):
    """
    Configurações gerais do sistema (Drive).
    Um valor vazio aqui NÃO sobrescreve o .env: o valor do .env é usado como fallback.
    """
    SECRET_KEYS = ()

    key = models.CharField("Chave", max_length=100, primary_key=True)
    value = models.TextField("Valor", blank=True)
    description = models.CharField("Descrição", max_length=250, blank=True)
    updated_at = models.DateTimeField("Última Atualização", auto_now=True)

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    def __str__(self):
        return self.key

    @classmethod
    def get_val(cls, key: str, default: str = "") -> str:
        value = cls.objects.filter(key=key).values_list('value', flat=True).first()
        return value.strip() if value and value.strip() else default
