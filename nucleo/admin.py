from django.contrib import admin

from .models import (
    Actividad,
    ActivoCritico,
    Auditoria,
    AvanceSubactividad,
    DetalleProyecto,
    Indicador,
    ListaValor,
    RegistroIndicador,
    RelacionActividadRiesgo,
    Riesgo,
    Subactividad,
    TareaCalendario,
    Validacion,
)

# Rediseño visual del admin (colores/encabezado institucionales JANOTEC);
# el estilo en sí vive en templates/admin/base_site.html + el CSS en
# nucleo/static/nucleo/css/admin_custom.css.
admin.site.site_header = "Gestión TIC · Seguridad JANO"
admin.site.site_title = "Gestión TIC"
admin.site.index_title = "Panel de administración"


class RelacionActividadRiesgoInline(admin.TabularInline):
    model = RelacionActividadRiesgo
    extra = 1


class DetalleProyectoInline(admin.StackedInline):
    model = DetalleProyecto
    extra = 0
    can_delete = False


@admin.register(Actividad)
class ActividadAdmin(admin.ModelAdmin):
    list_display = (
        "id", "nombre", "linea_gestion", "responsable", "prioridad",
        "estado", "avance_pct", "fecha_compromiso", "es_proyecto",
    )
    list_filter = ("estado", "prioridad", "linea_gestion")
    search_fields = ("id", "nombre", "descripcion", "responsable")
    inlines = [RelacionActividadRiesgoInline, DetalleProyectoInline]

    def has_delete_permission(self, request, obj=None):
        # Política de auditoría: nunca se borran actividades.
        return False


@admin.register(Subactividad)
class SubactividadAdmin(admin.ModelAdmin):
    list_display = (
        "id_detalle", "actividad", "nombre", "responsable", "estado",
        "fecha_compromiso", "fecha_fin", "avance_pct",
    )
    list_filter = ("estado",)
    search_fields = ("id_detalle", "nombre", "responsable")
    autocomplete_fields = ["actividad"]


@admin.register(AvanceSubactividad)
class AvanceSubactividadAdmin(admin.ModelAdmin):
    list_display = (
        "id_avance", "subactividad", "fecha_avance", "avance_acumulado", "responsable",
    )
    search_fields = ("id_avance", "subactividad__id_detalle", "subactividad__nombre")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ActivoCritico)
class ActivoCriticoAdmin(admin.ModelAdmin):
    list_display = (
        "id_servicio", "servicio", "categoria", "criticidad", "tipo_servicio",
        "responsable", "estado_validacion",
    )
    list_filter = ("criticidad", "categoria", "tipo_servicio", "estado_actual")
    search_fields = ("id_servicio", "servicio", "responsable", "proveedor")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Validacion)
class ValidacionAdmin(admin.ModelAdmin):
    list_display = (
        "id_validacion", "activo", "fecha_validacion", "tipo_validacion",
        "resultado", "responsable",
    )
    list_filter = ("resultado", "tipo_validacion")
    search_fields = ("id_validacion", "activo__servicio", "activo__id_servicio")
    autocomplete_fields = ["activo"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TareaCalendario)
class TareaCalendarioAdmin(admin.ModelAdmin):
    list_display = ("id", "titulo", "fecha", "responsable", "estado", "vencida")
    list_filter = ("estado",)
    search_fields = ("id", "titulo", "responsable")


@admin.register(Riesgo)
class RiesgoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "nivel", "categoria_dofa", "referencia_matriz_externa")
    list_filter = ("nivel", "categoria_dofa")
    search_fields = ("codigo", "nombre", "descripcion", "referencia_matriz_externa")
    ordering = ("codigo",)


@admin.register(ListaValor)
class ListaValorAdmin(admin.ModelAdmin):
    list_display = ("categoria", "valor", "orden")
    list_filter = ("categoria",)
    search_fields = ("valor",)
    ordering = ("categoria", "orden", "valor")


@admin.register(Indicador)
class IndicadorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "periodicidad", "unidad", "activo", "orden")
    list_filter = ("tipo", "periodicidad", "activo")
    search_fields = ("nombre", "descripcion")
    ordering = ("orden", "nombre")


@admin.register(RegistroIndicador)
class RegistroIndicadorAdmin(admin.ModelAdmin):
    list_display = ("indicador", "anio", "periodo", "meta_manual", "valor_manual", "estado_accion")
    list_filter = ("indicador", "anio", "estado_accion")
    search_fields = ("indicador__nombre", "analisis", "accion_correctiva")
    autocomplete_fields = ["indicador"]


@admin.register(Auditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ("fecha_hora", "usuario", "accion", "modulo", "id_registro")
    list_filter = ("modulo", "accion")
    search_fields = ("usuario", "id_registro", "detalle")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
