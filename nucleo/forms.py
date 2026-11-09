from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.html import format_html, format_html_join

from .models import (
    Actividad,
    ActivoCritico,
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


def _widgets_fecha(*nombres):
    # format="%Y-%m-%d" es obligatorio: el <input type="date"> del navegador
    # solo entiende fechas en formato AAAA-MM-DD. Sin esto, Django renderiza
    # el valor guardado con el formato regional (DD/MM/AAAA), el navegador no
    # lo reconoce y el campo aparece vacío al editar — aunque el dato SÍ está
    # guardado en la base de datos (no se pierde nada).
    return {
        n: forms.DateInput(attrs={"type": "date", "class": "form-control"}, format="%Y-%m-%d")
        for n in nombres
    }


class ListaDesplegableWidget(forms.TextInput):
    """Combina un campo de texto normal con un <datalist> alimentado desde el
    catálogo de ListaValor: al escribir, el navegador sugiere los valores ya
    cargados (evita errores de tecleo como "Operativo sin NOvedad"), pero si
    hace falta un valor que todavía no está en la lista, se puede escribir
    uno nuevo igual — no es obligatorio elegir de la lista, solo la sugiere.
    Si un valor nuevo se repite mucho, el Jefe/Sistemas puede agregarlo al
    catálogo desde /admin/ -> Listas (catálogos) para que quede sugerido."""

    def __init__(self, categoria, attrs=None):
        self.categoria = categoria
        super().__init__(attrs)

    def render(self, name, value, attrs=None, renderer=None):
        attrs = dict(attrs or {})
        datalist_id = f"lista_{name}"
        attrs["list"] = datalist_id
        attrs.setdefault("autocomplete", "off")
        html_input = super().render(name, value, attrs, renderer)
        opciones = ListaValor.opciones(self.categoria)
        html_opciones = format_html_join("", "<option value=\"{}\">", ((o,) for o in opciones))
        return format_html('{}<datalist id="{}">{}</datalist>', html_input, datalist_id, html_opciones)


class BaseModelForm(forms.ModelForm):
    """Aplica la clase de Bootstrap a todos los campos automáticamente,
    para no repetirla campo por campo en cada formulario."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre, campo in self.fields.items():
            css_actual = campo.widget.attrs.get("class", "")
            if isinstance(campo.widget, (forms.CheckboxInput,)):
                campo.widget.attrs["class"] = (css_actual + " form-check-input").strip()
            elif isinstance(campo.widget, forms.Select):
                campo.widget.attrs["class"] = (css_actual + " form-select").strip()
            else:
                campo.widget.attrs["class"] = (css_actual + " form-control").strip()


class FormularioIngreso(AuthenticationForm):
    username = forms.CharField(widget=forms.TextInput(attrs={"class": "form-control", "autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"class": "form-control"}))


class ActividadForm(BaseModelForm):
    class Meta:
        model = Actividad
        fields = [
            "linea_gestion", "nombre", "descripcion", "relacionado_con_riesgos",
            "responsable", "prioridad", "fecha_inicio", "fecha_compromiso",
            "fecha_final", "estado", "avance_pct", "evidencia", "observaciones",
            "revisado_por", "fecha_revision", "estado_revision", "codigo_seif",
            "link_seif", "comentario",
        ]
        widgets = {
            **_widgets_fecha("fecha_inicio", "fecha_compromiso", "fecha_final", "fecha_revision"),
            "linea_gestion": ListaDesplegableWidget(ListaValor.Categoria.LINEA_GESTION),
            "responsable": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "prioridad": ListaDesplegableWidget(ListaValor.Categoria.PRIORIDAD),
            "estado": ListaDesplegableWidget(ListaValor.Categoria.ESTADO_ACTIVIDAD),
            "revisado_por": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "estado_revision": ListaDesplegableWidget(ListaValor.Categoria.ESTADO_REVISION),
        }


class RiesgosActividadForm(forms.Form):
    """Reemplaza por completo la lista de códigos de riesgo asociados a una
    actividad — mismo comportamiento de saveRelacionesActividad() del Apps
    Script (reemplazo total, no incremental).

    `riesgos_catalogo` es la lista de casillas (código + nombre, con la
    descripción como ayuda) que se llena en __init__ con lo que exista en el
    catálogo de Riesgo en ese momento. `otros_codigos` es un campo de texto
    aparte, para códigos sueltos que ya estaban guardados pero que todavía
    no tienen un Riesgo creado en el catálogo (no se pierden, pero no salen
    como casilla porque no hay nada que mostrar de ellos todavía)."""

    riesgos_catalogo = forms.ModelMultipleChoiceField(
        label="Riesgos asociados",
        queryset=Riesgo.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    otros_codigos = forms.CharField(
        label="Otros códigos (que todavía no estén en el catálogo de riesgos, separados por coma)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "R-99"}),
    )

    @staticmethod
    def initial_desde(actividad):
        """Arma el `initial` de este formulario a partir de los códigos que
        ya tenga guardados la actividad, separando los que sí existen en el
        catálogo (van marcados como casilla) de los que no (quedan en el
        campo de texto aparte, sin perderlos)."""
        if actividad is None:
            return {}
        codigos_actuales = set(actividad.codigos_riesgo)
        codigos_catalogo = set(Riesgo.objects.values_list("codigo", flat=True))
        return {
            "riesgos_catalogo": list(codigos_actuales & codigos_catalogo),
            "otros_codigos": ", ".join(sorted(codigos_actuales - codigos_catalogo)),
        }

    def guardar(self, actividad):
        del_catalogo = {r.codigo for r in self.cleaned_data["riesgos_catalogo"]}
        crudos = self.cleaned_data["otros_codigos"]
        otros = {c.strip().upper() for c in crudos.split(",") if c.strip()}
        codigos = del_catalogo | otros
        RelacionActividadRiesgo.objects.filter(actividad=actividad).delete()
        RelacionActividadRiesgo.objects.bulk_create(
            [RelacionActividadRiesgo(actividad=actividad, codigo_riesgo=c) for c in codigos]
        )


class IndicadorForm(BaseModelForm):
    class Meta:
        model = Indicador
        fields = [
            "nombre", "descripcion", "tipo", "periodicidad", "unidad", "activo", "orden",
            "actividades_fuente",
        ]
        widgets = {
            "actividades_fuente": forms.SelectMultiple(attrs={"size": 8}),
        }
        help_texts = {
            "actividades_fuente": 'Solo aplica si el tipo elegido arriba es "% de '
            'subactividades finalizadas de una o más actividades/proyectos" — ahí sí elige '
            "de cuáles actividades se cuentan las subactividades (mantén Ctrl/Cmd presionado "
            "para elegir varias). Para los demás tipos, déjalo vacío.",
        }


class RegistroIndicadorForm(BaseModelForm):
    class Meta:
        model = RegistroIndicador
        fields = [
            "anio", "periodo", "meta_manual", "valor_manual", "analisis",
            "accion_correctiva", "fecha_accion", "estado_accion",
        ]
        widgets = {**_widgets_fecha("fecha_accion")}

    def __init__(self, *args, indicador=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.indicador = indicador or (self.instance.indicador if self.instance.pk else None)
        if self.indicador:
            self.fields["periodo"] = forms.ChoiceField(
                label="Periodo", choices=self.indicador.periodos_disponibles(),
                widget=forms.Select(attrs={"class": "form-select"}),
            )
            if self.indicador.tipo != Indicador.Tipo.MANUAL:
                for nombre in ("meta_manual", "valor_manual"):
                    self.fields[nombre].required = False
                    self.fields[nombre].help_text = (
                        "Este indicador es automático: se calcula solo a partir de los datos "
                        "reales de la plataforma, no hace falta escribirlo aquí."
                    )
                    self.fields[nombre].widget.attrs["disabled"] = True

    def clean(self):
        # Validación manual de "un registro por periodo": el campo
        # `indicador` no está en el formulario (se asigna en la vista), así
        # que Django excluye de forma automática la UniqueConstraint que lo
        # involucra al validar el form — hay que revisarlo a mano aquí.
        cleaned = super().clean()
        anio = cleaned.get("anio")
        periodo = cleaned.get("periodo")
        if self.indicador and anio and periodo:
            ya_existe = RegistroIndicador.objects.filter(
                indicador=self.indicador, anio=anio, periodo=periodo,
            ).exclude(pk=self.instance.pk).exists()
            if ya_existe:
                raise forms.ValidationError(
                    "Ya existe un registro de este indicador para ese año y periodo. "
                    "Edita el que ya existe en vez de crear uno duplicado."
                )
        return cleaned

    def save(self, commit=True):
        instancia = super().save(commit=False)
        if self.indicador:
            instancia.indicador = self.indicador
        if self.indicador and self.indicador.tipo != Indicador.Tipo.MANUAL:
            # Los campos vienen deshabilitados en el HTML (no llegan en el
            # POST), así que nos aseguramos de no pisarlos con None.
            instancia.valor_manual = None
            instancia.meta_manual = None
        if commit:
            instancia.save()
        return instancia


class RiesgoForm(BaseModelForm):
    class Meta:
        model = Riesgo
        fields = [
            "codigo", "nombre", "descripcion", "nivel", "categoria_dofa",
            "referencia_matriz_externa",
        ]


class SubactividadForm(BaseModelForm):
    class Meta:
        model = Subactividad
        fields = [
            "actividad", "nombre", "responsable", "fecha_inicio", "fecha_compromiso",
            "fecha_fin", "estado", "cumplimiento", "evidencia", "observacion",
        ]
        widgets = {
            **_widgets_fecha("fecha_inicio", "fecha_compromiso", "fecha_fin"),
            "responsable": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "estado": ListaDesplegableWidget(ListaValor.Categoria.ESTADO_SUBACTIVIDAD),
            "cumplimiento": ListaDesplegableWidget(ListaValor.Categoria.CUMPLIMIENTO),
        }


class AvanceSubactividadForm(BaseModelForm):
    class Meta:
        model = AvanceSubactividad
        fields = ["fecha_avance", "avance_acumulado", "responsable", "nota", "evidencia"]
        widgets = {
            **_widgets_fecha("fecha_avance"),
            "responsable": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
        }

    def clean_avance_acumulado(self):
        valor = self.cleaned_data["avance_acumulado"]
        if not (0 <= valor <= 99):
            raise forms.ValidationError(
                "El avance acumulado debe estar entre 0 y 99. El 100% se marca poniendo "
                "la fecha fin en la subactividad."
            )
        return valor


class ActivoCriticoForm(BaseModelForm):
    class Meta:
        model = ActivoCritico
        fields = [
            "servicio", "categoria", "criticidad", "tier", "rto", "rpo", "depende_de",
            "control_mitigacion", "responsable", "frecuencia_validacion", "estado_actual",
            "observacion", "proyecto_asociado", "proveedor", "ubicacion", "tipo_servicio",
            "critico_desde",
        ]
        widgets = {
            **_widgets_fecha("critico_desde"),
            "categoria": ListaDesplegableWidget(ListaValor.Categoria.CATEGORIA_ACTIVO),
            "criticidad": ListaDesplegableWidget(ListaValor.Categoria.CRITICIDAD),
            "responsable": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "frecuencia_validacion": ListaDesplegableWidget(ListaValor.Categoria.FRECUENCIA_VALIDACION),
            "proveedor": ListaDesplegableWidget(ListaValor.Categoria.PROVEEDOR),
            "ubicacion": ListaDesplegableWidget(ListaValor.Categoria.UBICACION),
            "tipo_servicio": ListaDesplegableWidget(ListaValor.Categoria.TIPO_SERVICIO),
        }


class ValidacionForm(BaseModelForm):
    class Meta:
        model = Validacion
        fields = [
            "activo", "fecha_validacion", "tipo_validacion", "resultado", "responsable",
            "evidencia", "observacion_validacion", "revisado_por", "fecha_revision",
            "estado_revision", "codigo_seif", "link_seif", "observacion_revision",
            "seguimiento_proveedor",
        ]
        widgets = {
            **_widgets_fecha("fecha_validacion", "fecha_revision"),
            "tipo_validacion": ListaDesplegableWidget(ListaValor.Categoria.TIPO_VALIDACION),
            "resultado": ListaDesplegableWidget(ListaValor.Categoria.RESULTADO_VALIDACION),
            "responsable": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "revisado_por": ListaDesplegableWidget(ListaValor.Categoria.RESPONSABLE),
            "estado_revision": ListaDesplegableWidget(ListaValor.Categoria.ESTADO_REVISION),
        }


class DetalleProyectoForm(BaseModelForm):
    class Meta:
        model = DetalleProyecto
        fields = [
            "objetivo_general", "alcance", "justificacion", "beneficios_esperados",
            "entregables", "exclusiones", "riesgos_mitigacion",
        ]
        widgets = {campo: forms.Textarea(attrs={"rows": 3}) for campo in fields}


class TareaCalendarioForm(BaseModelForm):
    class Meta:
        model = TareaCalendario
        fields = ["titulo", "fecha", "responsable", "observacion"]
        widgets = _widgets_fecha("fecha")
