"""
Alertas diarias por correo — equivalente a alertasDiariasJano() del Apps
Script (que llamaba a alertaServiciosCriticos() y alertaSubactividadesPorVencer()).

Pensado para ejecutarse una vez al día con una tarea programada de Plesk
("Scheduled Tasks"/cron), igual que el trigger diario de Apps Script:

    0 7 * * * /ruta/al/venv/bin/python manage.py alertas_diarias

Usa el mismo servidor SMTP que JANOTEC pero con la cuenta/mailbox que se
configure en EMAIL_HOST_USER del .env de este proyecto (una cuenta
distinta a la de JANOTEC, según lo pedido). Los destinatarios salen de
ALERTAS_DESTINATARIOS en el .env (equivalente a ALLOWED_USERS /
destinatariosAutorizados_() del Apps Script).
"""
from datetime import date, timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string

from nucleo.models import Actividad, ActivoCritico, Subactividad

ESTADOS_EN_ALERTA = ("Servicio con falla", "Pendiente revisión", "Revisar hoy")


class Command(BaseCommand):
    help = "Envía las alertas diarias de servicios críticos y subactividades por vencer."

    def add_arguments(self, parser):
        parser.add_argument(
            "--forzar", action="store_true",
            help="Envía el correo aunque no haya nada en alerta (para pruebas).",
        )

    def handle(self, *args, **options):
        forzar = options["forzar"]
        destinatarios = settings.ALERTAS_DESTINATARIOS
        enviados = 0

        # Las dos alertas "generales" (servicios críticos y subactividades)
        # sí dependen de la lista ALERTAS_DESTINATARIOS del .env.
        if not destinatarios:
            self.stdout.write(self.style.WARNING(
                "ALERTAS_DESTINATARIOS está vacío en el .env — no se envían las alertas "
                "generales de servicios críticos ni de subactividades."
            ))
        else:
            if self._alerta_servicios_criticos(destinatarios, forzar):
                enviados += 1
            if self._alerta_subactividades_por_vencer(destinatarios, forzar):
                enviados += 1

        # La alerta de actividades es personal (a cada dueño, con su propio
        # correo de usuario) y no depende de ALERTAS_DESTINATARIOS.
        enviados += self._alerta_actividades_por_vencer(forzar)

        self.stdout.write(self.style.SUCCESS(f"Alertas diarias: {enviados} correo(s) enviado(s)."))

    # -- Servicios críticos: con falla, pendientes de revisión o para hoy --------
    def _alerta_servicios_criticos(self, destinatarios, forzar):
        activos = [a for a in ActivoCritico.objects.all() if a.estado_validacion in ESTADOS_EN_ALERTA]
        if not activos and not forzar:
            return False

        hay_falla = any(a.estado_validacion == "Servicio con falla" for a in activos)
        asunto = (
            "🚨 CRÍTICO - Servicios TI requieren atención" if hay_falla
            else "📋 Recordatorio - Validación de Servicios TI"
        )
        cuerpo_html = render_to_string("nucleo/correo_servicios_criticos.html", {"activos": activos})
        self._enviar(asunto, cuerpo_html, destinatarios)
        self.stdout.write(f"  - Servicios críticos en alerta: {len(activos)}")
        return True

    # -- Subactividades con fecha de compromiso hoy (o dentro de la ventana) ----
    def _alerta_subactividades_por_vencer(self, destinatarios, forzar):
        hoy = date.today()
        limite = hoy + timedelta(days=settings.DIAS_ANTES_VENCIMIENTO)
        subactividades = Subactividad.objects.filter(
            fecha_fin__isnull=True,
            fecha_compromiso__isnull=False,
            fecha_compromiso__gte=hoy,
            fecha_compromiso__lte=limite,
        ).select_related("actividad")

        if not subactividades and not forzar:
            return False

        hay_hoy = any(s.fecha_compromiso == hoy for s in subactividades)
        asunto = (
            "🗓️ HOY - Subactividades con fecha de compromiso" if hay_hoy
            else "📋 Recordatorio - Subactividades por vencer"
        )
        cuerpo_html = render_to_string(
            "nucleo/correo_subactividades_por_vencer.html", {"subactividades": subactividades, "hoy": hoy}
        )
        self._enviar(asunto, cuerpo_html, destinatarios)
        self.stdout.write(f"  - Subactividades por vencer: {subactividades.count()}")
        return True

    # -- Actividades con fecha de compromiso vencida o a menos de una semana,
    #    que todavía no se han marcado como finalizadas. A diferencia de las
    #    otras dos alertas (que van a la lista general de ALERTAS_DESTINATARIOS),
    #    esta le llega a cada persona SOLO con sus propias actividades, usando
    #    el dueño real (creado_por_usuario) y el correo que tenga esa cuenta
    #    en /admin/ -> Usuarios. Si una actividad no tiene dueño asignado, o el
    #    dueño no tiene correo registrado, se avisa por consola pero no se
    #    manda nada (para no inventar destinatarios).
    def _alerta_actividades_por_vencer(self, forzar):
        hoy = date.today()
        limite = hoy + timedelta(days=7)
        actividades = Actividad.objects.filter(
            fecha_final__isnull=True,
            fecha_compromiso__isnull=False,
            fecha_compromiso__lte=limite,
        ).select_related("creado_por_usuario")

        if not actividades and not forzar:
            return 0

        por_usuario = {}
        sin_dueno_o_correo = []
        for a in actividades:
            usuario = a.creado_por_usuario
            if usuario and usuario.email:
                por_usuario.setdefault(usuario, []).append(a)
            else:
                sin_dueno_o_correo.append(a.id)

        if sin_dueno_o_correo:
            self.stdout.write(self.style.WARNING(
                "  - Actividades por vencer SIN dueño o sin correo registrado (no se "
                f"les pudo avisar a nadie): {', '.join(sin_dueno_o_correo)}"
            ))

        enviados = 0
        for usuario, propias in por_usuario.items():
            hay_vencida = any(a.fecha_compromiso < hoy for a in propias)
            asunto = (
                "🚨 Tienes actividades VENCIDAS por finalizar" if hay_vencida
                else "📋 Tienes actividades por vencer esta semana"
            )
            cuerpo_html = render_to_string(
                "nucleo/correo_actividades_por_vencer.html", {"actividades": propias, "hoy": hoy}
            )
            self._enviar(asunto, cuerpo_html, [usuario.email])
            enviados += 1
            self.stdout.write(
                f"  - Actividades por vencer para {usuario.get_full_name() or usuario.username} "
                f"({usuario.email}): {len(propias)}"
            )
        return enviados

    @staticmethod
    def _enviar(asunto, cuerpo_html, destinatarios):
        correo = EmailMultiAlternatives(
            subject=asunto,
            body="Este correo requiere un cliente que muestre HTML.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=destinatarios,
        )
        correo.attach_alternative(cuerpo_html, "text/html")
        correo.send(fail_silently=False)
