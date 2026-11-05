"""
Importa los datos reales del Excel original "PLAN_DE_GESTIÓN_TI" (el mismo
que alimentaba la app de Google Sheets + Apps Script) a esta base de datos.

Uso:
    python manage.py importar_datos_excel /ruta/al/PLAN_DE_GESTI_N_TI.xlsx

Es seguro volver a correrlo (usa update_or_create / get_or_create con los
mismos IDs que trae el Excel), así que si se corrige algo en el archivo se
puede re-importar sin duplicar nada.

Decisiones tomadas para esta migración (documentadas aquí para que quede
registro del porqué):
  - Solo se cuentan como "filas reales" las que tienen su campo clave
    (nombre, servicio, subactividad, etc.) no vacío — muchas hojas del
    Excel traen fórmulas de ID arrastradas hacia abajo en miles de filas
    vacías que no son datos reales.
  - La hoja AVANCE_SUBACTIVIDADES solo tenía 2 registros reales, pero
    DETALLE_ACTIVIDADES sí trae un "% DE AVANCE" histórico por
    subactividad. Para no perder ese dato, si una subactividad no tiene
    fecha fin y no va a tener un registro de avance explícito, se crea
    automáticamente UN avance sintético con ese porcentaje (tope 99%,
    igual que la regla de negocio) para que se siga viendo el avance real
    en el dashboard.
  - Las fechas de auditoría y de creación de tareas de calendario SÍ se
    preservan tal cual venían en el Excel (se cambió el modelo para que lo
    permita, ver nucleo/models.py).
"""
from datetime import date, datetime, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from nucleo.models import (
    Actividad,
    ActivoCritico,
    Auditoria,
    AvanceSubactividad,
    DetalleProyecto,
    ListaValor,
    RelacionActividadRiesgo,
    Subactividad,
    TareaCalendario,
    Validacion,
)

MAPA_LISTAS = {
    "LINEAS": ListaValor.Categoria.LINEA_GESTION,
    "ESTADO ACTIVIDAD": ListaValor.Categoria.ESTADO_ACTIVIDAD,
    "TIPOS_GESTIÓN": ListaValor.Categoria.TIPO_GESTION,
    "RESPONSABLE": ListaValor.Categoria.RESPONSABLE,
    "CARGO": ListaValor.Categoria.CARGO,
    "TIPOS DE VALIDACIÓN": ListaValor.Categoria.TIPO_VALIDACION,
    "RESULTADO_VALIDAICON": ListaValor.Categoria.RESULTADO_VALIDACION,
    "PRIORIDAD": ListaValor.Categoria.PRIORIDAD,
    "ESTADO DE REVISIÓN": ListaValor.Categoria.ESTADO_REVISION,
    "CODIGO_RIESGOS": ListaValor.Categoria.CODIGO_RIESGO,
    "CUMPLIMIENTO": ListaValor.Categoria.CUMPLIMIENTO,
    "categoria": ListaValor.Categoria.CATEGORIA_ACTIVO,
    "REVISION": ListaValor.Categoria.FRECUENCIA_VALIDACION,
    "Proveedor": ListaValor.Categoria.PROVEEDOR,
    "Ubicación Activo / Servicio": ListaValor.Categoria.UBICACION,
}


def _texto(valor):
    if valor is None:
        return ""
    return str(valor).strip()


