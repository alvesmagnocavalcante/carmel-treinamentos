import logging
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .context_processors import get_profile
from .models import Department, TrainingVideo, VideoProgress
from .services.drive_service import GoogleDriveService
from .services.document_parser import clean_script
from .services.heygen_service import MAX_SCRIPT_CHARS
from .services.pipeline import (
    approve_and_generate, attach_uploaded_video, generation_params, mark_awaiting_video,
    start_pipeline_async, validate_script,
)
from .services.storage import is_allowed_extension, new_source_path, safe_filename, title_from_filename

Status = TrainingVideo.Status
logger = logging.getLogger(__name__)


def _require_manager(request):
    profile = get_profile(request.user)
    if not profile.can_manage:
        raise PermissionDenied("Apenas gestores e administradores podem executar esta ação.")
    return profile


@login_required
def home_view(request):
    """Catálogo de treinamentos, filtrado pelos setores que o usuário pode ver."""
    profile = get_profile(request.user)
    allowed_depts = profile.visible_departments()

    selected_dept = request.GET.get('setor', 'all')
    if selected_dept != 'all' and not allowed_depts.filter(code=selected_dept).exists():
        selected_dept = 'all'

    search_query = request.GET.get('q', '').strip()

    videos = TrainingVideo.objects.filter(status=Status.COMPLETED, department__in=allowed_depts).select_related('department')
    if selected_dept != 'all':
        videos = videos.filter(department__code=selected_dept)
    if search_query:
        videos = videos.filter(
            Q(title__icontains=search_query)
            | Q(script_text__icontains=search_query)
            | Q(file_name__icontains=search_query)
        )

    watched_ids = set(
        VideoProgress.objects.filter(user=request.user, completed=True).values_list('video_id', flat=True)
    )

    return render(request, 'treinamentos/home.html', {
        'departments': allowed_depts,
        'show_dept_filter': allowed_depts.count() > 1,
        'selected_dept': selected_dept,
        'videos': videos.order_by('-completed_at', '-created_at'),
        'watched_ids': watched_ids,
        'search_query': search_query,
    })


@login_required
def queue_view(request):
    """Fila de processamento (documentos lidos, roteirizados e enviados à HeyGen)."""
    profile = get_profile(request.user)
    jobs = (
        TrainingVideo.objects.filter(department__in=profile.visible_departments())
        .select_related('department', 'created_by')
        .order_by('-created_at')[:50]
    )
    jobs = list(jobs)
    return render(request, 'treinamentos/queue.html', {
        'jobs': jobs,
        'has_active_jobs': any(j.is_in_progress for j in jobs),
    })


@login_required
def upload_document_view(request):
    """Upload manual de documento (gestores e administradores)."""
    profile = _require_manager(request)
    departments = profile.visible_departments()

    if request.method == 'POST':
        upload = request.FILES.get('file')
        dept = departments.filter(id=request.POST.get('department_id') or 0).first()
        title = request.POST.get('title', '').strip()[:250]

        error = None
        if not upload:
            error = "Selecione um arquivo."
        elif not dept:
            error = "Setor inválido ou sem permissão."
        elif not is_allowed_extension(upload.name):
            error = "Formato não suportado. Envie PDF, DOCX, TXT ou MD."
        elif upload.size > settings.MAX_UPLOAD_MB * 1024 * 1024:
            error = f"Arquivo maior que o limite de {settings.MAX_UPLOAD_MB} MB."

        if error:
            messages.error(request, error)
        else:
            dest = new_source_path(f"upload_{dept.code}", upload.name)
            with open(dest, 'wb') as fh:
                for chunk in upload.chunks():
                    fh.write(chunk)

            video = TrainingVideo.objects.create(
                department=dept,
                title=title or title_from_filename(upload.name),
                file_name=safe_filename(upload.name),
                source_path=str(dest),
                status=Status.PENDING,
                status_message='Documento enviado. Iniciando leitura...',
                created_by=request.user,
            )
            start_pipeline_async(video.id)
            messages.success(request, f"Documento '{video.file_name}' recebido! O vídeo está sendo gerado.")
            return redirect('queue')

    return render(request, 'treinamentos/upload.html', {
        'departments': departments,
        'max_upload_mb': settings.MAX_UPLOAD_MB,
        'allowed_ext': ", ".join(settings.ALLOWED_DOC_EXTENSIONS),
    })


