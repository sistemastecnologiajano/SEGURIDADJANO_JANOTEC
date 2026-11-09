import calendar as calendar_mod
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView

from .context_processors import es_jefe, puede_editar, puede_gestionar_activos
from .forms import (
    ActividadForm,
    ActivoCriticoForm,
    AvanceSubactividadForm,
    DetalleProyectoForm,
    FormularioIngreso,
    IndicadorForm,
    RegistroIndicadorForm,
    RiesgoForm,
    RiesgosActividadForm,
    SubactividadForm,
    TareaCalendarioForm,
    ValidacionForm,
)
from .models import (
    Actividad,
    ActivoCritico,
    Auditoria,
    AvanceSubactividad,
    DetalleProyecto,
    Indicador,
    NoEliminable,
    RegistroIndicador,
    Riesgo,
    Subactividad,
    TareaCalendario,
    Validacion,
    registrar_auditoria,
)

# Orden de severidad para colorear/ordenar Activos Críticos: los más
# urgentes primero (Crítica/Alta -> rojo, Media -> naranja, Baja ->
# amarillo), tal como lo pidió el usuario.
_ORDEN_CRITICIDAD = {"Crítica": 0, "Alta": 0, "Media": 1, "Baja": 2}


def _clase_criticidad(criticidad):
    if criticidad in ("Crítica", "Alta"):
        return "fila-critica"
    if criticidad == "Media":
        return "fila-media"
    if criticidad == "Baja":
        return "fila-baja"
    return ""


class EntrarView(LoginView):
    template_name = "nucleo/login.html"
    authentication_form = FormularioIngreso


class SalirView(LogoutView):
    pass


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "nucleo/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        hoy = date.today()
        limite = hoy + timedelta(days=7)

        ctx["total_actividades"] = Actividad.objects.count()
        ctx["total_subactividades"] = Subactividad.objects.count()
        ctx["total_activos"] = ActivoCritico.objects.count()
        ctx["total_validaciones"] = Validacion.objects.count()
        ctx["total_proyectos"] = sum(1 for a in Actividad.objects.all() if a.es_proyecto)
        ctx["total_riesgos"] = Riesgo.objects.count()
        ctx["pendientes_seguimiento"] = (
            Actividad.objects.exclude(estado_revision="Revisada").count()
            + Validacion.objects.exclude(estado_revision="Revisada").count()
        )

        # Conteo simple por estado.
        conteo_estado = {}
        for valor in Actividad.objects.values_list("estado", flat=True):
            clave = valor or "(sin estado)"
            conteo_estado[clave] = conteo_estado.get(clave, 0) + 1
        ctx["conteo_actividades_por_estado"] = conteo_estado

        activos_en_alerta = [a for a in ActivoCritico.objects.all() if a.en_alerta]
        ctx["activos_en_alerta"] = activos_en_alerta

        ctx["proximas_validaciones"] = [
            a for a in ActivoCritico.objects.all()
            if a.proxima_validacion and hoy <= a.proxima_validacion <= limite
        ]

        ctx["subactividades_por_vencer"] = Subactividad.objects.filter(
            fecha_fin__isnull=True, fecha_compromiso__gte=hoy, fecha_compromiso__lte=limite
        ).order_by("fecha_compromiso")

        ctx["proyectos"] = [a for a in Actividad.objects.all() if a.es_proyecto][:5]
        return ctx


# ---------------------------------------------------------------------------
# Actividades
# ---------------------------------------------------------------------------
@login_required
def lista_actividades(request):
    qs = Actividad.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(nombre__icontains=q) | Q(id__icontains=q) | Q(responsable__icontains=q))
    solo_proyectos = request.GET.get("proyectos") == "1"
    if solo_proyectos:
        qs = [a for a in qs if a.es_proyecto]
    return render(request, "nucleo/actividad_lista.html", {
        "actividades": qs, "q": q, "solo_proyectos": solo_proyectos,
    })


@login_required
def detalle_actividad(request, pk):
    actividad = get_object_or_404(Actividad, pk=pk)
    return render(request, "nucleo/actividad_detalle.html", {
        "actividad": actividad,
        "subactividades": actividad.subactividades.all(),
    })


