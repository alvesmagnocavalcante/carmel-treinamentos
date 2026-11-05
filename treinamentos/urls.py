from django.urls import path

from . import mcp_server, views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('fila/', views.queue_view, name='queue'),
    path('fila/<int:video_id>/revisar/', views.review_script_view, name='review_script'),
    path('fila/<int:video_id>/anexar-video/', views.attach_video_view, name='attach_video'),
    path('fila/<int:video_id>/reprocessar/', views.retry_video_view, name='retry_video'),
    path('api/sync-drive/', views.sync_drive_ajax, name='sync_drive'),
    path('video/<int:video_id>/arquivo/', views.stream_video_view, name='stream_video'),
    path('api/video/<int:video_id>/view/', views.register_view, name='register_view'),
    path('mcp/', mcp_server.mcp_endpoint, name='mcp'),
    path('mcp/<str:token>/', mcp_server.mcp_endpoint, name='mcp_token'),
    # sem a barra final (POST não pode ser redirecionado pelo APPEND_SLASH)
    path('mcp', mcp_server.mcp_endpoint),
    path('mcp/<str:token>', mcp_server.mcp_endpoint),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]