@login_required
@require_POST
def sync_drive_ajax(request):
    """Varredura imediata das pastas dos setores (somente os setores do gestor)."""
    profile = _require_manager(request)
    result = GoogleDriveService.scan_all_departments(profile.visible_departments())
    for video in result['new_videos']:
        start_pipeline_async(video.id)

    found, published = result['found'], result['published']
    parts = []
    if found:
        parts.append(f"{found} novo(s) roteiro(s) encontrado(s) e enviado(s) para a fila")
    if published:
        parts.append(f"{published} vídeo(s) carregado(s) do Drive e publicado(s) no catálogo")
    message = ("; ".join(parts) + ".") if parts else "Nada novo encontrado nas pastas Roteiros e Vídeos."
    if not result['drive_connected']:
        message += " (Google Drive não configurado — apenas pastas locais foram varridas.)"
    if result['errors']:
        message += " Erros: " + "; ".join(result['errors'])

    return JsonResponse({
        'status': 'error' if result['errors'] else 'success',
        'found': found, 'published': published, 'message': message,
    })


@login_required
@require_POST
def retry_video_view(request, video_id):
    """Reprocessa um vídeo que falhou."""
    profile = _require_manager(request)
    video = get_object_or_404(TrainingVideo, id=video_id, department__in=profile.visible_departments())
    if video.is_in_progress and video.status != Status.PENDING:
        messages.error(request, "Este vídeo já está em processamento.")
    else:
        video.set_status(Status.PENDING, "Reiniciando pipeline...")
        start_pipeline_async(video.id)
        messages.success(request, f"'{video.title}' reenviado para processamento.")
    return redirect('queue')


@login_required
def review_script_view(request, video_id):
    """O gestor lê/edita o roteiro e aprova antes de gastar crédito da HeyGen."""
    profile = _require_manager(request)
    video = get_object_or_404(TrainingVideo, id=video_id, department__in=profile.visible_departments())
    if video.status != Status.AWAITING_REVIEW:
        messages.error(request, "Este vídeo não está aguardando revisão de roteiro.")
        return redirect('queue')

    script = video.script_text
    if request.method == 'POST':
        script = clean_script(request.POST.get('script', ''))
        try:
            validate_script(script)
        except ValueError as exc:
            messages.error(request, str(exc))
        else:
            video.script_text = script
            video.save(update_fields=['script_text'])
            if settings.HEYGEN_GENERATION_MODE == 'api':
                video.set_status(Status.PENDING, "Roteiro aprovado. Enviando para a HeyGen...")
                start_pipeline_async(video.id, approve_and_generate)
                messages.success(request, f"Roteiro de '{video.title}' aprovado! O vídeo está sendo gerado.")
            else:
                mark_awaiting_video(video)
                messages.success(
                    request, f"Roteiro de '{video.title}' aprovado! Agora o vídeo precisa ser gerado na HeyGen e registrado."
                )
            return redirect('queue')

    return render(request, 'treinamentos/review.html', {
        'video': video, 'script': script, 'max_chars': MAX_SCRIPT_CHARS,
    })