@login_required
def guardar_actividad(request, pk=None):
    actividad = get_object_or_404(Actividad, pk=pk) if pk else None
    if actividad is not None and not puede_editar(request.user, actividad):
        messages.error(
            request,
            "Esta actividad la creó otra persona, así que solo ella (o el Jefe) puede editarla.",
        )
        return redirect("actividad_detalle", pk=actividad.id)
    form = ActividadForm(request.POST or None, request.FILES or None, instance=actividad)
    riesgos_form = RiesgosActividadForm(
        request.POST or None,
        initial=RiesgosActividadForm.initial_desde(actividad),
    )
    if request.method == "POST" and form.is_valid() and riesgos_form.is_valid():
        es_nueva = actividad is None
        actividad = form.save(commit=False)
        if es_nueva:
            actividad.creado_por_usuario = request.user
        actividad.save()
        riesgos_form.guardar(actividad)
        registrar_auditoria(
            request.user, "CREAR" if es_nueva else "EDITAR", "Actividades", actividad.id,
            actividad.nombre,
        )
        messages.success(request, f"Actividad {actividad.id} guardada correctamente.")
        return redirect("actividad_detalle", pk=actividad.id)
    return render(request, "nucleo/actividad_form.html", {
        "form": form, "riesgos_form": riesgos_form, "actividad": actividad,
        "riesgos_catalogo": Riesgo.objects.order_by("codigo"),
    })


# ---------------------------------------------------------------------------
# Subactividades y su avance
# ---------------------------------------------------------------------------
@login_required
def lista_subactividades(request):
    qs = Subactividad.objects.select_related("actividad").all()
    actividad_id = request.GET.get("actividad", "").strip()
    if actividad_id:
        qs = qs.filter(actividad_id=actividad_id)
    return render(request, "nucleo/subactividad_lista.html", {
        "subactividades": qs, "actividad_id": actividad_id,
    })


@login_required
def detalle_subactividad(request, pk):
    sub = get_object_or_404(Subactividad, pk=pk)
    return render(request, "nucleo/subactividad_detalle.html", {
        "sub": sub, "avances": sub.avances.all(),
    })


@login_required
def guardar_subactividad(request, pk=None):
    sub = get_object_or_404(Subactividad, pk=pk) if pk else None
    if sub is not None and not puede_editar(request.user, sub):
        messages.error(
            request,
            "Esta subactividad la creó otra persona, así que solo ella (o el Jefe) puede editarla.",
        )
        return redirect("subactividad_detalle", pk=sub.id_detalle)
    origen = request.GET if request.method != "POST" else request.POST
    desde_tarea = origen.get("desde_tarea", "")
    if not sub:
        inicial = {
            "actividad": request.GET.get("actividad") or None,
            "nombre": request.GET.get("nombre") or None,
            "fecha_compromiso": request.GET.get("fecha_compromiso") or None,
            "responsable": request.GET.get("responsable") or None,
        }
        inicial = {k: v for k, v in inicial.items() if v} or None
    else:
        inicial = None
    form = SubactividadForm(request.POST or None, request.FILES or None, instance=sub, initial=inicial)
    if request.method == "POST" and form.is_valid():
        es_nueva = sub is None
        sub = form.save(commit=False)
        if es_nueva:
            sub.creado_por_usuario = request.user
        sub.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nueva else "EDITAR", "Subactividades", sub.id_detalle, sub.nombre,
        )
        # Viene de "Convertir a subactividad" en el Calendario: la tarea
        # original se marca como Hecha, con una nota de a cuál subactividad
        # quedó convertida (no se borra, para no perder el historial).
        if es_nueva and desde_tarea:
            tarea = TareaCalendario.objects.filter(pk=desde_tarea).first()
            if tarea:
                tarea.estado = TareaCalendario.Estado.HECHA
                tarea.completado_por = getattr(request.user, "email", "") or str(request.user)
                tarea.fecha_completado = timezone.now()
                nota = f"Convertida a subactividad {sub.id_detalle}."
                tarea.observacion = f"{tarea.observacion}\n{nota}".strip() if tarea.observacion else nota
                tarea.save()
        messages.success(request, f"Subactividad {sub.id_detalle} guardada correctamente.")
        return redirect("subactividad_detalle", pk=sub.id_detalle)
    return render(request, "nucleo/subactividad_form.html", {
        "form": form, "sub": sub, "desde_tarea": desde_tarea,
    })


@login_required
def eliminar_subactividad(request, pk):
    sub = get_object_or_404(Subactividad, pk=pk)
    actividad_id = sub.actividad_id
    if not puede_editar(request.user, sub):
        messages.error(
            request,
            "Esta subactividad la creó otra persona, así que solo ella (o el Jefe) puede eliminarla.",
        )
        return redirect(f"{reverse_lazy('subactividad_lista')}?actividad={actividad_id}")
    if request.method == "POST":
        registrar_auditoria(request.user, "ELIMINAR", "Subactividades", sub.id_detalle, sub.nombre)
        sub.delete()
        messages.success(request, "Subactividad eliminada.")
        return redirect(f"{reverse_lazy('subactividad_lista')}?actividad={actividad_id}")
    return render(request, "nucleo/confirmar_eliminar.html", {"objeto": sub})


