"""
Crea un registro "borrador" en Gestión de riesgos (modelo Riesgo) por cada
código de riesgo que ya existe en RelacionActividadRiesgo (los códigos que
se importaron desde la columna "CÓDIGO RIESGO" del Excel, o los que ya se
le asignaron a una actividad desde la app) pero que todavía no tiene su
ficha completa en el catálogo de riesgos.

No inventa nombre/nivel/categoría — los deja en blanco (o con un nombre
provisional) para que el usuario los complete a mano, exactamente como ya
venía trabajando con su matriz de riesgos/DOFA externa. Es seguro correrlo
varias veces: nunca pisa un Riesgo que ya tenga datos.

Uso:
    python manage.py sincronizar_riesgos
"""
from django.core.management.base import BaseCommand

from nucleo.models import RelacionActividadRiesgo, Riesgo


class Command(BaseCommand):
    help = "Crea fichas borrador en Gestión de riesgos para los códigos de riesgo que ya están asociados a actividades."

    def handle(self, *args, **options):
        codigos_en_uso = set(
            RelacionActividadRiesgo.objects.values_list("codigo_riesgo", flat=True)
        )
        codigos_en_uso = {c.strip().upper() for c in codigos_en_uso if c and c.strip()}
        codigos_existentes = set(Riesgo.objects.values_list("codigo", flat=True))

        faltantes = sorted(codigos_en_uso - codigos_existentes)
        if not faltantes:
            self.stdout.write(self.style.SUCCESS(
                "No hay códigos de riesgo nuevos por crear: todos los que están "
                "asociados a actividades ya tienen ficha en Gestión de riesgos."
            ))
            return

        creados = 0
        for codigo in faltantes:
            Riesgo.objects.create(
                codigo=codigo,
                nombre=f"Riesgo {codigo} (completar datos)",
                descripcion="Creado automáticamente porque ya estaba asociado a una o más "
                "actividades. Completa nombre, nivel, categoría DOFA y referencia externa "
                "con los datos de tu matriz de riesgos.",
            )
            creados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Se crearon {creados} fichas borrador en Gestión de riesgos: {', '.join(faltantes)}. "
            "Entra a cada una y completa sus datos reales."
        ))
