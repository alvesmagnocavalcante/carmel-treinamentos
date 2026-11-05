from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User

from .models import Department, SystemSetting, TrainingVideo, UserProfile, VideoProgress

admin.site.site_header = "Carmel Treinamentos"
admin.site.site_title = "Carmel Treinamentos"
admin.site.index_title = "Painel de Controle e Gestão de Setores"


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Perfil de Acesso & Setor'


@admin.display(description='Setor Principal')
def user_department(obj):
    profile = getattr(obj, 'profile', None)
    return profile.department.name if profile and profile.department else '-'


@admin.display(description='Nível de Acesso')
def user_role(obj):
    profile = getattr(obj, 'profile', None)
    return profile.get_role_display() if profile else '-'


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', user_department, user_role, 'is_staff')
    list_filter = ('profile__department', 'profile__role', 'is_staff', 'is_active')
    list_select_related = ('profile__department',)


admin.site.unregister(User)
admin.site.register(User, UserAdmin)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'drive_folder_id', 'avatar_id', 'voice_id', 'total_videos')
    search_fields = ('name', 'code', 'drive_folder_id')
    prepopulated_fields = {'code': ('name',)}


@admin.register(TrainingVideo)
class TrainingVideoAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'status', 'duration', 'created_by', 'created_at')
    list_filter = ('department', 'status', 'created_at')
    search_fields = ('title', 'file_name', 'script_text')
    readonly_fields = ('created_at', 'completed_at', 'heygen_video_id', 'source_path', 'drive_file_id', 'drive_video_id')
    list_select_related = ('department', 'created_by')
    actions = ['reprocess_videos']

    @admin.display(description='Duração', ordering='duration_seconds')
    def duration(self, obj):
        return obj.duration_formatted

    @admin.action(description="Reprocessar vídeos selecionados no HeyGen")
    def reprocess_videos(self, request, queryset):
        from treinamentos.services.pipeline import start_pipeline_async

        count = 0
        for video in queryset:
            video.set_status(TrainingVideo.Status.PENDING, 'Reiniciando pipeline...')
            if start_pipeline_async(video.id):
                count += 1
        self.message_user(request, f"{count} vídeo(s) reenviado(s) para o pipeline de geração.")


@admin.register(VideoProgress)
class VideoProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'video', 'watched_at', 'completed', 'completed_at')
    list_filter = ('video__department', 'completed', 'watched_at')
    search_fields = ('user__username', 'video__title')
    list_select_related = ('user', 'video')


@admin.register(SystemSetting)
class SystemSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'display_value', 'description', 'updated_at')
    search_fields = ('key', 'description')

    @admin.display(description='Valor')
    def display_value(self, obj):
        if obj.key in SystemSetting.SECRET_KEYS and obj.value:
            return f"••••••{obj.value[-4:]}"
        return obj.value or '(vazio — usa .env)'
