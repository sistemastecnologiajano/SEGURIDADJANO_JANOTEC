"""
Asigna como "creador" (dueño, para efectos de quién puede editar) a TODAS
las Actividades y Subactividades que todavía no tienen uno asignado —
es decir, las que ya existían antes de que este control de permisos
existiera.

Es seguro correrlo varias veces: nunca toca un registro que ya tenga
dueño asignado, solo rellena los que están vacíos.

Uso:
    python manage.py asignar_dueno_antiguos y.prada
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from nucleo.models import Actividad, Subactividad


class Command(BaseCommand):
    help = "Asigna un usuario como dueño de las Actividades/Subactividades antiguas que no tienen dueño."

    def add_arguments(self, parser):
        parser.add_argument(
            "usuario",
            help="Nombre de usuario (el mismo con el que esa persona inicia sesión) al que se le "
            "asignarán como propias todas las actividades/subactividades que hoy no tienen dueño.",
        )

    def handle(self, *args, **options):
        username = options["usuario"]
        try:
            usuario = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(
                f'No existe ningún usuario con el nombre de usuario "{username}". '
                "Revisa en /admin/ -> Usuarios el nombre exacto con el que inicia sesión."
            )

        actividades = Actividad.objects.filter(creado_por_usuario__isnull=True)
        subactividades = Subactividad.objects.filter(creado_por_usuario__isnull=True)
        n_act = actividades.count()
        n_sub = subactividades.count()

        actividades.update(creado_por_usuario=usuario)
        subactividades.update(creado_por_usuario=usuario)

        self.stdout.write(self.style.SUCCESS(
            f'Listo: se asignaron {n_act} actividades y {n_sub} subactividades (las que no tenían '
            f'dueño) a "{usuario.get_full_name() or usuario.username}". A partir de ahora solo esa '
            "persona (o el Jefe) puede editarlas."
        ))
