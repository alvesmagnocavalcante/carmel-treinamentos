from .models import UserProfile


def get_profile(user) -> UserProfile | None:
    """Retorna (criando se necessário) o perfil de um usuário autenticado."""
    if not user.is_authenticated:
        return None
    try:
        return user.profile
    except UserProfile.DoesNotExist:
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile


def access(request):
    profile = get_profile(request.user)
    return {
        'user_profile': profile,
        'can_manage': bool(profile and profile.can_manage),
        'is_global': bool(profile and profile.is_global),
    }
