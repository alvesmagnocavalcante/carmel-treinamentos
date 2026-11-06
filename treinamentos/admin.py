from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from django.utils.html import format_html

from .models import Department, SystemSetting, TrainingVideo, UserProfile, VideoProgress

Status = TrainingVideo.Status

# Cor da etiqueta de cada situação nas listas (as classes pill-* estão em carmel_admin.css).
STATUS_TONE = {
    Status.COMPLETED: "ok",
    Status.FAILED: "err",
    Status.AWAITING_REVIEW: "warn",
    Status.AWAITING_VIDEO: "warn",
    Status.GENERATING_HEYGEN: "info",
    Status.PENDING: "neutral",
    Status.PARSING: "neutral",
}


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de acesso e setor'


@admin.display(description='Setor')
def user_department(obj):
    profile = getattr(obj, 'profile', None)
    return profile.department.name if profile and profile.department else '-'


@admin.display(description='Nível de acesso')
def user_role(obj):
    profile = getattr(obj, 'profile', None)
    return profile.get_role_display().split(' (')[0] if profile else '-'


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'first_name', 'last_name', 'email', user_department, user_role, 'is_active')
    list_filter = ('profile__department', 'profile__role', 'is_active', 'is_staff')
    list_select_related = ('profile__department',)
    list_per_page = 25


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'drive_ok', 'avatar_id', 'voice_id', 'total_videos')
    search_fields = ('name', 'code', 'drive_folder_id')
    prepopulated_fields = {'code': ('name',)}
    fieldsets = (
        ('Setor', {'fields': ('name', 'code')}),
        ('Google Drive', {
            'fields': ('drive_folder_id',),
            'description': 'Cole o ID da pasta do setor (o trecho final do endereço da pasta no Drive). '
                           'Sem ele, o portal não importa roteiros nem salva vídeos deste setor.',
        }),
        ('Avatar e voz da HeyGen', {
            'fields': ('avatar_id', 'voice_id'),
            'description': 'Opcional. Deixe vazio para usar o avatar e a voz padrão do sistema.',
        }),
    )

    @admin.display(boolean=True, description='Drive configurado')
    def drive_ok(self, obj):
        return bool(obj.drive_folder_id)

    @admin.display(description='Vídeos publicados')
    def total_videos(self, obj):
        return obj.total_videos


@admin.register(TrainingVideo)
class TrainingVideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'status_badge', 'duration')
    ordering = ('-created_at',)
    list_filter = ('status', 'department', 'created_at')
    search_fields = ('title', 'file_name', 'script_text')
    list_select_related = ('department', 'created_by')
    list_per_page = 25
    actions = ['reprocess_videos']
    readonly_fields = ('created_at', 'completed_at', 'heygen_video_id', 'source_path',
                       'drive_file_id', 'drive_modified_at', 'drive_video_id')
    fieldsets = (
        ('Identificação', {'fields': ('title', 'department', 'status', 'status_message')}),
        ('Roteiro', {'fields': ('script_text',)}),
        ('Vídeo', {'fields': ('video_url', 'thumbnail_url', 'duration_seconds', 'completed_at')}),
        ('Dados técnicos', {
            'classes': ('collapse',),
            'fields': ('file_name', 'created_by', 'created_at', 'heygen_video_id', 'source_path',
                       'drive_file_id', 'drive_modified_at', 'drive_video_id'),
        }),
    )

    @admin.display(description='Situação', ordering='status')
    def status_badge(self, obj):
        return format_html('<span class="pill pill-{}">{}</span>', STATUS_TONE.get(obj.status, 'neutral'), obj.get_status_display())

    @admin.display(description='Duração', ordering='duration_seconds')
    def duration(self, obj):
        return obj.duration_formatted if obj.duration_seconds else '-'

    @admin.action(description="Reprocessar vídeos selecionados")
    def reprocess_videos(self, request, queryset):
        from treinamentos.services.pipeline import start_pipeline_async

        count = 0
        for video in queryset:
            video.set_status(Status.PENDING, 'Reiniciando o processamento...')
            if start_pipeline_async(video.id):
                count += 1
        self.message_user(request, f"{count} vídeo(s) reenviado(s) para processamento.")


@admin.register(VideoProgress)
class VideoProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'video', 'watched_at', 'completed')
    list_filter = ('video__department', 'completed', 'watched_at')
    search_fields = ('user__username', 'video__title')
    list_select_related = ('user', 'video')
    list_per_page = 25


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'display_value', 'description', 'updated_at')
    search_fields = ('key', 'description')

    @admin.display(description='Valor')
    def display_value(self, obj):
        if obj.key in SystemSetting.SECRET_KEYS and obj.value:
            return f"••••••{obj.value[-4:]}"
        return obj.value or '(vazio — usa .env)'
