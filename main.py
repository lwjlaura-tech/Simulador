"""
Punto de entrada del simulador de Sistemas Operativos.

Genera un único reporte HTML (reporte.html) que reúne DOS simuladores, con un
botón para elegir cuál ver (por defecto se muestra el de planificación):

    1. Planificación de CPU (FCFS, SJF, SRTF y Round Robin)
    2. Concurrencia (los 5 problemas clásicos)

Uso por defecto (no pide ningún dato):

    py main.py

Opciones, todas facultativas:

    py main.py --archivo otro.txt    carga otra lista de procesos
    py main.py --aleatorio 50        genera 50 procesos al azar
    py main.py --semilla 7           semilla para repetir la misma carga
    py main.py --ordenado            carga aleatoria en orden de llegada
    py main.py --quantum 4           quantum del Round Robin
    py main.py --simulador concurrencia   abre el reporte en la pestaña de concurrencia
    py main.py --sin-abrir           genera el reporte sin abrir el navegador

El programa escribe 'reporte.html' en esta misma carpeta y lo abre en el
navegador. También generó los 5 reportes individuales de concurrencia.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from pathlib import Path

from simulador_so import (
    GestorProcesos,
    construir_politicas,
    _ESTILO_BASE,
    _SCRIPT_GANT,
    _cuerpo_html,
    _construir_variantes,
    _datos_graficos,
    _estilos_como_css,
    ejecutar_todas,
)
from simulador_concurrencia import (
    ESTILO_CONCURRENCIA,
    SCRIPT_CONCURRENCIA,
    construir_problemas,
    cuerpo_concurrencia,
    datos_concurrencia,
    generar_reportes_individuales,
)

ARCHIVO_POR_DEFECTO = "procesos.txt"
QUANTUM_POR_DEFECTO = 2
REPORTE_POR_DEFECTO = "reporte.html"


#  PLANTILLA DEL REPORTE 

PLANTILLA_UNIFICADA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulador de Sistemas Operativos</title>
<style>
:root {
__VARIABLES_TEMA__
    --acento-seccion: var(--acento);
}
body {
    background: var(--fondo);
    color: var(--texto);
    font-family: 'Segoe UI', Roboto, system-ui, -apple-system, sans-serif;
    line-height: 1.55;
    margin: 0; padding: 0 20px 80px;
}
.envoltorio { max-width: 1180px; margin: 0 auto; }
.globo {
    position: fixed; z-index: 99; pointer-events: none; opacity: 0;
    background: #0d1119; color: #e6ebf5; border: 1px solid var(--borde);
    padding: 6px 11px; border-radius: 8px; font-size: 12.5px;
    font-family: 'Cascadia Mono', Consolas, monospace;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45); transition: opacity .12s;
}
rect.barra { cursor: pointer; }
rect.barra:hover { stroke: #ffffff; stroke-width: 1.6; }
rect.barra-cs { cursor: help; }
.pestanas-principales {
    position: sticky; top: 0; z-index: 60;
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    background: var(--carta); border: 1px solid var(--borde);
    border-radius: 13px; padding: 12px 16px; margin: 22px 0;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.pestana-principal {
    font: inherit; font-size: 15px; cursor: pointer; font-weight: 600;
    background: var(--fondo-alterno); color: var(--texto);
    border: 1px solid var(--borde); border-radius: 10px; padding: 9px 20px;
}
.pestana-principal:hover { border-color: var(--acento); }
.pestana-principal.activa { background: var(--acento); color: #12161f; border-color: var(--acento); }
#tab-planificacion .controles { top: 74px; }
__ESTILO_BASE__
__ESTILO_CONC__
</style>
</head>
<body>
<div class="envoltorio">
  <nav class="pestanas-principales">
    <button class="pestana-principal activa" data-tab="planificacion" type="button">Planificación de CPU</button>
    <button class="pestana-principal" data-tab="concurrencia" type="button">Concurrencia</button>
  </nav>
  <div id="tab-planificacion" class="tab-panel">
__CUERPO_PLAN__
  </div>
  <div id="tab-concurrencia" class="tab-panel" style="display:none">
__CUERPO_CONC__
  </div>
</div>
<script>
__SCRIPT_TABS__
</script>
<script>
__SCRIPT_GANTT__
</script>
<script>
__SCRIPT_CONC__
</script>
</body>
</html>
"""

SCRIPT_PESTANAS = """
(function () {
    const INICIAL = "__TAB_INICIAL__";
    const botones = document.querySelectorAll('.pestana-principal');
    function activar(nombre) {
        botones.forEach(function (b) {
            b.classList.toggle('activa', b.getAttribute('data-tab') === nombre);
        });
        document.querySelectorAll('.tab-panel').forEach(function (panel) {
            panel.style.display = (panel.id === 'tab-' + nombre) ? '' : 'none';
        });
    }
    botones.forEach(function (b) {
        b.addEventListener('click', function () { activar(b.getAttribute('data-tab')); });
    });
    activar(INICIAL);
})();
"""


