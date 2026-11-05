"""
URL configuration for config project (Plataforma de Gestión TIC).
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from nucleo.views import EntrarView, SalirView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("cuenta/login/", EntrarView.as_view(), name="login"),
    path("cuenta/logout/", SalirView.as_view(), name="logout"),
    path("", include("nucleo.urls")),
]

# Los archivos de evidencia (imágenes/PDF subidos en Actividades,
# Subactividades y Validaciones) se sirven directo desde Django/Passenger,
# igual que ya se hace con los estáticos — no se configuró ningún Alias de
# Apache para /media/, así que esto tiene que estar activo siempre (no solo
# en DEBUG) para que las evidencias se puedan abrir en el servidor real.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
