"""Crea el grupo "Sistemas" automáticamente (igual que "Jefe" ya existe a
mano desde el admin), para asignar permisos sobre Activos críticos sin que
el usuario tenga que crear el grupo manualmente primero."""
from django.db import migrations


def crear_grupo(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Sistemas")


def eliminar_grupo(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Sistemas").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("nucleo", "0004_actividad_creado_por_usuario_and_more"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(crear_grupo, eliminar_grupo),
    ]
