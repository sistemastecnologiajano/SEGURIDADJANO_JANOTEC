/* Tablas ordenables: cualquier <table class="tabla-ordenable"> permite
 * ordenar haciendo clic en los encabezados (<th>), tal como se pidió para
 * Actividades y Activos críticos. Funciona sin recargar la página.
 * No depende de ninguna librería externa. */
(function () {
  function textoCelda(celda) {
    return (celda.getAttribute("data-orden") || celda.textContent || "").trim();
  }

  function valorComparable(txt) {
    var limpio = txt.replace(/\./g, "").replace(",", ".").replace("%", "").trim();
    var numero = parseFloat(limpio);
    if (!isNaN(numero) && /^-?[0-9.,]+%?$/.test(txt.trim())) return numero;
    // Fechas dd/mm/aaaa -> aaaammdd para que ordenen bien como texto.
    var fecha = txt.trim().match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    if (fecha) return fecha[3] + fecha[2].padStart(2, "0") + fecha[1].padStart(2, "0");
    return txt.toLowerCase();
  }

  function activarTabla(tabla) {
    var encabezados = tabla.querySelectorAll("thead th");
    encabezados.forEach(function (th, indice) {
      if (th.hasAttribute("data-no-ordenar")) return;
      th.classList.add("ordenable");
      th.addEventListener("click", function () {
        var ascendente = !th.classList.contains("orden-asc");
        encabezados.forEach(function (otro) {
          otro.classList.remove("orden-asc", "orden-desc");
        });
        th.classList.add(ascendente ? "orden-asc" : "orden-desc");

        var cuerpo = tabla.querySelector("tbody");
        var filas = Array.prototype.slice.call(cuerpo.querySelectorAll("tr"));
        filas.sort(function (a, b) {
          var celdaA = a.children[indice];
          var celdaB = b.children[indice];
          if (!celdaA || !celdaB) return 0;
          var va = valorComparable(textoCelda(celdaA));
          var vb = valorComparable(textoCelda(celdaB));
          if (va < vb) return ascendente ? -1 : 1;
          if (va > vb) return ascendente ? 1 : -1;
          return 0;
        });
        filas.forEach(function (fila) { cuerpo.appendChild(fila); });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("table.tabla-ordenable").forEach(activarTabla);

    // Filtro rápido en vivo: <input data-filtro-tabla="#idTabla">
    document.querySelectorAll("[data-filtro-tabla]").forEach(function (input) {
      var tabla = document.querySelector(input.getAttribute("data-filtro-tabla"));
      if (!tabla) return;
      input.addEventListener("input", function () {
        var texto = input.value.trim().toLowerCase();
        tabla.querySelectorAll("tbody tr").forEach(function (fila) {
          fila.style.display = fila.textContent.toLowerCase().indexOf(texto) === -1 ? "none" : "";
        });
      });
    });
  });
})();