@login_required
def guardar_avance_subactividad(request, sub_pk):
    sub = get_object_or_404(Subactividad, pk=sub_pk)
    form = AvanceSubactividadForm(request.POST or None, request.FILES or None, initial={"fecha_avance": date.today()})
    if request.method == "POST" and form.is_valid():
        avance = form.save(commit=False)
        avance.subactividad = sub
        avance.save()
        registrar_auditoria(request.user, "CREAR", "Avance subactividad", avance.id_avance, sub.nombre)
        messages.success(request, "Avance registrado.")
        return redirect("subactividad_detalle", pk=sub.id_detalle)
    return render(request, "nucleo/avance_form.html", {"form": form, "sub": sub})


# ---------------------------------------------------------------------------
# Activos críticos y validaciones
# ---------------------------------------------------------------------------
@login_required
def lista_activos(request):
    qs = ActivoCritico.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(servicio__icontains=q) | Q(id_servicio__icontains=q))

    # Orden: primero los que requieren atención (en_alerta = sin revisar /
    # con falla / vencidos), luego por criticidad (Crítica y Alta primero),
    # y dentro de eso por nombre. en_alerta/criticidad son propiedades de
    # Python, no columnas, así que el orden se arma aquí en memoria.
    activos = list(qs)
    for a in activos:
        a.clase_criticidad = _clase_criticidad(a.criticidad)
    activos.sort(
        key=lambda a: (
            0 if a.en_alerta else 1,
            _ORDEN_CRITICIDAD.get(a.criticidad, 3),
            a.servicio,
        )
    )
    return render(request, "nucleo/activo_lista.html", {"activos": activos, "q": q})


@login_required
def detalle_activo(request, pk):
    activo = get_object_or_404(ActivoCritico, pk=pk)
    return render(request, "nucleo/activo_detalle.html", {
        "activo": activo, "validaciones": activo.validaciones.all(),
    })


@login_required
def guardar_activo(request, pk=None):
    if not puede_gestionar_activos(request.user):
        messages.error(
            request,
            "Solo el Jefe, el equipo de Sistemas o un administrador pueden agregar o editar activos críticos.",
        )
        return redirect("activo_lista")
    activo = get_object_or_404(ActivoCritico, pk=pk) if pk else None
    form = ActivoCriticoForm(request.POST or None, instance=activo)
    if request.method == "POST" and form.is_valid():
        es_nuevo = activo is None
        activo = form.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nuevo else "EDITAR", "Activos críticos",
            activo.id_servicio, activo.servicio,
        )
        messages.success(request, f"Activo {activo.id_servicio} guardado correctamente.")
        return redirect("activo_detalle", pk=activo.id_servicio)
    return render(request, "nucleo/activo_form.html", {"form": form, "activo": activo})


@login_required
def guardar_validacion(request, pk=None):
    validacion = get_object_or_404(Validacion, pk=pk) if pk else None
    activo_id = request.GET.get("activo")
    inicial = {"activo": activo_id, "fecha_validacion": date.today()} if activo_id and not validacion else None
    form = ValidacionForm(request.POST or None, request.FILES or None, instance=validacion, initial=inicial)
    if request.method == "POST" and form.is_valid():
        es_nueva = validacion is None
        validacion = form.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nueva else "EDITAR", "Validaciones",
            validacion.id_validacion, str(validacion.activo),
        )
        messages.success(request, f"Validación {validacion.id_validacion} guardada correctamente.")
        return redirect("activo_detalle", pk=validacion.activo_id)
    return render(request, "nucleo/validacion_form.html", {"form": form, "validacion": validacion})


# ---------------------------------------------------------------------------
# Proyectos (son Actividades con es_proyecto == True, más su ficha)
# ---------------------------------------------------------------------------
@login_required
def lista_proyectos(request):
    proyectos = [a for a in Actividad.objects.all() if a.es_proyecto]
    return render(request, "nucleo/proyecto_lista.html", {"proyectos": proyectos})


