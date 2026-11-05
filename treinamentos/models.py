from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.urls import reverse


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
    title = models.CharField("Título do Treinamento", max_length=250)
    file_name = models.CharField("Nome do Arquivo Original", max_length=250)
    source_path = models.CharField("Caminho do Arquivo no Servidor", max_length=500, blank=True)
    drive_file_id = models.CharField("ID do Roteiro no Google Drive", max_length=200, blank=True, db_index=True)
    drive_video_id = models.CharField("ID do Vídeo no Google Drive", max_length=200, blank=True)
    status = models.CharField("Status do Pipeline", max_length=30, choices=Status.choices, default=Status.PENDING)
    status_message = models.TextField("Mensagem de Status", blank=True)

    script_text = models.TextField("Roteiro (texto narrado pelo avatar)", blank=True)

    heygen_video_id = models.CharField("ID do Vídeo no HeyGen", max_length=150, blank=True)
    video_url = models.URLField("URL do Vídeo MP4", max_length=1000, blank=True)
    thumbnail_url = models.URLField("URL da Thumbnail", max_length=1000, blank=True)
    duration_seconds = models.FloatField("Duração em Segundos", default=0.0)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Enviado por")
    created_at = models.DateTimeField("Data de Envio", auto_now_add=True)
    completed_at = models.DateTimeField("Data de Conclusão", null=True, blank=True)

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
