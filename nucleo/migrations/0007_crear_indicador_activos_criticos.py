"""Crea automáticamente el indicador "Activos críticos" (cálculo
automático desde Validaciones, trimestral), para que el usuario no tenga
que crearlo a mano la primera vez. Los otros 6 indicadores que el usuario
mencionó (Gestión de incidentes, Mantenimiento, Gestión de solicitudes,
Modernización tecnológica, Seguimiento proveedores, Continuidad operativa)
los agrega él mismo desde la plataforma cuando quiera, cada uno con su
propia periodicidad — esa es justamente la idea de que el catálogo sea
configurable sin necesitar código nuevo."""
from django.db import migrations


NOMBRE = "Activos críticos"


def crear_indicador(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Indicador.objects.get_or_create(
        nombre=NOMBRE,
        defaults=dict(
            descripcion=(
                "% de activos/servicios críticos validados en el periodo, respecto a la "
                "meta esperada. Se calcula solo a partir de las Validaciones registradas "
                "(revalidar el mismo activo varias veces en el periodo solo cuenta una vez)."
            ),
            tipo="AUTO_ACTIVOS_CRITICOS",
            periodicidad="TRIMESTRAL",
            unidad="%",
            activo=True,
            orden=1,
        ),
    )


def eliminar_indicador(apps, schema_editor):
    Indicador = apps.get_model("nucleo", "Indicador")
    Indicador.objects.filter(nombre=NOMBRE).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0006_indicador_registroindicador"),
    ]

    operations = [
        migrations.RunPython(crear_indicador, eliminar_indicador),
    ]