@login_required
def detalle_proyecto(request, pk):
    proyecto = get_object_or_404(Actividad, pk=pk)
    subactividades = proyecto.subactividades.all()
    activos = proyecto.activos_asociados.all()
    conteo_sub = {"finalizado": 0, "en_proceso": 0, "no_iniciado": 0}
    for s in subactividades:
        if s.fecha_fin:
            conteo_sub["finalizado"] += 1
        elif s.avance_pct:
            conteo_sub["en_proceso"] += 1
        else:
            conteo_sub["no_iniciado"] += 1
    return render(request, "nucleo/proyecto_detalle.html", {
        "proyecto": proyecto,
        "subactividades": subactividades,
        "activos": activos,
        "conteo_sub": conteo_sub,
        "ficha": getattr(proyecto, "ficha", None),
    })


@login_required
def guardar_ficha_proyecto(request, pk):
    proyecto = get_object_or_404(Actividad, pk=pk)
    ficha = getattr(proyecto, "ficha", None)
    form = DetalleProyectoForm(request.POST or None, instance=ficha)
    if request.method == "POST" and form.is_valid():
        ficha = form.save(commit=False)
        ficha.proyecto = proyecto
        ficha.actualizado_por = getattr(request.user, "email", "") or str(request.user)
        ficha.save()
        registrar_auditoria(request.user, "EDITAR", "Ficha de proyecto", proyecto.id, proyecto.nombre)
        messages.success(request, "Ficha del proyecto actualizada.")
        return redirect("proyecto_detalle", pk=proyecto.id)
    return render(request, "nucleo/ficha_proyecto_form.html", {"form": form, "proyecto": proyecto})


# ---------------------------------------------------------------------------
# Validaciones — hoja general de seguimiento (todas las validaciones de
# todos los activos, en una sola vista filtrable/ordenable, independiente
# de entrar activo por activo).
# ---------------------------------------------------------------------------
@login_required
def lista_validaciones(request):
    qs = Validacion.objects.select_related("activo").all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(activo__servicio__icontains=q)
            | Q(id_validacion__icontains=q)
            | Q(responsable__icontains=q)
        )
    resultado = request.GET.get("resultado", "").strip()
    if resultado:
        qs = qs.filter(resultado=resultado)
    resultados_disponibles = (
        Validacion.objects.exclude(resultado="").values_list("resultado", flat=True).distinct()
    )
    return render(request, "nucleo/validacion_lista.html", {
        "validaciones": qs, "q": q, "resultado": resultado,
        "resultados_disponibles": sorted(set(resultados_disponibles)),
    })


# ---------------------------------------------------------------------------
# Seguimiento — el jefe revisa y da validez a actividades y validaciones
# (equivalente al "botón de revisar" del Apps Script). Solo usuarios del
# grupo "Jefe" (o superusuarios) ven/pueden usar el botón Revisar.
# ---------------------------------------------------------------------------
@login_required
def seguimiento(request):
    tab = request.GET.get("tab", "pendientes")
    q = request.GET.get("q", "").strip()

    actividades = Actividad.objects.all()
    validaciones = Validacion.objects.select_related("activo").all()

    if q:
        actividades = actividades.filter(Q(nombre__icontains=q) | Q(id__icontains=q))
        validaciones = validaciones.filter(
            Q(activo__servicio__icontains=q) | Q(id_validacion__icontains=q)
        )

    if tab == "revisadas":
        actividades = actividades.filter(estado_revision="Revisada")
        validaciones = validaciones.filter(estado_revision="Revisada")
    else:
        tab = "pendientes"
        actividades = actividades.exclude(estado_revision="Revisada")
        validaciones = validaciones.exclude(estado_revision="Revisada")

    return render(request, "nucleo/seguimiento.html", {
        "actividades": actividades,
        "validaciones": validaciones,
        "tab": tab,
        "q": q,
        "actividades_sin_revisar": Actividad.objects.exclude(estado_revision="Revisada").count(),
        "validaciones_sin_revisar": Validacion.objects.exclude(estado_revision="Revisada").count(),
    })


def _marcar_revision(request, obj, modulo, etiqueta, url_regreso):
    if not es_jefe(request.user):
        messages.error(request, "Solo el jefe (grupo \"Jefe\") puede revisar registros.")
        return redirect(url_regreso)
    if request.method == "POST":
        if obj.estado_revision == "Revisada":
            obj.estado_revision = ""
            obj.revisado_por = ""
            obj.fecha_revision = None
        else:
            obj.estado_revision = "Revisada"
            obj.revisado_por = getattr(request.user, "email", "") or str(request.user)
            obj.fecha_revision = timezone.localdate()
        obj.save()
        registrar_auditoria(
            request.user, "EDITAR", modulo, str(obj.pk), f"revisión -> {obj.estado_revision or 'pendiente'}"
        )
        messages.success(request, f"{etiqueta} actualizada.")
    return redirect(url_regreso)


