"""
Modelos de la Plataforma de Gestión TIC (gestiontic.seguridadjano.com).

Migrado desde el proyecto de Google Sheets + Apps Script "PLAN_DE_GESTIÓN_TI".
Cada modelo corresponde a una hoja del Excel original; en los comentarios de
cada clase se indica de cuál hoja viene, para poder volver a consultar el
Apps Script original si hace falta aclarar una regla de negocio.

Reglas generales heredadas del Apps Script (no cambiarlas sin avisar al
usuario, son decisiones de política explícitas del proyecto original):
  - Actividades, Activos Críticos y Validaciones NUNCA se eliminan (se
    conservan para auditoría) — se cambia su ESTADO en vez de borrarlos.
  - Las "subactividades por vencer" y los "servicios críticos con falla o
    pendientes" se avisan por correo (ver nucleo/alertas.py).
  - Un "proyecto" es cualquier Actividad cuyo nombre empiece con la palabra
    PROYECTO (sin importar mayúsculas/tildes en el resto del texto).
"""
import calendar
import re
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Coalesce
from django.utils import timezone


# ---------------------------------------------------------------------------
# Generador de IDs consecutivos tipo "TI-001", "SER-003", "VAL-0012", etc.
# Replica nextId_() del Apps Script: busca el número más alto ya usado con
# ese prefijo en esa tabla y le suma 1. Funciona aunque haya huecos (IDs
# borrados a mano en algún momento) porque no depende de un contador aparte.
# ---------------------------------------------------------------------------
def generar_siguiente_id(modelo, prefijo, longitud_relleno, campo_pk="pk"):
    maximo = 0
    for valor in modelo.objects.values_list(campo_pk, flat=True):
        coincidencia = re.search(r"(\d+)$", str(valor))
        if coincidencia:
            numero = int(coincidencia.group(1))
            if numero > maximo:
                maximo = numero
    return f"{prefijo}{str(maximo + 1).zfill(longitud_relleno)}"


class NoEliminable(Exception):
    """Se lanza cuando se intenta borrar un registro con política de
    auditoría (igual que los `throw new Error(...)` de deleteActividad(),
    deleteActivoCritico() y deleteValidacion() en el Apps Script)."""


# ---------------------------------------------------------------------------
# LISTAS — catálogos de valores para los <select> de los formularios.
# En el Sheet original eran columnas sueltas de la hoja "LISTAS" que
# cualquiera podía alimentar escribiendo un valor nuevo debajo del
# encabezado. Aquí es una sola tabla categoría/valor, editable desde el
# admin de Django sin tocar código ni hacer una migración nueva.
# ---------------------------------------------------------------------------
class ListaValor(models.Model):
    class Categoria(models.TextChoices):
        LINEA_GESTION = "LINEA_GESTION", "Línea de gestión"
        ESTADO_ACTIVIDAD = "ESTADO_ACTIVIDAD", "Estado de actividad"
        TIPO_GESTION = "TIPO_GESTION", "Tipo de gestión"
        RESPONSABLE = "RESPONSABLE", "Responsable"
        CARGO = "CARGO", "Cargo"
        TIPO_VALIDACION = "TIPO_VALIDACION", "Tipo de validación"
        RESULTADO_VALIDACION = "RESULTADO_VALIDACION", "Resultado de validación"
        PRIORIDAD = "PRIORIDAD", "Prioridad"
        ESTADO_REVISION = "ESTADO_REVISION", "Estado de revisión"
        CODIGO_RIESGO = "CODIGO_RIESGO", "Código de riesgo"
        CUMPLIMIENTO = "CUMPLIMIENTO", "Cumplimiento"
        CATEGORIA_ACTIVO = "CATEGORIA_ACTIVO", "Categoría de activo/servicio"
        CRITICIDAD = "CRITICIDAD", "Criticidad"
        FRECUENCIA_VALIDACION = "FRECUENCIA_VALIDACION", "Frecuencia de validación"
        TIPO_SERVICIO = "TIPO_SERVICIO", "Tipo de servicio (interno/proveedor)"
        PROVEEDOR = "PROVEEDOR", "Proveedor"
        UBICACION = "UBICACION", "Ubicación del activo/servicio"
        ESTADO_SUBACTIVIDAD = "ESTADO_SUBACTIVIDAD", "Estado de subactividad"

    categoria = models.CharField(max_length=40, choices=Categoria.choices)
    valor = models.CharField(max_length=150)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Valor de lista"
        verbose_name_plural = "Listas (catálogos)"
        ordering = ["categoria", "orden", "valor"]
        constraints = [
            models.UniqueConstraint(fields=["categoria", "valor"], name="lista_categoria_valor_unica")
        ]

    def __str__(self):
        return f"{self.get_categoria_display()}: {self.valor}"

    @staticmethod
    def opciones(categoria):
        return list(
            ListaValor.objects.filter(categoria=categoria).values_list("valor", flat=True)
        )


# Días de cadencia por frecuencia, para calcular próxima validación e
# indicadores. "Evento" no tiene cadencia fija (igual que en el Apps
# Script: queda fuera del cálculo de brecha de validaciones).
CICLOS_DIAS_POR_FRECUENCIA = {
    "Diario": 1,
    "Semanal": 7,
    "Mensual": 30,
    "Trimestral": 90,
    "Semestral": 180,
    "Anual": 365,
}
CRITICIDADES_INDICADOR = ["Crítica", "Alta"]


