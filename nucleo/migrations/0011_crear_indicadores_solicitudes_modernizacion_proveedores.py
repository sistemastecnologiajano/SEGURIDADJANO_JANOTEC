"""Crea automáticamente 3 indicadores más (igual que se hizo con "Activos
críticos" en la migración 0007), para que el usuario no tenga que armarlos
a mano la primera vez:

- "Gestión de Solicitudes Tecnológicas": % de subactividades finalizadas de
  la actividad TI-033, calculado en vivo (no hace falta excluir periodos en
  curso: una solicitud que llega a mitad de trimestre y sigue "En proceso"
  simplemente no cuenta todavía como lograda hasta que se marque
  "Finalizado").
- "Modernización Tecnológica": mismo cálculo (% de subactividades
  finalizadas), pero sobre la actividad TI-014 (el proyecto de
  modernización de infraestructura).
- "Seguimiento a Proveedores de Servicios Críticos": a partir de
  Validaciones — una "novedad" es una validación con resultado Intermitente
  o Fallo sobre un activo que tiene proveedor asignado, y un "seguimiento"
  es que el campo `seguimiento_proveedor` de esa validación quede en "Sí".
  No depende de ninguna actividad concreta (se calcula sobre todas las
  Validaciones), por eso no necesita `actividades_fuente`.

Si en el entorno donde corre esta migración todavía no existen las
actividades TI-033 o TI-014 (por ejemplo, una base de datos de pruebas sin
los datos reales importados), el indicador se crea igual pero sin esa
actividad vinculada — el usuario la puede asociar después desde "Editar
indicador" cuando la actividad sí exista."""
from django.db import migrations


NOMBRE_SOLICITUDES = "Gestión de Solicitudes Tecnológicas"
NOMBRE_MODERNIZACION = "Modernización Tecnológica"
NOMBRE_PROVEEDORES = "Seguimiento a Proveedores de Servicios Críticos"


def crear_indicadores(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Actividad = apps.get_model("nucleo", "Actividad")

    solicitudes, _ = Indicador.objects.get_or_create(
        nombre=NOMBRE_SOLICITUDES,
        defaults=dict(
            descripcion=(
                "(N.º de solicitudes tecnológicas gestionadas / N.º total de solicitudes "
                "recibidas) × 100. Cada solicitud es una subactividad de la actividad "
                "TI-033; se cuenta como 'gestionada' cuando queda en estado Finalizado. Se "
                "calcula solo, en vivo, a partir de las subactividades de esa actividad."
            ),
            tipo="AUTO_SUBACTIVIDADES_PROYECTO",
            periodicidad="TRIMESTRAL",
            unidad="%",
            activo=True,
            orden=2,
        ),
    )
    actividad_ti033 = Actividad.objects.filter(id="TI-033").first()
    if actividad_ti033:
        solicitudes.actividades_fuente.set([actividad_ti033])

    modernizacion, _ = Indicador.objects.get_or_create(
        nombre=NOMBRE_MODERNIZACION,
        defaults=dict(
            descripcion=(
                "% de subactividades del proyecto de Modernización Tecnológica (TI-014) "
                "que ya quedaron en estado Finalizado, respecto al total de subactividades "
                "del proyecto. Se calcula solo, en vivo, a partir de esas subactividades."
            ),
            tipo="AUTO_SUBACTIVIDADES_PROYECTO",
            periodicidad="TRIMESTRAL",
            unidad="%",
            activo=True,
            orden=3,
        ),
    )
    actividad_ti014 = Actividad.objects.filter(id="TI-014").first()
    if actividad_ti014:
        modernizacion.actividades_fuente.set([actividad_ti014])

    Indicador.objects.get_or_create(
        nombre=NOMBRE_PROVEEDORES,
        defaults=dict(
            descripcion=(
                "(N.º de servicios tecnológicos críticos de terceros con novedades a los "
                "que se realizó seguimiento / N.º total de servicios tecnológicos críticos "
                "de terceros con novedades) × 100. Una 'novedad' es una Validación con "
                "resultado Intermitente o Fallo sobre un activo con proveedor asignado; "
                "'seguimiento' es que el campo Seguimiento proveedor de esa validación "
                "quede en Sí. Se calcula solo a partir de las Validaciones registradas."
            ),
            tipo="AUTO_SEGUIMIENTO_PROVEEDORES",
            periodicidad="TRIMESTRAL",
            unidad="%",
            activo=True,
            orden=4,
        ),
    )


def eliminar_indicadores(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Indicador.objects.filter(
        nombre__in=[NOMBRE_SOLICITUDES, NOMBRE_MODERNIZACION, NOMBRE_PROVEEDORES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0010_indicador_actividades_fuente_alter_indicador_tipo"),
    ]

    operations = [
        migrations.RunPython(crear_indicadores, eliminar_indicadores),
    ]