@login_required
def revisar_actividad(request, pk):
    actividad = get_object_or_404(Actividad, pk=pk)
    return _marcar_revision(
        request, actividad, "Actividades", f"Revisión de {actividad.id}",
        f"{reverse_lazy('seguimiento')}?tab={request.GET.get('tab', 'pendientes')}",
    )


@login_required
def revisar_validacion(request, pk):
    validacion = get_object_or_404(Validacion, pk=pk)
    return _marcar_revision(
        request, validacion, "Validaciones", f"Revisión de {validacion.id_validacion}",
        f"{reverse_lazy('seguimiento')}?tab={request.GET.get('tab', 'pendientes')}",
    )


# ---------------------------------------------------------------------------
# Gestión de riesgos — riesgos como registros reales (vienen de la matriz
# de riesgos / DOFA externa, se cargan aquí a mano a propósito).
# ---------------------------------------------------------------------------
@login_required
def lista_riesgos(request):
    qs = Riesgo.objects.all()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
    return render(request, "nucleo/riesgo_lista.html", {"riesgos": qs, "q": q})


@login_required
def detalle_riesgo(request, pk):
    riesgo = get_object_or_404(Riesgo, pk=pk)
    return render(request, "nucleo/riesgo_detalle.html", {
        "riesgo": riesgo, "actividades": riesgo.actividades,
    })


@login_required
def guardar_riesgo(request, pk=None):
    riesgo = get_object_or_404(Riesgo, pk=pk) if pk else None
    form = RiesgoForm(request.POST or None, instance=riesgo)
    if request.method == "POST" and form.is_valid():
        es_nuevo = riesgo is None
        riesgo = form.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nuevo else "EDITAR", "Gestión de riesgos",
            riesgo.codigo, riesgo.nombre,
        )
        messages.success(request, f"Riesgo {riesgo.codigo} guardado correctamente.")
        return redirect("riesgo_detalle", pk=riesgo.codigo)
    return render(request, "nucleo/riesgo_form.html", {"form": form, "riesgo": riesgo})


# ---------------------------------------------------------------------------
# Indicadores — catálogo configurable + registros periódicos. Solo
# Jefe/Sistemas/superusuario pueden crear indicadores nuevos o registrar/
# editar los valores de cada periodo (misma regla que Activos Críticos);
# cualquier usuario autenticado puede VER el catálogo y su historial.
# ---------------------------------------------------------------------------
@login_required
def lista_indicadores(request):
    indicadores = Indicador.objects.filter(activo=True)
    tarjetas = []
    for indicador in indicadores:
        anio, periodo = indicador.periodo_actual()
        registro = RegistroIndicador.objects.filter(
            indicador=indicador, anio=anio, periodo=periodo
        ).first()
        es_periodo_actual = True
        if registro is None:
            # Si no hay nada registrado todavía para el periodo de HOY, se
            # muestra el último registro que sí exista (por ejemplo, si ya
            # cargaste el Trimestre 1 pero hoy estamos en el Trimestre 4),
            # dejando claro de qué periodo es, en vez de decir "sin registro"
            # cuando en realidad sí hay datos cargados.
            registro = indicador.registros.first()  # ordering = -anio, -periodo
            es_periodo_actual = False
        tarjetas.append({
            "indicador": indicador,
            "registro_actual": registro,
            "es_periodo_actual": es_periodo_actual,
            "anio_actual": anio,
            "periodo_actual": periodo,
        })
    return render(request, "nucleo/indicador_lista.html", {"tarjetas": tarjetas})