# ---------------------------------------------------------------------------
# AUDITORÍA — bitácora de quién hizo qué y cuándo (hoja "AUDITORÍA").
# ---------------------------------------------------------------------------
class Auditoria(models.Model):
    # default=timezone.now (en vez de auto_now_add=True) para poder preservar
    # las fechas reales al importar el histórico de auditoría del Excel; en
    # el uso normal de la app se comporta igual (se llena solo).
    fecha_hora = models.DateTimeField(default=timezone.now)
    usuario = models.CharField(max_length=150, blank=True)
    accion = models.CharField(max_length=50)
    modulo = models.CharField(max_length=100)
    id_registro = models.CharField(max_length=50, blank=True)
    detalle = models.TextField(blank=True)

    class Meta:
        verbose_name = "Registro de auditoría"
        verbose_name_plural = "Auditoría"
        ordering = ["-fecha_hora"]

    def __str__(self):
        return f"[{self.fecha_hora:%Y-%m-%d %H:%M}] {self.usuario} {self.accion} {self.modulo} {self.id_registro}"


def registrar_auditoria(usuario, accion, modulo, id_registro="", detalle=""):
    """Equivalente a logAudit_() del Apps Script. Nunca debe tumbar la
    operación principal por un fallo al escribir el log."""
    try:
        Auditoria.objects.create(
            usuario=getattr(usuario, "email", None) or str(usuario or "Desconocido"),
            accion=accion,
            modulo=modulo,
            id_registro=id_registro or "",
            detalle=detalle or "",
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# ACTIVIDADES  (hoja "SEGUIMIENTO_GESTION_TI")
# ---------------------------------------------------------------------------
class Actividad(models.Model):
    id = models.CharField(primary_key=True, max_length=20, editable=False)
    linea_gestion = models.CharField("Línea de gestión", max_length=150, blank=True)
    nombre = models.CharField("Actividad / Proyecto", max_length=255)
    descripcion = models.TextField("Descripción", blank=True)
    relacionado_con_riesgos = models.CharField(
        "Relacionado con riesgos", max_length=10, blank=True
    )
    codigo_riesgo_historico = models.CharField(
        "Código riesgo (histórico, ya no se edita aquí)", max_length=100, blank=True,
        help_text="Desde que existe la relación muchos-a-muchos con riesgos, la fuente "
        "de verdad es la lista de riesgos asociados de abajo. Este campo queda congelado "
        "como referencia histórica, igual que en el Sheet original.",
    )
    responsable = models.CharField(max_length=150, blank=True)
    prioridad = models.CharField(max_length=50, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_compromiso = models.DateField(null=True, blank=True)
    fecha_final = models.DateField("Fecha final", null=True, blank=True)
    estado = models.CharField(max_length=50, blank=True)
    avance_pct = models.DecimalField("% avance", max_digits=5, decimal_places=2, default=0)
    evidencia = models.FileField(
        upload_to="evidencias/%Y/%m/", max_length=500, blank=True,
        help_text="Sube una imagen o PDF como evidencia (antes era un link de texto; los links "
        "antiguos ya guardados siguen ahí como referencia, pero no se pueden abrir como archivo).",
    )
    observaciones = models.TextField(blank=True)
    revisado_por = models.CharField(max_length=150, blank=True)
    fecha_revision = models.DateField(null=True, blank=True)
    estado_revision = models.CharField(max_length=50, blank=True)
    codigo_seif = models.CharField(max_length=50, blank=True)
    link_seif = models.CharField("Link SEIF", max_length=500, blank=True)
    comentario = models.TextField(blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)
    creado_por_usuario = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="actividades_creadas", editable=False,
        help_text="Se asigna solo automáticamente, con el usuario que la creó. "
        "Usada para restringir quién puede editarla (su creador, o el Jefe/admin).",
    )

    class Meta:
        verbose_name = "Actividad"
        verbose_name_plural = "Actividades"
        ordering = ["-fecha_inicio", "id"]

    def __str__(self):
        return f"{self.id} — {self.nombre}"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = generar_siguiente_id(Actividad, "TI-", 3)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NoEliminable(
            "Las actividades no se pueden eliminar (política de auditoría). "
            "Cambia su ESTADO en vez de borrarla."
        )

    @property
    def es_proyecto(self):
        return self.nombre.strip().upper().startswith("PROYECTO")

    @property
    def codigos_riesgo(self):
        return list(self.riesgos.values_list("codigo_riesgo", flat=True))


class Riesgo(models.Model):
    """Registro real de un riesgo (antes solo existía como un código de
    texto suelto en RelacionActividadRiesgo). Se crea manualmente aquí, con
    los datos que vienen de la matriz de riesgos / DOFA externa — a
    propósito no se sincroniza automático con ningún archivo externo
    ("para no tener problemas si cambian link o hojas o nombre etc."),
    igual que se venía haciendo en el Apps Script.

    El campo `codigo` es la misma referencia corta (R-01, R-02...) que ya
    se usaba en RelacionActividadRiesgo.codigo_riesgo y en
    Actividad.codigo_riesgo_historico — sirve de llave de unión entre
    ambas tablas sin necesitar una migración de datos.
    """

    class Nivel(models.TextChoices):
        BAJA = "Baja", "Baja"
        MEDIA = "Media", "Media"
        ALTA = "Alta", "Alta"
        CRITICA = "Crítica", "Crítica"

    class CategoriaDofa(models.TextChoices):
        DEBILIDAD = "Debilidad", "Debilidad"
        OPORTUNIDAD = "Oportunidad", "Oportunidad"
        FORTALEZA = "Fortaleza", "Fortaleza"
        AMENAZA = "Amenaza", "Amenaza"

    codigo = models.CharField(primary_key=True, max_length=30)
    nombre = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True)
    nivel = models.CharField(max_length=20, choices=Nivel.choices, blank=True)
    categoria_dofa = models.CharField(
        "Categoría DOFA", max_length=20, choices=CategoriaDofa.choices, blank=True,
    )
    referencia_matriz_externa = models.CharField(
        "Código/referencia en la matriz externa", max_length=100, blank=True,
        help_text="Código o celda con el que aparece este riesgo en tu matriz de "
        "riesgos/DOFA externa (solo texto de referencia, no se sincroniza).",
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Riesgo"
        verbose_name_plural = "Gestión de riesgos"
        ordering = ["codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.nombre}"

    def save(self, *args, **kwargs):
        self.codigo = self.codigo.strip().upper()
        super().save(*args, **kwargs)

    @property
    def actividades(self):
        return Actividad.objects.filter(
            id__in=RelacionActividadRiesgo.objects.filter(
                codigo_riesgo=self.codigo
            ).values_list("actividad_id", flat=True)
        )


class RelacionActividadRiesgo(models.Model):
    """Hoja RELACION_ACTIVIDAD_RIESGO — relación muchos-a-muchos: una
    actividad puede contribuir a varios riesgos (A18, A83, A84...) a la vez.
    El total global de actividades SIEMPRE se cuenta desde Actividad, nunca
    desde aquí; esta tabla solo sirve para filtrar "qué actividades
    contribuyen al riesgo X"."""

    actividad = models.ForeignKey(
        Actividad, on_delete=models.CASCADE, related_name="riesgos", to_field="id"
    )
    codigo_riesgo = models.CharField(max_length=30)

    class Meta:
        verbose_name = "Relación actividad-riesgo"
        verbose_name_plural = "Relaciones actividad-riesgo"
        constraints = [
            models.UniqueConstraint(
                fields=["actividad", "codigo_riesgo"], name="relacion_actividad_riesgo_unica"
            )
        ]

    def save(self, *args, **kwargs):
        self.codigo_riesgo = self.codigo_riesgo.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.actividad_id} → {self.codigo_riesgo}"


# ---------------------------------------------------------------------------
# SUBACTIVIDADES  (hoja "DETALLE_ACTIVIDADES") y su avance
# (hoja "AVANCE_SUBACTIVIDADES")
# ---------------------------------------------------------------------------
class Subactividad(models.Model):
    id_detalle = models.CharField(primary_key=True, max_length=20, editable=False)
    actividad = models.ForeignKey(
        Actividad, on_delete=models.PROTECT, related_name="subactividades", to_field="id",
        verbose_name="Actividad padre",
    )
    nombre = models.CharField("Subactividad", max_length=255)
    responsable = models.CharField(max_length=150, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_compromiso = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=50, blank=True)
    cumplimiento = models.CharField(max_length=50, blank=True)
    evidencia = models.FileField(
        upload_to="evidencias/%Y/%m/", max_length=500, blank=True,
        help_text="Sube una imagen o PDF como evidencia (antes era un link de texto; los links "
        "antiguos ya guardados siguen ahí como referencia, pero no se pueden abrir como archivo).",
    )
    observacion = models.TextField(blank=True)
    creado_por_usuario = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="subactividades_creadas", editable=False,
        help_text="Se asigna solo automáticamente, con el usuario que la creó. "
        "Usada para restringir quién puede editarla (su creador, o el Jefe/admin).",
    )

    class Meta:
        verbose_name = "Subactividad"
        verbose_name_plural = "Subactividades"
        ordering = ["-fecha_compromiso", "id_detalle"]

    def __str__(self):
        return f"{self.id_detalle} — {self.nombre}"

    def save(self, *args, **kwargs):
        if not self.id_detalle:
            self.id_detalle = generar_siguiente_id(Subactividad, "DET-", 4, campo_pk="id_detalle")
        super().save(*args, **kwargs)

    @property
    def avance_pct(self):
        if self.fecha_fin:
            return 100
        ultimo = self.avances.order_by("-fecha_avance", "-avance_acumulado").first()
        return ultimo.avance_acumulado if ultimo else 0

    @property
    def dias(self):
        inicio = self.fecha_inicio or self.fecha_compromiso
        if not inicio:
            return None
        fin = self.fecha_fin or date.today()
        return (fin - inicio).days

    @property
    def vencida(self):
        return bool(
            self.fecha_compromiso and not self.fecha_fin and self.fecha_compromiso < date.today()
        )


