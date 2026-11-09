"""Crea automáticamente el indicador "Continuidad Operativa" (igual que las
migraciones 0007 y 0011 con los demás indicadores automáticos). Es un
promedio entre el % de Revisión de Activos Críticos y el % de Actividades
con riesgo asociado que ya quedaron gestionadas (Finalizado) en el periodo
— no necesita `actividades_fuente` porque no depende de una actividad en
particular, sino de todas las que tengan al menos un Riesgo asociado."""
from django.db import migrations


NOMBRE = "Continuidad Operativa"


def crear_indicador(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Indicador.objects.get_or_create(
        nombre=NOMBRE,
        defaults=dict(
            descripcion=(
                "Promedio entre el % de Revisión de Activos Críticos (validaciones al día) "
                "y el % de Actividades con riesgo asociado que ya quedaron gestionadas "
                "(Finalizado) en el periodo. Se calcula solo, en vivo."
            ),
            tipo="AUTO_CONTINUIDAD_OPERATIVA",
            periodicidad="TRIMESTRAL",
            unidad="%",
            activo=True,
            orden=5,
        ),
    )


def eliminar_indicador(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Indicador.objects.filter(nombre=NOMBRE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0011_crear_indicadores_solicitudes_modernizacion_proveedores"),
    ]

    operations = [
        migrations.RunPython(crear_indicador, eliminar_indicador),
    ]