@login_required
def detalle_indicador(request, pk):
    indicador = get_object_or_404(Indicador, pk=pk)
    registros = indicador.registros.all()
    contexto = {"indicador": indicador, "registros": registros}

    if indicador.tipo == Indicador.Tipo.AUTO_ACTIVOS_CRITICOS:
        anio_actual, periodo_actual = indicador.periodo_actual()
        try:
            anio = int(request.GET.get("anio", anio_actual))
        except (TypeError, ValueError):
            anio = anio_actual
        mes_individual = request.GET.get("mes")
        if mes_individual:
            # Vista de un solo mes (para que un auditor revise un mes
            # puntual en vez del trimestre completo).
            try:
                mes = int(mes_individual)
            except (TypeError, ValueError):
                mes = date.today().month
            vista = indicador.detalle_mes_activos_criticos(anio, mes)
            vista["es_mes_individual"] = True
            vista["anio"] = anio
        else:
            try:
                periodo = int(request.GET.get("periodo", periodo_actual))
            except (TypeError, ValueError):
                periodo = periodo_actual
            vista = indicador.detalle_activos_criticos(anio, periodo)
            vista["es_mes_individual"] = False
            vista["anio"] = anio
            vista["periodo"] = periodo
        nombres_mes = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
            "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ]
        contexto["vista"] = vista
        contexto["anio_seleccionado"] = anio
        contexto["anios_disponibles"] = range(anio_actual - 2, anio_actual + 1)
        contexto["meses_opciones"] = [
            {"numero": n, "nombre": nombre, "seleccionado": vista["es_mes_individual"] and n == vista.get("mes")}
            for n, nombre in enumerate(nombres_mes, start=1)
        ]

        # Resumen por servicio para la gráfica de barras (% de casillas
        # cumplidas de ese activo dentro de la vista actual, sea un mes
        # suelto o el periodo completo) y para armar la tabla tipo Looker.
        resumen_por_servicio = []
        filas_tabla = []
        faltantes = []
        if vista["es_mes_individual"]:
            for f in vista["filas"]:
                if not f["aplica"]:
                    continue
                pct = 100.0 if f["cumplido"] else 0.0
                resumen_por_servicio.append({"activo": f["activo"], "pct": pct, "cantidad": f["cantidad"]})
                nombre_mes = nombres_mes[vista["mes"] - 1]
                filas_tabla.append({
                    "activo": f["activo"], "anio": vista["anio"], "nombre_mes": nombre_mes,
                    "cantidad": f["cantidad"], "cumplido": f["cumplido"],
                })
                if not f["cumplido"]:
                    faltantes.append(f"{f['activo'].servicio} ({nombre_mes} {vista['anio']})")
        else:
            for fila in vista["filas"]:
                aplicables = [c for c in fila["celdas"] if c["aplica"]]
                if not aplicables:
                    continue
                cumplidos = sum(1 for c in aplicables if c["cumplido"])
                pct = round(cumplidos / len(aplicables) * 100, 1)
                cantidad_total = sum(c["cantidad"] for c in aplicables)
                resumen_por_servicio.append({"activo": fila["activo"], "pct": pct, "cantidad": cantidad_total})
                for c in aplicables:
                    nombre_mes = nombres_mes[c["mes"] - 1]
                    filas_tabla.append({
                        "activo": fila["activo"], "anio": c["anio"], "nombre_mes": nombre_mes,
                        "cantidad": c["cantidad"], "cumplido": c["cumplido"],
                    })
                    if not c["cumplido"]:
                        faltantes.append(f"{fila['activo'].servicio} ({nombre_mes} {c['anio']})")
        resumen_por_servicio.sort(key=lambda r: r["activo"].servicio)
        filas_tabla.sort(key=lambda r: (r["activo"].servicio, r["anio"]))
        contexto["resumen_por_servicio"] = resumen_por_servicio
        contexto["filas_tabla"] = filas_tabla
        contexto["faltantes_texto"] = faltantes
        contexto["cumplimiento_pct_vista"] = (
            min(100, round(vista["valor"] / vista["meta"] * 100, 1)) if vista.get("meta") else None
        )

    elif indicador.tipo == Indicador.Tipo.AUTO_CONTINUIDAD_OPERATIVA:
        anio_actual, periodo_actual = indicador.periodo_actual()
        try:
            anio = int(request.GET.get("anio", anio_actual))
        except (TypeError, ValueError):
            anio = anio_actual
        try:
            periodo = int(request.GET.get("periodo", periodo_actual))
        except (TypeError, ValueError):
            periodo = periodo_actual
        vista = indicador.detalle_continuidad_operativa(anio, periodo)
        contexto["vista"] = vista
        contexto["anio_seleccionado"] = anio
        contexto["periodo_seleccionado"] = periodo
        contexto["anios_disponibles"] = range(anio_actual - 2, anio_actual + 1)

    elif indicador.tipo in (
        Indicador.Tipo.AUTO_SUBACTIVIDADES_PROYECTO, Indicador.Tipo.AUTO_SEGUIMIENTO_PROVEEDORES,
    ):
        anio_actual, periodo_actual = indicador.periodo_actual()
        try:
            anio = int(request.GET.get("anio", anio_actual))
        except (TypeError, ValueError):
            anio = anio_actual
        try:
            periodo = int(request.GET.get("periodo", periodo_actual))
        except (TypeError, ValueError):
            periodo = periodo_actual
        if indicador.tipo == Indicador.Tipo.AUTO_SUBACTIVIDADES_PROYECTO:
            vista = indicador.detalle_subactividades_proyecto(anio, periodo)
        else:
            vista = indicador.detalle_seguimiento_proveedores(anio, periodo)
        contexto["vista"] = vista
        contexto["anio_seleccionado"] = anio
        contexto["periodo_seleccionado"] = periodo
        contexto["anios_disponibles"] = range(anio_actual - 2, anio_actual + 1)
        contexto["cumplimiento_pct_vista"] = (
            min(100, round(vista["valor"] / vista["meta"] * 100, 1)) if vista.get("meta") else None
        )

    return render(request, "nucleo/indicador_detalle.html", contexto)