class AvanceSubactividad(models.Model):
    """Hoja AVANCE_SUBACTIVIDADES. Un registro por cada vez que se trabaja
    en una subactividad. Política: se editan pero NO se borran (historial).
    El avance va de 0 a 99 — el 100% solo llega al poner fecha_fin en la
    subactividad (ver Subactividad.avance_pct)."""

    id_avance = models.CharField(primary_key=True, max_length=20, editable=False)
    subactividad = models.ForeignKey(
        Subactividad, on_delete=models.CASCADE, related_name="avances", to_field="id_detalle"
    )
    fecha_avance = models.DateField()
    avance_acumulado = models.PositiveSmallIntegerField()
    responsable = models.CharField(max_length=150, blank=True)
    nota = models.TextField(blank=True)
    evidencia = models.FileField(
        upload_to="evidencias/%Y/%m/", max_length=500, blank=True,
        help_text="Sube una imagen o PDF como evidencia (antes era un link de texto; los links "
        "antiguos ya guardados siguen ahí como referencia, pero no se pueden abrir como archivo).",
    )

    class Meta:
        verbose_name = "Avance de subactividad"
        verbose_name_plural = "Avances de subactividades"
        ordering = ["-fecha_avance"]

    def __str__(self):
        return f"{self.subactividad_id} → {self.avance_acumulado}% ({self.fecha_avance})"

    def clean(self):
        if self.avance_acumulado is not None and not (0 <= self.avance_acumulado <= 99):
            raise ValidationError(
                "El avance acumulado debe ser un número entre 0 y 99. El 100% se logra "
                "poniendo la fecha fin en la subactividad."
            )

    def save(self, *args, **kwargs):
        if not self.id_avance:
            self.id_avance = generar_siguiente_id(AvanceSubactividad, "AV-", 4, campo_pk="id_avance")
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# ACTIVOS CRÍTICOS  (hoja "SERVICIOS_CRITICOS_TI")
# y VALIDACIONES  (hoja "VALIDACION_SERVICIOS_TI")
# ---------------------------------------------------------------------------
class ActivoCritico(models.Model):
    id_servicio = models.CharField(primary_key=True, max_length=20, editable=False)
    servicio = models.CharField(max_length=255)
    categoria = models.CharField(max_length=100, blank=True)
    criticidad = models.CharField(max_length=50, blank=True)
    tier = models.CharField(max_length=50, blank=True)
    rto = models.CharField("RTO", max_length=100, blank=True)
    rpo = models.CharField("RPO", max_length=100, blank=True)
    depende_de = models.CharField(max_length=255, blank=True)
    control_mitigacion = models.TextField(blank=True)
    responsable = models.CharField(max_length=150, blank=True)
    frecuencia_validacion = models.CharField(max_length=50, blank=True)
    estado_actual = models.CharField(max_length=50, blank=True)
    observacion = models.TextField(blank=True)
    proyecto_asociado = models.ForeignKey(
        Actividad, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="activos_asociados", to_field="id",
    )
    proveedor = models.CharField(max_length=150, blank=True)
    ubicacion = models.CharField(max_length=150, blank=True)
    tipo_servicio = models.CharField(
        max_length=30, blank=True, help_text="INTERNO o PROVEEDOR EXTERNO"
    )
    critico_desde = models.DateField(
        "Crítico desde", null=True, blank=True,
        help_text="Desde cuándo este activo es crítico y debe validarse (déjalo vacío si "
        "siempre lo ha sido). El indicador de Activos Críticos NO exige validación en los "
        "meses anteriores a esta fecha, para no mostrar como 'incumplido' un activo que en "
        "ese momento todavía no existía o no era crítico.",
    )

    class Meta:
        verbose_name = "Activo / servicio crítico"
        verbose_name_plural = "Activos / servicios críticos"
        ordering = ["servicio"]

    def __str__(self):
        return f"{self.id_servicio} — {self.servicio}"

    def save(self, *args, **kwargs):
        if not self.id_servicio:
            self.id_servicio = generar_siguiente_id(ActivoCritico, "SER-", 3, campo_pk="id_servicio")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NoEliminable(
            "Los activos críticos no se pueden eliminar (política de auditoría). "
            "Cambia su ESTADO_ACTUAL en vez de borrarlo."
        )

    @property
    def ultima_validacion(self):
        v = self.validaciones.order_by("-fecha_validacion").first()
        return v.fecha_validacion if v else None

    @property
    def proxima_validacion(self):
        ultima = self.ultima_validacion
        dias = CICLOS_DIAS_POR_FRECUENCIA.get(self.frecuencia_validacion)
        if not ultima or not dias:
            return None
        return ultima + timedelta(days=dias)

    @property
    def estado_validacion(self):
        """Replica el criterio usado por alertaServiciosCriticos() del Apps
        Script para decidir si un servicio sale en la alerta diaria."""
        ultima_val = self.validaciones.order_by("-fecha_validacion").first()
        if ultima_val and str(ultima_val.resultado).strip().lower() in ("fallo", "falla"):
            return "Servicio con falla"
        prox = self.proxima_validacion
        if prox:
            hoy = date.today()
            if prox < hoy:
                return "Pendiente revisión"
            if prox == hoy:
                return "Revisar hoy"
        return "Al día"

    @property
    def en_alerta(self):
        return self.estado_validacion in ("Servicio con falla", "Pendiente revisión", "Revisar hoy")


