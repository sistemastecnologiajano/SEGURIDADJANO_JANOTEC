"""Variables disponibles en TODOS los templates sin tener que pasarlas
a mano desde cada vista (ver settings.TEMPLATES -> context_processors)."""


def es_jefe(user):
    """¿Puede este usuario revisar/validar en el módulo Seguimiento?
    Regla: superusuario, o pertenece al grupo Django "Jefe" (se asigna
    desde el admin, Usuarios -> elegir usuario -> Grupos)."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name="Jefe").exists()


def puede_gestionar_activos(user):
    """¿Puede este usuario crear/editar Activos críticos? Regla: solo el
    Jefe, el grupo "Sistemas" (se asigna desde el admin, Usuarios -> elegir
    usuario -> Grupos) o el superusuario. A diferencia de Actividades, aquí
    NO importa quién creó el activo: es por rol, no por dueño individual."""
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=["Jefe", "Sistemas"]).exists()


def puede_editar(user, objeto):
    """¿Puede este usuario editar esta Actividad/Subactividad?
    Regla: el Jefe/superusuario puede editar cualquiera (para corregir o
    reasignar); cualquier otro usuario solo puede editar las que él mismo
    creó. Los registros ya existentes de antes de este cambio no tienen
    `creado_por_usuario` (quedó vacío porque no existía ese dato) — a esos,
    por compatibilidad, los puede seguir editando cualquiera, para no
    bloquear de golpe lo que ya estaba cargado."""
    if not getattr(user, "is_authenticated", False):
        return False
    if es_jefe(user):
        return True
    creador_id = getattr(objeto, "creado_por_usuario_id", None)
    if creador_id is None:
        return True
    return creador_id == user.id


def flags(request):
    ctx = {
        "es_jefe": es_jefe(request.user),
        "puede_gestionar_activos": puede_gestionar_activos(request.user),
    }
    if getattr(request.user, "is_authenticated", False):
        # Import tardío para evitar problemas de apps no cargadas todavía.
        from .models import Actividad, Validacion

        ctx["pendientes_seguimiento_nav"] = (
            Actividad.objects.exclude(estado_revision="Revisada").count()
            + Validacion.objects.exclude(estado_revision="Revisada").count()
        )
    return ctx