@login_required
def guardar_indicador(request, pk=None):
    if not puede_gestionar_activos(request.user):
        messages.error(request, "No tienes permiso para crear o editar indicadores.")
        return redirect("indicador_lista")
    indicador = get_object_or_404(Indicador, pk=pk) if pk else None
    form = IndicadorForm(request.POST or None, instance=indicador)
    if request.method == "POST" and form.is_valid():
        es_nuevo = indicador is None
        indicador = form.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nuevo else "EDITAR", "Indicadores",
            str(indicador.pk), indicador.nombre,
        )
        messages.success(request, f'Indicador "{indicador.nombre}" guardado correctamente.')
        return redirect("indicador_detalle", pk=indicador.pk)
    return render(request, "nucleo/indicador_form.html", {"form": form, "indicador": indicador})


@login_required
def guardar_registro_indicador(request, pk, registro_pk=None):
    indicador = get_object_or_404(Indicador, pk=pk)
    if not puede_gestionar_activos(request.user):
        messages.error(request, "No tienes permiso para registrar valores de indicadores.")
        return redirect("indicador_detalle", pk=indicador.pk)
    registro = (
        get_object_or_404(RegistroIndicador, pk=registro_pk, indicador=indicador)
        if registro_pk else None
    )
    if registro is None:
        anio, periodo = indicador.periodo_actual()
        registro = RegistroIndicador(indicador=indicador, anio=anio, periodo=periodo)
    form = RegistroIndicadorForm(request.POST or None, instance=registro, indicador=indicador)
    if request.method == "POST" and form.is_valid():
        es_nuevo = registro.pk is None
        registro = form.save(commit=False)
        registro.indicador = indicador
        if es_nuevo:
            registro.creado_por_usuario = request.user
        registro.save()
        registrar_auditoria(
            request.user, "CREAR" if es_nuevo else "EDITAR", "Indicadores",
            indicador.nombre, registro.etiqueta_periodo,
        )
        messages.success(request, "Registro del indicador guardado correctamente.")
        return redirect("indicador_detalle", pk=indicador.pk)
    return render(request, "nucleo/registro_indicador_form.html", {
        "form": form, "indicador": indicador, "registro": registro,
    })