class Validacion(models.Model):
    id_validacion = models.CharField(primary_key=True, max_length=20, editable=False)
    activo = models.ForeignKey(
        ActivoCritico, on_delete=models.PROTECT, related_name="validaciones", to_field="id_servicio",
        verbose_name="Servicio / activo",
    )
    fecha_validacion = models.DateField()
    tipo_validacion = models.CharField(max_length=50, blank=True)
    resultado = models.CharField(max_length=50, blank=True)
    responsable = models.CharField(max_length=150, blank=True)
    evidencia = models.FileField(
        upload_to="evidencias/%Y/%m/", max_length=500, blank=True,
        help_text="Sube una imagen o PDF como evidencia (antes era un link de texto; los links "
        "antiguos ya guardados siguen ahí como referencia, pero no se pueden abrir como archivo).",
    )
    observacion_validacion = models.TextField(blank=True)
    revisado_por = models.CharField(max_length=150, blank=True)
    fecha_revision = models.DateField(null=True, blank=True)
    estado_revision = models.CharField(max_length=50, blank=True)
    codigo_seif = models.CharField(max_length=50, blank=True)
    link_seif = models.CharField("Link SEIF", max_length=500, blank=True)
    observacion_revision = models.TextField(blank=True)
    seguimiento_proveedor = models.CharField(
        max_length=10, blank=True,
        help_text="Sí/No — ¿se hizo seguimiento al proveedor cuando esta validación fue "
        "una novedad (resultado Intermitente o Fallo)?",
    )

    class Meta:
        verbose_name = "Validación"
        verbose_name_plural = "Validaciones"
        ordering = ["-fecha_validacion"]

    def __str__(self):
        return f"{self.id_validacion} — {self.activo_id} ({self.fecha_validacion})"

    def save(self, *args, **kwargs):
        if not self.id_validacion:
            self.id_validacion = generar_siguiente_id(Validacion, "VAL-", 4, campo_pk="id_validacion")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NoEliminable(
            "El historial de validaciones se conserva. No se permite eliminar registros; "
            "edita la validación si necesitas corregir información."
        )


