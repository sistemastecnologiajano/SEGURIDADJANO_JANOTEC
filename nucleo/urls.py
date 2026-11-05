from django.urls import path

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),

    path("actividades/", views.lista_actividades, name="actividad_lista"),
    path("actividades/nueva/", views.guardar_actividad, name="actividad_nueva"),
    path("actividades/<str:pk>/", views.detalle_actividad, name="actividad_detalle"),
    path("actividades/<str:pk>/editar/", views.guardar_actividad, name="actividad_editar"),

    path("subactividades/", views.lista_subactividades, name="subactividad_lista"),
    path("subactividades/nueva/", views.guardar_subactividad, name="subactividad_nueva"),
    path("subactividades/<str:pk>/", views.detalle_subactividad, name="subactividad_detalle"),
    path("subactividades/<str:pk>/editar/", views.guardar_subactividad, name="subactividad_editar"),
    path("subactividades/<str:pk>/eliminar/", views.eliminar_subactividad, name="subactividad_eliminar"),
    path(
        "subactividades/<str:sub_pk>/avances/nuevo/",
        views.guardar_avance_subactividad,
        name="avance_subactividad_nuevo",
    ),

    path("activos/", views.lista_activos, name="activo_lista"),
    path("activos/nuevo/", views.guardar_activo, name="activo_nuevo"),
    path("activos/<str:pk>/", views.detalle_activo, name="activo_detalle"),
    path("activos/<str:pk>/editar/", views.guardar_activo, name="activo_editar"),

    path("validaciones/", views.lista_validaciones, name="validacion_lista"),
    path("validaciones/nueva/", views.guardar_validacion, name="validacion_nueva"),
    path("validaciones/<str:pk>/editar/", views.guardar_validacion, name="validacion_editar"),

    path("seguimiento/", views.seguimiento, name="seguimiento"),
    path("seguimiento/actividades/<str:pk>/revisar/", views.revisar_actividad, name="revisar_actividad"),
    path("seguimiento/validaciones/<str:pk>/revisar/", views.revisar_validacion, name="revisar_validacion"),

    path("indicadores/", views.lista_indicadores, name="indicador_lista"),
    path("indicadores/nuevo/", views.guardar_indicador, name="indicador_nuevo"),
    path("indicadores/<int:pk>/", views.detalle_indicador, name="indicador_detalle"),
    path("indicadores/<int:pk>/editar/", views.guardar_indicador, name="indicador_editar"),
    path(
        "indicadores/<int:pk>/registros/nuevo/",
        views.guardar_registro_indicador, name="registro_indicador_nuevo",
    ),
    path(
        "indicadores/<int:pk>/registros/<int:registro_pk>/editar/",
        views.guardar_registro_indicador, name="registro_indicador_editar",
    ),

    path("riesgos/", views.lista_riesgos, name="riesgo_lista"),
    path("riesgos/nuevo/", views.guardar_riesgo, name="riesgo_nuevo"),
    path("riesgos/<str:pk>/", views.detalle_riesgo, name="riesgo_detalle"),
    path("riesgos/<str:pk>/editar/", views.guardar_riesgo, name="riesgo_editar"),

    path("proyectos/", views.lista_proyectos, name="proyecto_lista"),
    path("proyectos/<str:pk>/", views.detalle_proyecto, name="proyecto_detalle"),
    path("proyectos/<str:pk>/ficha/", views.guardar_ficha_proyecto, name="ficha_proyecto_editar"),

    path("calendario/", views.lista_calendario, name="calendario_lista"),
    path("calendario/nueva/", views.guardar_tarea_calendario, name="calendario_nueva"),
    path("calendario/<str:pk>/editar/", views.guardar_tarea_calendario, name="calendario_editar"),
    path("calendario/<str:pk>/marcar/", views.marcar_tarea_calendario, name="calendario_marcar"),

    path("auditoria/", views.lista_auditoria, name="auditoria_lista"),
]