# ---------------------------------------------------------------------------
# Calendario — grilla mensual estilo Google Calendar
# ---------------------------------------------------------------------------
@login_required
def lista_calendario(request):
    hoy = date.today()
    try:
        anio = int(request.GET.get("anio", hoy.year))
        mes = int(request.GET.get("mes", hoy.month))
        date(anio, mes, 1)
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month

    cal = calendar_mod.Calendar(firstweekday=0)  # lunes primero
    semanas_fechas = cal.monthdatescalendar(anio, mes)

    primer_dia = semanas_fechas[0][0]
    ultimo_dia = semanas_fechas[-1][-1]
    tareas_rango = TareaCalendario.objects.filter(fecha__gte=primer_dia, fecha__lte=ultimo_dia)
    tareas_por_fecha = {}
    for t in tareas_rango:
        tareas_por_fecha.setdefault(t.fecha, []).append({
            "id": t.id, "titulo": t.titulo, "fecha": t.fecha, "responsable": t.responsable,
            "estado": t.estado, "vencida": t.vencida, "url": reverse("calendario_editar", args=[t.id]),
            "tipo": "tarea", "color_fondo": None,
        })

    # Eventos automáticos — no se guardan aparte, se leen en vivo de lo que ya
    # existe (igual que la alerta diaria por correo), para no duplicar datos
    # ni tener que mantenerlos sincronizados a mano:
    #  - Próxima validación de cada Activo Crítico.
    #  - Actividades y Subactividades con fecha de compromiso, que todavía no
    #    estén en estado "Finalizado".
    for a in ActivoCritico.objects.exclude(frecuencia_validacion=""):
        f = a.proxima_validacion
        if f and primer_dia <= f <= ultimo_dia:
            tareas_por_fecha.setdefault(f, []).append({
                "titulo": f"Revisar: {a.servicio}", "fecha": f, "responsable": a.responsable,
                "estado": a.estado_validacion, "vencida": f < hoy,
                "url": reverse("activo_detalle", args=[a.id_servicio]),
                "tipo": "validacion", "color_fondo": "#e3f2fd",
            })

    actividades_pend = Actividad.objects.filter(
        fecha_compromiso__gte=primer_dia, fecha_compromiso__lte=ultimo_dia,
    ).exclude(estado="Finalizado")
    for act in actividades_pend:
        tareas_por_fecha.setdefault(act.fecha_compromiso, []).append({
            "titulo": f"Actividad: {act.nombre}", "fecha": act.fecha_compromiso, "responsable": act.responsable,
            "estado": act.estado or "Sin estado", "vencida": act.fecha_compromiso < hoy,
            "url": reverse("actividad_detalle", args=[act.id]),
            "tipo": "actividad", "color_fondo": "#fff3cd",
        })

    subactividades_pend = Subactividad.objects.filter(
        fecha_compromiso__gte=primer_dia, fecha_compromiso__lte=ultimo_dia,
    ).exclude(estado="Finalizado").select_related("actividad")
    for sub in subactividades_pend:
        tareas_por_fecha.setdefault(sub.fecha_compromiso, []).append({
            "titulo": f"Subactividad: {sub.nombre}", "fecha": sub.fecha_compromiso, "responsable": sub.responsable,
            "estado": sub.estado or "Sin estado", "vencida": sub.fecha_compromiso < hoy,
            "url": reverse("subactividad_detalle", args=[sub.id_detalle]),
            "tipo": "subactividad", "color_fondo": "#fde2e2",
        })

    semanas = [
        [
            {
                "fecha": f,
                "en_mes": f.month == mes,
                "es_hoy": f == hoy,
                "tareas": tareas_por_fecha.get(f, []),
            }
            for f in semana
        ]
        for semana in semanas_fechas
    ]

    mes_anterior = (anio, mes - 1) if mes > 1 else (anio - 1, 12)
    mes_siguiente = (anio, mes + 1) if mes < 12 else (anio + 1, 1)

    return render(request, "nucleo/calendario_lista.html", {
        "semanas": semanas,
        "nombre_mes": calendar_mod.month_name[mes].capitalize(),
        "anio": anio,
        "mes": mes,
        "mes_anterior": mes_anterior,
        "mes_siguiente": mes_siguiente,
        "dias_semana": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
        "hoy": hoy,
    })


@login_required
def guardar_tarea_calendario(request, pk=None):
    tarea = get_object_or_404(TareaCalendario, pk=pk) if pk else None
    form = TareaCalendarioForm(request.POST or None, instance=tarea)
    if request.method == "POST" and form.is_valid():
        es_nueva = tarea is None
        tarea = form.save(commit=False)
        if es_nueva:
            tarea.creado_por = getattr(request.user, "email", "") or str(request.user)
        tarea.save()
        registrar_auditoria(request.user, "CREAR" if es_nueva else "EDITAR", "Calendario", tarea.id, tarea.titulo)
        messages.success(request, "Tarea guardada.")
        return redirect("calendario_lista")
    return render(request, "nucleo/calendario_form.html", {"form": form, "tarea": tarea})


@login_required
def marcar_tarea_calendario(request, pk):
    tarea = get_object_or_404(TareaCalendario, pk=pk)
    if request.method == "POST":
        if tarea.estado == TareaCalendario.Estado.PENDIENTE:
            tarea.estado = TareaCalendario.Estado.HECHA
            tarea.completado_por = getattr(request.user, "email", "") or str(request.user)
            from django.utils import timezone
            tarea.fecha_completado = timezone.now()
        else:
            tarea.estado = TareaCalendario.Estado.PENDIENTE
            tarea.completado_por = ""
            tarea.fecha_completado = None
        tarea.save()
        registrar_auditoria(request.user, "EDITAR", "Calendario", tarea.id, f"estado -> {tarea.estado}")
    return redirect("calendario_lista")


# ---------------------------------------------------------------------------
# Auditoría (solo lectura)
# ---------------------------------------------------------------------------
@login_required
def lista_auditoria(request):
    registros = Auditoria.objects.all()[:300]
    return render(request, "nucleo/auditoria_lista.html", {"registros": registros})