# ---------------------------------------------------------------------------
# PROYECTOS — ficha informativa  (hoja "DETALLE_PROYECTOS")
# Un "proyecto" no es una tabla propia: es cualquier Actividad con
# Actividad.es_proyecto == True. Esta tabla solo guarda la ficha ampliada
# que alguien llena para ese proyecto (texto libre).
# ---------------------------------------------------------------------------
class DetalleProyecto(models.Model):
    proyecto = models.OneToOneField(
        Actividad, primary_key=True, on_delete=models.CASCADE, related_name="ficha", to_field="id"
    )
    objetivo_general = models.TextField(blank=True)
    alcance = models.TextField(blank=True)
    justificacion = models.TextField(blank=True)
    beneficios_esperados = models.TextField(blank=True)
    entregables = models.TextField(blank=True)
    exclusiones = models.TextField(blank=True)
    riesgos_mitigacion = models.TextField(
        "Riesgos y mitigación", blank=True,
        help_text="Texto libre a propósito: no se deriva de la matriz de riesgos.",
    )
    actualizado_por = models.CharField(max_length=150, blank=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ficha de proyecto"
        verbose_name_plural = "Fichas de proyectos"

    def __str__(self):
        return f"Ficha de {self.proyecto_id}"


# ---------------------------------------------------------------------------
# CALENDARIO — tareas sueltas  (hoja "TAREAS_CALENDARIO")
# ---------------------------------------------------------------------------
class TareaCalendario(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "Pendiente", "Pendiente"
        HECHA = "Hecha", "Hecha"

    id = models.CharField(primary_key=True, max_length=20, editable=False)
    titulo = models.CharField(max_length=255)
    fecha = models.DateField()
    responsable = models.CharField(max_length=150, blank=True)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    observacion = models.TextField(blank=True)
    creado_por = models.CharField(max_length=150, blank=True)
    # default=timezone.now (no auto_now_add) por la misma razón que en
    # Auditoria: poder preservar la fecha real al importar del Excel.
    fecha_creacion = models.DateTimeField(default=timezone.now)
    completado_por = models.CharField(max_length=150, blank=True)
    fecha_completado = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Tarea de calendario"
        verbose_name_plural = "Tareas de calendario"
        ordering = ["fecha"]

    def __str__(self):
        return f"{self.id} — {self.titulo}"

    def save(self, *args, **kwargs):
        if not self.id:
            self.id = generar_siguiente_id(TareaCalendario, "TAR-", 4)
        super().save(*args, **kwargs)

    @property
    def vencida(self):
        return self.estado == self.Estado.PENDIENTE and self.fecha < date.today()


# ---------------------------------------------------------------------------
# INDICADORES — catálogo configurable estilo "tabla dinámica", inspirado en
# los indicadores que el usuario llevaba en Looker Studio (Servicios
# Críticos, Plan de trabajo de Sistemas, etc.). La idea central, pedida
# explícitamente por el usuario: que se puedan agregar indicadores nuevos
# SIN escribir código — Indicador es el "molde" (una fila de catálogo) y
# RegistroIndicador es cada medición periódica de ese molde (una fila por
# trimestre/mes/año). Para la mayoría de indicadores la meta y el valor
# logrado se escriben a mano, junto con un análisis en texto libre y el
# seguimiento de una acción correctiva. El de "Activos críticos" es especial
# (tipo AUTO_ACTIVOS_CRITICOS): su valor logrado NO se escribe a mano, se
# calcula solo a partir de las Validaciones reales del periodo (contando
# cada activo una sola vez así se haya revalidado varias veces, tal como
# pidió el usuario: "puede que haya revisado un activo más veces no pasa
# nada, ya que solo vale 1 vez que se haga la validación").
# ---------------------------------------------------------------------------
class Indicador(models.Model):
    class Tipo(models.TextChoices):
        MANUAL = "MANUAL", "Manual (se escribe el valor logrado cada periodo)"
        AUTO_ACTIVOS_CRITICOS = (
            "AUTO_ACTIVOS_CRITICOS",
            "Automático — activos críticos validados (calculado desde Validaciones)",
        )
        AUTO_SUBACTIVIDADES_PROYECTO = (
            "AUTO_SUBACTIVIDADES_PROYECTO",
            "Automático — % de subactividades finalizadas de una o más actividades/proyectos",
        )
        AUTO_SEGUIMIENTO_PROVEEDORES = (
            "AUTO_SEGUIMIENTO_PROVEEDORES",
            "Automático — seguimiento a proveedores en novedades de activos críticos "
            "(calculado desde Validaciones)",
        )
        AUTO_CONTINUIDAD_OPERATIVA = (
            "AUTO_CONTINUIDAD_OPERATIVA",
            "Automático — promedio entre % Activos Críticos y % Actividades con riesgo "
            "gestionadas",
        )

    class Periodicidad(models.TextChoices):
        MENSUAL = "MENSUAL", "Mensual"
        TRIMESTRAL = "TRIMESTRAL", "Trimestral"
        ANUAL = "ANUAL", "Anual"

    nombre = models.CharField(max_length=150, unique=True)
    descripcion = models.TextField(
        blank=True, help_text="Qué mide este indicador (aparece como ayuda al registrar un periodo)."
    )
    tipo = models.CharField(max_length=30, choices=Tipo.choices, default=Tipo.MANUAL)
    periodicidad = models.CharField(
        max_length=20, choices=Periodicidad.choices, default=Periodicidad.TRIMESTRAL
    )
    unidad = models.CharField(
        max_length=20, blank=True, default="%",
        help_text='Cómo mostrar el valor, por ejemplo "%" o "validaciones".',
    )
    activo = models.BooleanField(
        default=True, help_text="Si se desmarca, deja de aparecer en el listado principal (no se borra)."
    )
    orden = models.PositiveIntegerField(default=0, help_text="Para ordenar las tarjetas del listado.")
    actividades_fuente = models.ManyToManyField(
        "Actividad", blank=True, related_name="indicadores_fuente",
        verbose_name="Actividades/proyectos de origen",
        help_text='Solo para el tipo "% de subactividades finalizadas": de cuál(es) '
        "actividad(es) o proyecto(s) se cuentan las subactividades (ej. el proyecto de "
        "Modernización Tecnológica, o la actividad de Gestión de Solicitudes). No aplica a "
        "los demás tipos de indicador.",
    )

    class Meta:
        verbose_name = "Indicador"
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def rango_fechas(self, anio, periodo):
        """Devuelve (fecha_inicio, fecha_fin) del periodo según la
        periodicidad de este indicador. `periodo` es: mes 1-12 si es
        MENSUAL, trimestre 1-4 si es TRIMESTRAL, o se ignora si es ANUAL."""
        if self.periodicidad == self.Periodicidad.MENSUAL:
            mes = periodo
            inicio = date(anio, mes, 1)
            fin_mes = calendar.monthrange(anio, mes)[1]
            fin = date(anio, mes, fin_mes)
        elif self.periodicidad == self.Periodicidad.TRIMESTRAL:
            mes_inicio = (periodo - 1) * 3 + 1
            mes_fin = mes_inicio + 2
            inicio = date(anio, mes_inicio, 1)
            fin_mes = calendar.monthrange(anio, mes_fin)[1]
            fin = date(anio, mes_fin, fin_mes)
        else:  # ANUAL
            inicio = date(anio, 1, 1)
            fin = date(anio, 12, 31)
        return inicio, fin

    def _info_mes(self, anio, mes):
        """(fecha_inicio, fecha_fin, ya_transcurrido) de un mes calendario."""
        inicio = date(anio, mes, 1)
        fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
        return inicio, fin, fin < date.today()

    def detalle_mes_activos_criticos(self, anio, mes):
        """Para UN mes calendario puntual: por cada activo Alta/Crítica que ya
        existía como crítico ese mes (según `critico_desde`), si tuvo al menos
        una validación ese mes (cumple) y cuántas tuvo en total (informativo).
        Si el mes todavía no ha terminado, no exige nada todavía (ver
        `_info_mes`) — así el indicador no se ve artificialmente bajo a mitad
        de un periodo en curso."""
        inicio, fin, transcurrido = self._info_mes(anio, mes)
        activos = ActivoCritico.objects.filter(criticidad__in=CRITICIDADES_INDICADOR).order_by("servicio")
        conteo = {}
        if transcurrido:
            for activo_id in (
                Validacion.objects.filter(activo__in=activos, fecha_validacion__gte=inicio, fecha_validacion__lte=fin)
                .order_by()
                .values_list("activo_id", flat=True)
            ):
                conteo[activo_id] = conteo.get(activo_id, 0) + 1
        filas, meta, valor, bruto = [], 0, 0, 0
        for activo in activos:
            existia = transcurrido and (activo.critico_desde is None or activo.critico_desde <= inicio)
            if not existia:
                filas.append({"activo": activo, "aplica": False, "cumplido": None, "cantidad": 0})
                continue
            cantidad = conteo.get(activo.id_servicio, 0)
            cumplido = cantidad >= 1
            filas.append({"activo": activo, "aplica": True, "cumplido": cumplido, "cantidad": cantidad})
            meta += 1
            bruto += cantidad
            if cumplido:
                valor += 1
        return {
            "anio": anio, "mes": mes, "inicio": inicio, "fin": fin, "transcurrido": transcurrido,
            "filas": filas, "meta": meta, "valor": valor, "total_bruto": bruto,
        }

    def detalle_activos_criticos(self, anio, periodo):
        """Igual que `detalle_mes_activos_criticos` pero agregado sobre TODO
        el periodo del indicador (puede ser varios meses si es trimestral o
        anual) — cada mes cuenta por separado (una revalidación del mismo
        activo en el mismo mes no suma dos veces, pero si lo valida en dos
        meses distintos del periodo sí cuentan los dos), tal como se acordó
        con el usuario."""
        inicio, fin = self.rango_fechas(anio, periodo)
        meses = []
        cursor = date(inicio.year, inicio.month, 1)
        while cursor <= fin:
            meses.append(self.detalle_mes_activos_criticos(cursor.year, cursor.month))
            cursor = date(cursor.year + (1 if cursor.month == 12 else 0), (cursor.month % 12) + 1, 1)

        activos = ActivoCritico.objects.filter(criticidad__in=CRITICIDADES_INDICADOR).order_by("servicio")
        filas = []
        for activo in activos:
            celdas = []
            for info_mes in meses:
                fila_mes = next(
                    (f for f in info_mes["filas"] if f["activo"].id_servicio == activo.id_servicio), None
                )
                celdas.append({
                    "anio": info_mes["anio"], "mes": info_mes["mes"], "transcurrido": info_mes["transcurrido"],
                    **(fila_mes or {"aplica": False, "cumplido": None, "cantidad": 0}),
                })
            filas.append({"activo": activo, "celdas": celdas})

        meta = sum(m["meta"] for m in meses)
        valor = sum(m["valor"] for m in meses)
        total_bruto = sum(m["total_bruto"] for m in meses)
        faltantes = [
            (fila["activo"], celda) for fila in filas for celda in fila["celdas"]
            if celda.get("aplica") and celda.get("cumplido") is False
        ]
        return {
            "meses": meses, "filas": filas, "meta": meta, "valor": valor,
            "total_bruto": total_bruto, "faltantes": faltantes,
        }

    def detalle_subactividades_proyecto(self, anio, periodo):
        """Para indicadores tipo AUTO_SUBACTIVIDADES_PROYECTO: cuenta las
        subactividades de las actividades/proyectos configurados en
        `actividades_fuente` cuya fecha de inicio cae dentro del periodo, y
        de esas cuántas ya quedaron "Finalizado". Se recalcula en vivo cada
        vez que se consulta — si llega una solicitud nueva a mitad de
        periodo y sigue "En proceso", simplemente no cuenta todavía como
        lograda hasta que alguien la marque Finalizado (no hace falta
        excluir periodos en curso, a diferencia de Activos Críticos)."""
        inicio, fin = self.rango_fechas(anio, periodo)
        subactividades = (
            Subactividad.objects.filter(actividad__in=self.actividades_fuente.all())
            .annotate(
                _fecha_ref=Coalesce("fecha_inicio", "fecha_compromiso", "fecha_fin")
            )
            .filter(_fecha_ref__gte=inicio, _fecha_ref__lte=fin)
            .select_related("actividad")
            .order_by("actividad__id", "_fecha_ref")
        )
        filas = [
            {
                "subactividad": s, "actividad": s.actividad, "estado": s.estado,
                "finalizado": s.estado == "Finalizado",
            }
            for s in subactividades
        ]
        total = len(filas)
        finalizadas = sum(1 for f in filas if f["finalizado"])
        return {"filas": filas, "meta": total, "valor": finalizadas, "inicio": inicio, "fin": fin}

    def detalle_seguimiento_proveedores(self, anio, periodo):
        """Para indicadores tipo AUTO_SEGUIMIENTO_PROVEEDORES: una "novedad"
        es una Validación con resultado Intermitente o Fallo sobre un activo
        crítico que SÍ tiene proveedor asignado (servicio de terceros); un
        "seguimiento" es que, de esas, el campo `seguimiento_proveedor` de
        la validación quede en "Sí"."""
        inicio, fin = self.rango_fechas(anio, periodo)
        novedades_qs = (
            Validacion.objects.filter(
                fecha_validacion__gte=inicio, fecha_validacion__lte=fin,
                resultado__in=["Intermitente", "Fallo"],
            )
            .exclude(activo__proveedor="")
            .select_related("activo")
            .order_by("activo__servicio", "fecha_validacion")
        )
        filas = [
            {
                "validacion": v, "activo": v.activo, "mes": v.fecha_validacion,
                "con_seguimiento": v.seguimiento_proveedor.strip().lower() == "sí"
                or v.seguimiento_proveedor.strip().lower() == "si",
            }
            for v in novedades_qs
        ]
        total = len(filas)
        con_seguimiento = sum(1 for f in filas if f["con_seguimiento"])
        return {"filas": filas, "meta": total, "valor": con_seguimiento, "inicio": inicio, "fin": fin}

    def detalle_actividades_con_riesgo(self, anio, periodo):
        """Para el componente de Continuidad Operativa: de todas las
        Actividades que tienen al menos un Riesgo asociado (tabla
        RelacionActividadRiesgo) y cuya fecha de inicio cae en el periodo,
        cuántas ya quedaron "Finalizado"."""
        inicio, fin = self.rango_fechas(anio, periodo)
        actividades = (
            Actividad.objects.filter(riesgos__isnull=False)
            .annotate(
                _fecha_ref=Coalesce("fecha_inicio", "fecha_compromiso", "fecha_final")
            )
            .filter(_fecha_ref__gte=inicio, _fecha_ref__lte=fin)
            .distinct()
            .order_by("id")
        )
        filas = [
            {"actividad": a, "estado": a.estado, "finalizada": a.estado == "Finalizado"}
            for a in actividades
        ]
        total = len(filas)
        finalizadas = sum(1 for f in filas if f["finalizada"])
        return {"filas": filas, "meta": total, "valor": finalizadas, "inicio": inicio, "fin": fin}

    def detalle_continuidad_operativa(self, anio, periodo):
        """Continuidad Operativa = promedio simple entre el % de Revisión de
        Activos Críticos y el % de Actividades con riesgo asociado que ya
        quedaron gestionadas (Finalizado) en el periodo."""
        activos = self.detalle_activos_criticos(anio, periodo)
        pct_activos = (
            min(100, round(activos["valor"] / activos["meta"] * 100, 1)) if activos["meta"] else None
        )
        actividades = self.detalle_actividades_con_riesgo(anio, periodo)
        pct_actividades = (
            min(100, round(actividades["valor"] / actividades["meta"] * 100, 1))
            if actividades["meta"] else None
        )
        partes = [p for p in (pct_activos, pct_actividades) if p is not None]
        promedio = round(sum(partes) / len(partes), 1) if partes else None
        return {
            "pct_activos": pct_activos, "pct_actividades": pct_actividades, "promedio": promedio,
            "detalle_activos": activos, "detalle_actividades": actividades,
            "inicio": actividades["inicio"], "fin": actividades["fin"],
        }

    def calcular_valor_automatico(self, anio, periodo):
        """Para indicadores de tipo AUTO_*, calcula el valor logrado real a
        partir de los datos de la plataforma (sin que nadie lo digite)."""
        if self.tipo == self.Tipo.AUTO_ACTIVOS_CRITICOS:
            return self.detalle_activos_criticos(anio, periodo)["valor"]
        if self.tipo == self.Tipo.AUTO_SUBACTIVIDADES_PROYECTO:
            return self.detalle_subactividades_proyecto(anio, periodo)["valor"]
        if self.tipo == self.Tipo.AUTO_SEGUIMIENTO_PROVEEDORES:
            return self.detalle_seguimiento_proveedores(anio, periodo)["valor"]
        if self.tipo == self.Tipo.AUTO_CONTINUIDAD_OPERATIVA:
            # El "valor" ya es directamente el % promedio (no un conteo a
            # dividir) — por eso la meta se fija en 100 (ver más abajo), así
            # el % de cumplimiento que ya calcula RegistroIndicador queda
            # igual al promedio, sin tener que duplicar esa lógica aquí.
            return self.detalle_continuidad_operativa(anio, periodo)["promedio"]
        return None

    def calcular_meta_automatica(self, anio, periodo):
        """La meta tampoco se escribe a mano para estos tipos de indicador:
        se calcula sola a partir de los mismos datos (ver cada método
        `detalle_*` de arriba)."""
        if self.tipo == self.Tipo.AUTO_ACTIVOS_CRITICOS:
            return self.detalle_activos_criticos(anio, periodo)["meta"]
        if self.tipo == self.Tipo.AUTO_SUBACTIVIDADES_PROYECTO:
            return self.detalle_subactividades_proyecto(anio, periodo)["meta"]
        if self.tipo == self.Tipo.AUTO_SEGUIMIENTO_PROVEEDORES:
            return self.detalle_seguimiento_proveedores(anio, periodo)["meta"]
        if self.tipo == self.Tipo.AUTO_CONTINUIDAD_OPERATIVA:
            valor = self.detalle_continuidad_operativa(anio, periodo)["promedio"]
            return 100 if valor is not None else None
        return None

    def periodos_disponibles(self):
        if self.periodicidad == self.Periodicidad.MENSUAL:
            return [(n, nombre) for n, nombre in enumerate(
                ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
                 "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"], start=1
            )]
        if self.periodicidad == self.Periodicidad.TRIMESTRAL:
            return [(1, "Trimestre 1 (Ene-Mar)"), (2, "Trimestre 2 (Abr-Jun)"),
                    (3, "Trimestre 3 (Jul-Sep)"), (4, "Trimestre 4 (Oct-Dic)")]
        return [(1, "Año completo")]

    def periodo_actual(self):
        """(anio, periodo) de hoy, para preseleccionar el formulario."""
        hoy = date.today()
        if self.periodicidad == self.Periodicidad.MENSUAL:
            return hoy.year, hoy.month
        if self.periodicidad == self.Periodicidad.TRIMESTRAL:
            return hoy.year, (hoy.month - 1) // 3 + 1
        return hoy.year, 1


class RegistroIndicador(models.Model):
    class EstadoAccion(models.TextChoices):
        NA = "N/A", "No aplica / sin novedad"
        PENDIENTE = "Pendiente", "Pendiente"
        EN_PROCESO = "En proceso", "En proceso"
        COMPLETADA = "Completada", "Completada"

    indicador = models.ForeignKey(Indicador, on_delete=models.CASCADE, related_name="registros")
    anio = models.PositiveIntegerField("Año")
    periodo = models.PositiveSmallIntegerField(
        help_text="Mes (1-12), trimestre (1-4) o 1 si el indicador es anual, según su periodicidad."
    )
    meta_manual = models.DecimalField(
        "Meta esperada", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Lo que se esperaba lograr en este periodo (ej. 9 validaciones). Déjalo "
        "vacío si el indicador es automático: se calcula solo.",
    )
    valor_manual = models.DecimalField(
        "Valor logrado", max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Déjalo vacío si el indicador es automático: se calcula solo.",
    )
    analisis = models.TextField(
        "Análisis del indicador", blank=True,
        help_text="Texto libre, igual que la celda de análisis en el Excel/Looker Studio.",
    )
    accion_correctiva = models.TextField(blank=True)
    fecha_accion = models.DateField("Fecha compromiso de la acción", null=True, blank=True)
    estado_accion = models.CharField(
        max_length=20, choices=EstadoAccion.choices, default=EstadoAccion.NA
    )
    creado_por_usuario = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, editable=False,
        related_name="registros_indicador_creados",
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Registro de indicador"
        verbose_name_plural = "Registros de indicadores"
        constraints = [
            models.UniqueConstraint(
                fields=["indicador", "anio", "periodo"], name="un_registro_por_periodo"
            )
        ]
        ordering = ["-anio", "-periodo"]

    def __str__(self):
        return f"{self.indicador.nombre} — {self.anio}/{self.periodo}"

    @property
    def valor(self):
        """Valor logrado a mostrar: calculado si el indicador es
        automático, o el que se digitó a mano en caso contrario."""
        if self.indicador.tipo != Indicador.Tipo.MANUAL:
            calculado = self.indicador.calcular_valor_automatico(self.anio, self.periodo)
            if calculado is not None:
                return calculado
        return self.valor_manual

    @property
    def meta(self):
        """Igual que `valor`: para indicadores automáticos la meta tampoco
        se escribe a mano, se calcula sola (cuántas casillas activo×mes se
        exigían en el periodo)."""
        if self.indicador.tipo != Indicador.Tipo.MANUAL:
            calculado = self.indicador.calcular_meta_automatica(self.anio, self.periodo)
            if calculado is not None:
                return calculado
        return self.meta_manual

    @property
    def total_validaciones_bruto(self):
        """Conteo informativo (NO usado para el %): cuántas validaciones se
        hicieron en total en el periodo, sin deduplicar — para que se vea
        la diferencia entre "revisé mucho un activo" y "cumplí con todos"."""
        if self.indicador.tipo == Indicador.Tipo.AUTO_ACTIVOS_CRITICOS:
            return self.indicador.detalle_activos_criticos(self.anio, self.periodo)["total_bruto"]
        return None

    @property
    def cumplimiento_pct(self):
        """% de cumplimiento, siempre topado en 100 (así la meta se supere,
        como pidió el usuario con el ejemplo de 9 esperadas / 12 hechas)."""
        meta = self.meta
        valor = self.valor
        if not meta or valor is None:
            return None
        return min(100, round((float(valor) / float(meta)) * 100, 1))

    @property
    def etiqueta_periodo(self):
        for numero, nombre in self.indicador.periodos_disponibles():
            if numero == self.periodo:
                return f"{nombre} {self.anio}"
        return f"{self.anio}/{self.periodo}"