def obtener_argumentos() -> argparse.Namespace:
    """Lee los argumentos de la línea de comandos, todos con valor por defecto."""
    analizador = argparse.ArgumentParser(
        description="Simulador de planificación de CPU y de los 5 problemas de concurrencia.",
    )
    analizador.add_argument("--archivo", "-a", default=ARCHIVO_POR_DEFECTO,
                            help=f"archivo de carga de trabajo (por defecto: {ARCHIVO_POR_DEFECTO})")
    analizador.add_argument("--aleatorio", "-n", type=int, default=0, metavar="N",
                            help="genera N procesos al azar en vez de leer el archivo")
    analizador.add_argument("--semilla", type=int, default=None,
                            help="semilla, para que la carga aleatoria sea siempre la misma")
    analizador.add_argument("--ordenado", action="store_true",
                            help="genera la carga aleatoria en orden de llegada (IDs correlativos)")
    analizador.add_argument("--quantum", "-q", type=int, default=QUANTUM_POR_DEFECTO,
                            help=f"quantum del Round Robin (por defecto: {QUANTUM_POR_DEFECTO})")
    analizador.add_argument("--simulador", "-m", choices=["planificacion", "concurrencia"],
                            default="planificacion",
                            help="pestaña que se abre por defecto (por defecto: planificacion)")
    analizador.add_argument("--salida", "-s", default=REPORTE_POR_DEFECTO,
                            help=f"nombre del reporte (por defecto: {REPORTE_POR_DEFECTO})")
    analizador.add_argument("--sin-abrir", action="store_true",
                            help="no abre el navegador al terminar")
    return analizador.parse_args()


def cargar_procesos(opciones: argparse.Namespace) -> tuple[list, str]:
    """
    Devuelve la lista de procesos y una descripción de de dónde salió.
    Se prioriza la carga aleatoria si se pidió con --aleatorio.
    """
    if opciones.aleatorio > 0:
        procesos = GestorProcesos.generar_aleatorios(
            opciones.aleatorio, semilla=opciones.semilla, ordenado=opciones.ordenado
        )
        descripcion = f"{opciones.aleatorio} procesos generados al azar"
        if opciones.ordenado:
            descripcion += " (en orden de llegada)"
        if opciones.semilla is not None:
            descripcion += f" (semilla {opciones.semilla})"
        return procesos, descripcion

    ruta = Path(opciones.archivo)
    if not ruta.exists():
        print(f"[aviso] No existe '{ruta}', se generan 10 procesos al azar.")
        return GestorProcesos.generar_aleatorios(10), "10 procesos generados al azar"

    return GestorProcesos.leer_desde_txt(ruta), f"archivo {ruta.name}"


def generar_reporte_unificado(
    procesos,
    planificadores,
    problemas,
    ruta_salida: str | Path,
    tab_inicial: str = "planificacion",
) -> Path:
    """Escribe el reporte con los dos simuladores y devuelve su ruta."""
    ejecutar_todas(planificadores)
    vistas_sin_cs, vistas_con_cs = _construir_variantes(planificadores)
    cuerpo_plan = _cuerpo_html(vistas_sin_cs, vistas_con_cs, procesos, "", 0)
    cuerpo_conc = cuerpo_concurrencia(problemas)

    datos_gantt = json.dumps(_datos_graficos(vistas_sin_cs, vistas_con_cs), ensure_ascii=True)
    script_gantt = _SCRIPT_GANT.replace("__DATOS__", datos_gantt)
    datos_conc = json.dumps(datos_concurrencia(problemas), ensure_ascii=True)
    script_conc = SCRIPT_CONCURRENCIA.replace("__DATOS_CONC__", datos_conc)
    script_pestanas = SCRIPT_PESTANAS.replace("__TAB_INICIAL__", tab_inicial)

    html = (
        PLANTILLA_UNIFICADA
        .replace("__VARIABLES_TEMA__", _estilos_como_css())
        .replace("__ESTILO_BASE__", _ESTILO_BASE)
        .replace("__ESTILO_CONC__", ESTILO_CONCURRENCIA)
        .replace("__CUERPO_PLAN__", cuerpo_plan)
        .replace("__CUERPO_CONC__", cuerpo_conc)
        .replace("__SCRIPT_TABS__", script_pestanas)
        .replace("__SCRIPT_GANTT__", script_gantt)
        .replace("__SCRIPT_CONC__", script_conc)
    )

    destino = Path(ruta_salida)
    destino.write_text(html, encoding="utf-8")
    return destino


def main() -> None:
    opciones = obtener_argumentos()

    procesos, origen = cargar_procesos(opciones)
    planificadores = construir_politicas(procesos, quantum=opciones.quantum)
    problemas = construir_problemas()

    carpeta = Path(__file__).parent

    ruta_reporte = generar_reporte_unificado(
        procesos,
        planificadores,
        problemas,
        carpeta / opciones.salida,
        tab_inicial=opciones.simulador,
    )

    rutas_individuales = generar_reportes_individuales(carpeta)

    print(f"Carga de trabajo   : {origen}  ({len(procesos)} procesos)")
    print(f"Quantum            : {opciones.quantum}")
    print(f"Problemas concurrencia : {len(problemas)}")
    print(f"Reporte unificado  : {ruta_reporte.name}")
    print(f"Reportes individuales  : {len(rutas_individuales)} archivos")

    if not opciones.sin_abrir:
        webbrowser.open(ruta_reporte.resolve().as_uri())


if __name__ == "__main__":
    main()