@login_required
def attach_video_view(request, video_id):
    """Anexa o MP4 gerado fora do portal (MCP/site da HeyGen); ele é guardado no Drive e publicado no catálogo."""
    profile = _require_manager(request)
    video = get_object_or_404(TrainingVideo, id=video_id, department__in=profile.visible_departments())
    if video.status != Status.AWAITING_VIDEO:
        messages.error(request, "Este vídeo não está aguardando a geração.")
        return redirect('queue')

    if request.method == 'POST':
        upload = request.FILES.get('file')
        error = None
        if not upload:
            error = "Selecione o arquivo MP4."
        elif Path(upload.name).suffix.lower() != '.mp4':
            error = "Formato não suportado. Envie o vídeo em MP4."
        elif upload.size > settings.MAX_VIDEO_MB * 1024 * 1024:
            error = f"Vídeo maior que o limite de {settings.MAX_VIDEO_MB} MB."

        if not error:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "video.mp4"
                with open(path, 'wb') as fh:
                    for chunk in upload.chunks():
                        fh.write(chunk)
                try:
                    attach_uploaded_video(video, path)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Falha ao anexar o vídeo %s", video.id)
                    error = f"Não foi possível salvar no Drive: {exc}"
        if error:
            messages.error(request, error)
        else:
            messages.success(request, f"Vídeo de '{video.title}' anexado e publicado no catálogo.")
            return redirect('queue')

    return render(request, 'treinamentos/attach.html', {
        'video': video, 'params': generation_params(video), 'max_video_mb': settings.MAX_VIDEO_MB,
    })


RANGE_RE = re.compile(r"^bytes=\d*-\d*$")  # só um intervalo simples; o suficiente para o player de vídeo


@login_required
def stream_video_view(request, video_id):
    """
    Entrega o vídeo guardado no Drive ao colaborador logado (o Drive é privado, então o
    portal faz a ponte), respeitando o acesso por setor. Suporta Range para avançar/voltar.
    """
    profile = get_profile(request.user)
    video = get_object_or_404(
        TrainingVideo, id=video_id, status=Status.COMPLETED, department__in=profile.visible_departments()
    )
    if not video.drive_video_id:
        if video.video_url:
            return HttpResponseRedirect(video.video_url)
        raise Http404("Vídeo sem arquivo disponível.")

    range_header = request.headers.get("Range", "")
    if not RANGE_RE.match(range_header):
        range_header = ""

    try:
        client, upstream = GoogleDriveService.open_file_stream(video.drive_video_id, range_header)
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao abrir o vídeo %s no Drive", video.id)
        return HttpResponseRedirect(video.video_url) if video.video_url else HttpResponse("Vídeo indisponível.", status=502)

    if upstream.status_code not in (200, 206):
        status = upstream.status_code
        upstream.close()
        client.close()
        logger.error("Drive respondeu %s para o vídeo %s", status, video.id)
        if video.video_url:
            return HttpResponseRedirect(video.video_url)
        return HttpResponse("Vídeo indisponível.", status=404 if status == 404 else 502)

    def body():
        try:
            yield from upstream.iter_bytes(256 * 1024)
        finally:
            upstream.close()
            client.close()

    response = StreamingHttpResponse(body(), status=upstream.status_code, content_type="video/mp4")
    for header in ("Content-Length", "Content-Range"):
        if header in upstream.headers:
            response[header] = upstream.headers[header]
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, max-age=3600"
    return response


@login_required
@require_POST
def register_view(request, video_id):
    """Registra visualização / conclusão do treinamento pelo colaborador."""
    profile = get_profile(request.user)
    video = get_object_or_404(
        TrainingVideo, id=video_id, status=Status.COMPLETED, department__in=profile.visible_departments()
    )
    progress, _ = VideoProgress.objects.get_or_create(user=request.user, video=video)
    if request.POST.get('completed') == '1' and not progress.completed:
        progress.completed = True
        progress.completed_at = timezone.now()
        progress.save(update_fields=['completed', 'completed_at'])
    return JsonResponse({'status': 'ok', 'completed': progress.completed})


def login_view(request):
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = ''

    if request.user.is_authenticated:
        return redirect(next_url or 'home')

    if request.method == 'POST':
        user = authenticate(request, username=request.POST.get('username'), password=request.POST.get('password'))
        if user is not None:
            login(request, user)
            return redirect(next_url or 'home')
        messages.error(request, 'Usuário ou senha inválidos.')

    return render(request, 'treinamentos/login.html', {'next': next_url})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('login')