def _fecha(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None


def _numero(valor, por_defecto=0):
    if valor is None or valor == "":
        return por_defecto
    try:
        return float(valor)
    except (TypeError, ValueError):
        return por_defecto


def _fecha_hora(valor):
    """Convierte un datetime naive del Excel a uno con zona horaria (UTC),
    tal como lo exige USE_TZ=True. Devuelve None si no hay valor."""
    if not isinstance(valor, datetime):
        return None
    if valor.tzinfo is None:
        return valor.replace(tzinfo=dt_timezone.utc)
    return valor


def _codigo_seif(valor):
    """El Excel guarda CÓDIGO_SEIF como número (36974.0); lo volvemos texto
    limpio sin el '.0' final."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return _texto(valor)


def _mapa_encabezados(hoja):
    return {c.value: idx + 1 for idx, c in enumerate(hoja[1]) if c.value}


class Command(BaseCommand):
    help = "Importa los datos reales del Excel PLAN_DE_GESTIÓN_TI a la base de datos."

    def add_arguments(self, parser):
        parser.add_argument("ruta_excel", type=str)

    def handle(self, *args, **options):
        try:
            import openpyxl
        except ImportError:
            raise CommandError("Falta openpyxl: pip install openpyxl")

        ruta = options["ruta_excel"]
        try:
            wb = openpyxl.load_workbook(ruta, data_only=True)
        except FileNotFoundError:
            raise CommandError(f"No se encontró el archivo: {ruta}")

        with transaction.atomic():
            self._importar_listas(wb)
            self._importar_actividades(wb)
            self._importar_relacion_riesgos(wb)
            self._importar_activos_criticos(wb)
            self._importar_validaciones(wb)
            self._importar_subactividades_y_avances(wb)
            self._importar_proyectos_ficha(wb)
            self._importar_calendario(wb)
            self._importar_auditoria(wb)

        self.stdout.write(self.style.SUCCESS("Importación completa."))

    # ------------------------------------------------------------------
    def _importar_listas(self, wb):
        if "LISTAS" not in wb.sheetnames:
            return
        hoja = wb["LISTAS"]
        encabezados = _mapa_encabezados(hoja)
        total = 0
        for nombre_col, categoria in MAPA_LISTAS.items():
            col = encabezados.get(nombre_col)
            if not col:
                continue
            orden = 0
            for fila in range(2, hoja.max_row + 1):
                valor = _texto(hoja.cell(row=fila, column=col).value)
                if not valor:
                    continue
                ListaValor.objects.get_or_create(
                    categoria=categoria, valor=valor, defaults={"orden": orden}
                )
                orden += 1
                total += 1
        self.stdout.write(f"Listas: {total} valores de catálogo.")

    # ------------------------------------------------------------------
    def _importar_actividades(self, wb):
        hoja = wb["SEGUIMIENTO_GESTION_TI"]
        enc = _mapa_encabezados(hoja)
        total = 0
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_act = _texto(valores.get(enc["ID"]))
            nombre = _texto(valores.get(enc["ACTIVIDAD / PROYECTO"]))
            if not id_act or not nombre:
                continue
            Actividad.objects.update_or_create(
                id=id_act,
                defaults=dict(
                    linea_gestion=_texto(valores.get(enc.get("LÍNEA DE GESTIÓN"))),
                    nombre=nombre,
                    descripcion=_texto(valores.get(enc.get("DESCRIPCIÓN"))),
                    relacionado_con_riesgos=_texto(valores.get(enc.get("RELACIONADO CON RIESGOS"))),
                    codigo_riesgo_historico=_texto(valores.get(enc.get("CÓDIGO RIESGO"))),
                    responsable=_texto(valores.get(enc.get("RESPONSABLE"))),
                    prioridad=_texto(valores.get(enc.get("PRIORIDAD"))),
                    fecha_inicio=_fecha(valores.get(enc.get("FECHA INICIO"))),
                    fecha_compromiso=_fecha(valores.get(enc.get("FECHA COMPROMISO"))),
                    fecha_final=_fecha(valores.get(enc.get("FECHA FINAL"))),
                    estado=_texto(valores.get(enc.get("ESTADO"))),
                    avance_pct=_numero(valores.get(enc.get("% AVANCE"))),
                    evidencia=_texto(valores.get(enc.get("EVIDENCIA"))),
                    observaciones=_texto(valores.get(enc.get("OBSERVACIONES"))),
                    revisado_por=_texto(valores.get(enc.get("REVISADO_POR"))),
                    fecha_revision=_fecha(valores.get(enc.get("FECHA_REVISIÓN"))),
                    estado_revision=_texto(valores.get(enc.get("ESTADO_REVISIÓN"))),
                    codigo_seif=_codigo_seif(valores.get(enc.get("CÓDIGO_SEIF"))),
                    link_seif=_texto(valores.get(enc.get("LINK_SEIF"))),
                    comentario=_texto(valores.get(enc.get("COMENTARIO"))),
                ),
            )
            total += 1
        self.stdout.write(f"Actividades: {total} importadas.")

    # ------------------------------------------------------------------
    def _importar_relacion_riesgos(self, wb):
        total = 0
        if "RELACION_ACTIVIDAD_RIESGO" in wb.sheetnames:
            hoja = wb["RELACION_ACTIVIDAD_RIESGO"]
            enc = _mapa_encabezados(hoja)
            for fila in hoja.iter_rows(min_row=2, values_only=False):
                valores = {c.column: c.value for c in fila}
                id_act = _texto(valores.get(enc.get("ID_ACTIVIDAD")))
                codigo = _texto(valores.get(enc.get("CODIGO_RIESGO"))).upper()
                if not id_act or not codigo:
                    continue
                if not Actividad.objects.filter(pk=id_act).exists():
                    continue
                _, creado = RelacionActividadRiesgo.objects.get_or_create(
                    actividad_id=id_act, codigo_riesgo=codigo
                )
                if creado:
                    total += 1

        # Migración de códigos legados de una sola columna (igual que
        # migrarCodigosRiesgoExistentes() del Apps Script): si una
        # actividad tiene CÓDIGO RIESGO histórico pero no quedó en la
        # relación muchos-a-muchos, se agrega también.
        for actividad in Actividad.objects.exclude(codigo_riesgo_historico=""):
            codigo = actividad.codigo_riesgo_historico.strip().upper()
            if not codigo:
                continue
            _, creado = RelacionActividadRiesgo.objects.get_or_create(
                actividad=actividad, codigo_riesgo=codigo
            )
            if creado:
                total += 1
        self.stdout.write(f"Relación actividad-riesgo: {total} vínculos importados.")

    # ------------------------------------------------------------------
    def _importar_activos_criticos(self, wb):
        hoja = wb["SERVICIOS_CRITICOS_TI"]
        enc = _mapa_encabezados(hoja)
        total = 0
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_servicio = _texto(valores.get(enc["ID_SERVICIO"]))
            servicio = _texto(valores.get(enc["SERVICIO"]))
            if not id_servicio or not servicio:
                continue
            proyecto_id = _texto(valores.get(enc.get("PROYECTO ASOCIADO")))
            proyecto = Actividad.objects.filter(pk=proyecto_id).first() if proyecto_id else None
            ActivoCritico.objects.update_or_create(
                id_servicio=id_servicio,
                defaults=dict(
                    servicio=servicio,
                    categoria=_texto(valores.get(enc.get("CATEGORIA"))),
                    criticidad=_texto(valores.get(enc.get("CRITICIDAD"))),
                    tier=_texto(valores.get(enc.get("TIER"))),
                    rto=_texto(valores.get(enc.get("RTO"))),
                    rpo=_texto(valores.get(enc.get("RPO"))),
                    depende_de=_texto(valores.get(enc.get("DEPENDE_DE"))),
                    control_mitigacion=_texto(valores.get(enc.get("CONTROL_MITIGACION"))),
                    responsable=_texto(valores.get(enc.get("RESPONSABLE"))),
                    frecuencia_validacion=_texto(valores.get(enc.get("FERCUENCIA_VALIDACION"))),
                    estado_actual=_texto(valores.get(enc.get("ESTADO_ACTUAL"))),
                    observacion=_texto(valores.get(enc.get("OBSERVACIÓN"))),
                    proyecto_asociado=proyecto,
                    proveedor=_texto(valores.get(enc.get("PROVEEDOR"))),
                    ubicacion=_texto(valores.get(enc.get("UBICACION"))),
                    tipo_servicio=_texto(valores.get(enc.get("TIPO_SERVICIO"))),
                ),
            )
            total += 1
        self.stdout.write(f"Activos críticos: {total} importados.")

    # ------------------------------------------------------------------
    def _importar_validaciones(self, wb):
        hoja = wb["VALIDACION_SERVICIOS_TI"]
        enc = _mapa_encabezados(hoja)
        total = 0
        omitidas = 0
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_val = _texto(valores.get(enc["ID_VALIDACIÓN"]))
            nombre_servicio = _texto(valores.get(enc.get("NOMBRE_SERVICIO")))
            id_servicio = _texto(valores.get(enc.get("ID_SERVICIO")))
            if not id_val or not nombre_servicio:
                continue
            if not ActivoCritico.objects.filter(pk=id_servicio).exists():
                omitidas += 1
                continue
            Validacion.objects.update_or_create(
                id_validacion=id_val,
                defaults=dict(
                    activo_id=id_servicio,
                    fecha_validacion=_fecha(valores.get(enc.get("FECHA_VALIDACIÓN"))) or date.today(),
                    tipo_validacion=_texto(valores.get(enc.get("TIPO_VALIDACIÓN"))),
                    resultado=_texto(valores.get(enc.get("RESULTADO"))),
                    responsable=_texto(valores.get(enc.get("RESPONSABLE"))),
                    evidencia=_texto(valores.get(enc.get("EVIDENCIA"))),
                    observacion_validacion=_texto(valores.get(enc.get("OBSERVACIÓN_VALIDACIÓN"))),
                    revisado_por=_texto(valores.get(enc.get("REVISADO_POR"))),
                    fecha_revision=_fecha(valores.get(enc.get("FECHA_REVISIÓN"))),
                    estado_revision=_texto(valores.get(enc.get("ESTADO_REVISIÓN"))),
                    codigo_seif=_codigo_seif(valores.get(enc.get("CÓDIGO_SEIF"))),
                    link_seif=_texto(valores.get(enc.get("LINK_SEIF"))),
                    observacion_revision=_texto(valores.get(enc.get("OBSERVACIÓN_REIVISÓN"))),
                    seguimiento_proveedor=_texto(valores.get(enc.get("SEGUIMIENTO_PROVEEDOR"))),
                ),
            )
            total += 1
        self.stdout.write(f"Validaciones: {total} importadas ({omitidas} omitidas por servicio inexistente).")

    # ------------------------------------------------------------------
    def _importar_subactividades_y_avances(self, wb):
        hoja = wb["DETALLE_ACTIVIDADES"]
        enc = _mapa_encabezados(hoja)
        total = 0
        omitidas = 0
        sinteticos = 0
        ids_con_avance_explicito = set()

        if "AVANCE_SUBACTIVIDADES" in wb.sheetnames:
            hoja_av = wb["AVANCE_SUBACTIVIDADES"]
            enc_av = _mapa_encabezados(hoja_av)
            for fila in hoja_av.iter_rows(min_row=2, values_only=False):
                valores = {c.column: c.value for c in fila}
                id_detalle = _texto(valores.get(enc_av.get("ID_DETALLE")))
                if id_detalle:
                    ids_con_avance_explicito.add(id_detalle)

        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_detalle = _texto(valores.get(enc["ID_DETALLE"]))
            nombre_sub = _texto(valores.get(enc["SUBACTIVIDAD"]))
            id_padre = _texto(valores.get(enc.get("ID_PADRE")))
            if not id_detalle or not nombre_sub:
                continue
            if not Actividad.objects.filter(pk=id_padre).exists():
                omitidas += 1
                continue

            fecha_fin = _fecha(valores.get(enc.get("FECHA_FIN")))
            sub, _creada = Subactividad.objects.update_or_create(
                id_detalle=id_detalle,
                defaults=dict(
                    actividad_id=id_padre,
                    nombre=nombre_sub,
                    responsable=_texto(valores.get(enc.get("RESPONSABLE"))),
                    fecha_inicio=_fecha(valores.get(enc.get("FECHA INICIO"))),
                    fecha_compromiso=_fecha(valores.get(enc.get("FECHA_COMPROMISO"))),
                    fecha_fin=fecha_fin,
                    estado=_texto(valores.get(enc.get("ESTADO"))),
                    cumplimiento=_texto(valores.get(enc.get("CUMPLIMIENTO"))),
                    evidencia=_texto(valores.get(enc.get("EVIDENCIA"))),
                    observacion=_texto(valores.get(enc.get("OBSERVACIÓN"))),
                ),
            )
            total += 1

            # Avance sintético: solo si no hay fecha_fin (si no, la
            # propiedad avance_pct ya da 100 directamente) ni un avance
            # explícito que vaya a importarse para este id_detalle.
            porcentaje = _numero(valores.get(enc.get("% DE AVANCE")), None)
            if (
                not fecha_fin
                and porcentaje not in (None, 0)
                and id_detalle not in ids_con_avance_explicito
                and not sub.avances.exists()
            ):
                AvanceSubactividad.objects.create(
                    subactividad=sub,
                    fecha_avance=sub.fecha_compromiso or sub.fecha_inicio or date.today(),
                    avance_acumulado=min(int(porcentaje), 99),
                    responsable=sub.responsable,
                    nota="Avance importado desde el % histórico del Excel.",
                )
                sinteticos += 1

        if "AVANCE_SUBACTIVIDADES" in wb.sheetnames:
            hoja_av = wb["AVANCE_SUBACTIVIDADES"]
            enc_av = _mapa_encabezados(hoja_av)
            importados_av = 0
            for fila in hoja_av.iter_rows(min_row=2, values_only=False):
                valores = {c.column: c.value for c in fila}
                id_avance = _texto(valores.get(enc_av["ID_AVANCE"]))
                id_detalle = _texto(valores.get(enc_av.get("ID_DETALLE")))
                if not id_avance or not id_detalle:
                    continue
                if not Subactividad.objects.filter(pk=id_detalle).exists():
                    continue
                AvanceSubactividad.objects.update_or_create(
                    id_avance=id_avance,
                    defaults=dict(
                        subactividad_id=id_detalle,
                        fecha_avance=_fecha(valores.get(enc_av.get("FECHA_AVANCE"))) or date.today(),
                        avance_acumulado=min(int(_numero(valores.get(enc_av.get("AVANCE_ACUMULADO"))) or 0), 99),
                        responsable=_texto(valores.get(enc_av.get("RESPONSABLE"))),
                        nota=_texto(valores.get(enc_av.get("NOTA"))),
                        evidencia=_texto(valores.get(enc_av.get("EVIDENCIA"))),
                    ),
                )
                importados_av += 1
            self.stdout.write(f"Avances de subactividad (explícitos del Excel): {importados_av}.")

        self.stdout.write(
            f"Subactividades: {total} importadas ({omitidas} omitidas por actividad padre inexistente), "
            f"{sinteticos} avances sintéticos creados desde el % histórico."
        )

    # ------------------------------------------------------------------
    def _importar_proyectos_ficha(self, wb):
        if "DETALLE_PROYECTOS" not in wb.sheetnames:
            return
        hoja = wb["DETALLE_PROYECTOS"]
        enc = _mapa_encabezados(hoja)
        total = 0
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_proyecto = _texto(valores.get(enc["ID_PROYECTO"]))
            if not id_proyecto:
                continue
            if not Actividad.objects.filter(pk=id_proyecto).exists():
                continue
            DetalleProyecto.objects.update_or_create(
                proyecto_id=id_proyecto,
                defaults=dict(
                    objetivo_general=_texto(valores.get(enc.get("OBJETIVO_GENERAL"))),
                    alcance=_texto(valores.get(enc.get("ALCANCE"))),
                    justificacion=_texto(valores.get(enc.get("JUSTIFICACION"))),
                    beneficios_esperados=_texto(valores.get(enc.get("BENEFICIOS_ESPERADOS"))),
                    entregables=_texto(valores.get(enc.get("ENTREGABLES"))),
                    exclusiones=_texto(valores.get(enc.get("EXCLUSIONES"))),
                    riesgos_mitigacion=_texto(valores.get(enc.get("RIESGOS_MITIGACION"))),
                    actualizado_por=_texto(valores.get(enc.get("ACTUALIZADO_POR"))),
                ),
            )
            total += 1
        self.stdout.write(f"Fichas de proyecto: {total} importadas.")

    # ------------------------------------------------------------------
    def _importar_calendario(self, wb):
        if "TAREAS_CALENDARIO" not in wb.sheetnames:
            return
        hoja = wb["TAREAS_CALENDARIO"]
        enc = _mapa_encabezados(hoja)
        total = 0
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            id_tarea = _texto(valores.get(enc["ID"]))
            titulo = _texto(valores.get(enc.get("TITULO")))
            if not id_tarea or not titulo:
                continue
            tarea, _creada = TareaCalendario.objects.update_or_create(
                id=id_tarea,
                defaults=dict(
                    titulo=titulo,
                    fecha=_fecha(valores.get(enc.get("FECHA"))) or date.today(),
                    responsable=_texto(valores.get(enc.get("RESPONSABLE"))),
                    estado=_texto(valores.get(enc.get("ESTADO"))) or TareaCalendario.Estado.PENDIENTE,
                    observacion=_texto(valores.get(enc.get("OBSERVACION"))),
                    creado_por=_texto(valores.get(enc.get("CREADO_POR"))),
                    completado_por=_texto(valores.get(enc.get("COMPLETADO_POR"))),
                    fecha_completado=_fecha_hora(valores.get(enc.get("FECHA_COMPLETADO"))),
                ),
            )
            fecha_creacion = _fecha_hora(valores.get(enc.get("FECHA_CREACION")))
            if fecha_creacion:
                TareaCalendario.objects.filter(pk=id_tarea).update(fecha_creacion=fecha_creacion)
            total += 1
        self.stdout.write(f"Tareas de calendario: {total} importadas.")

    # ------------------------------------------------------------------
    def _importar_auditoria(self, wb):
        if "AUDITORÍA" not in wb.sheetnames:
            return
        hoja = wb["AUDITORÍA"]
        enc = _mapa_encabezados(hoja)
        total = 0
        registros = []
        for fila in hoja.iter_rows(min_row=2, values_only=False):
            valores = {c.column: c.value for c in fila}
            accion = _texto(valores.get(enc.get("ACCIÓN")))
            fecha_hora = _fecha_hora(valores.get(enc.get("FECHA_HORA")))
            if not fecha_hora or not accion:
                continue
            registros.append(
                Auditoria(
                    fecha_hora=fecha_hora,
                    usuario=_texto(valores.get(enc.get("USUARIO"))),
                    accion=accion,
                    modulo=_texto(valores.get(enc.get("MÓDULO"))),
                    id_registro=_texto(valores.get(enc.get("ID_REGISTRO"))),
                    detalle=_texto(valores.get(enc.get("DETALLE"))),
                )
            )
            total += 1

        # La auditoría importada se agrega solo si la tabla está vacía,
        # para que re-correr el import no duplique miles de registros.
        if not Auditoria.objects.exists():
            Auditoria.objects.bulk_create(registros)
            self.stdout.write(f"Auditoría: {total} registros históricos importados.")
        else:
            self.stdout.write("Auditoría: ya había registros, no se reimporta (evita duplicados).")
