"""
Verificación del simulador y del reporte HTML.

Comprueba que las cuatro políticas respetan las invariantes de la planificación
en muchos escenarios, y que el HTML generado quedó bien formado.

    py _verificar.py

Este archivo es opcional: no es parte de la entrega, se puede borrar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from simulador_so import (
    GestorProcesos,
    Proceso,
    PlanificadorFCFS,
    PlanificadorRoundRobin,
    TIEMPO_CONTEXT_SWITCH,
    construir_politicas,
    ejecutar_todas,
    generar_reporte_html,
    _construir_variantes,
    _datos_graficos,
)

fallos: list[str] = []


def comprobar(condicion: bool, mensaje: str) -> None:
    if not condicion:
        fallos.append(mensaje)


# ==========================================================================
#  Invariantes de la simulación
# ==========================================================================

def validar(planificador, etiqueta: str) -> None:
    comprobar(all(p.tf is not None for p in planificador.procesos),
              f"{etiqueta}: hay procesos sin tiempo de finalización")

    anterior = 0
    for bloque in planificador.bloques:
        comprobar(bloque.inicio >= anterior,
                  f"{etiqueta}: hueco o solape en t={bloque.inicio} (anterior={anterior})")
        comprobar(bloque.fin > bloque.inicio,
                  f"{etiqueta}: bloque de duración 0 en t={bloque.inicio}")
        anterior = bloque.fin

    trabajo = sum(b.duracion for b in planificador.bloques)
    esperado = sum(p.duracion for p in planificador.procesos)
    comprobar(trabajo == esperado,
              f"{etiqueta}: trabajo de CPU {trabajo} distinto de la suma de ráfagas {esperado}")

    llegada_menor = min(p.t_llegada for p in planificador.procesos)
    comprobar(planificador.bloques[0].inicio == llegada_menor,
              f"{etiqueta}: el primer bloque arranca en t={planificador.bloques[0].inicio}, "
              f"pero el proceso más temprano llega en t={llegada_menor}")

    for proceso in planificador.procesos:
        comprobar(proceso.tr == proceso.tf - proceso.t_llegada,
                  f"{etiqueta}/{proceso.id}: TR mal calculado")
        comprobar(proceso.te == proceso.tr - proceso.duracion,
                  f"{etiqueta}/{proceso.id}: TE mal calculado")
        comprobar(proceso.te >= 0,
                  f"{etiqueta}/{proceso.id}: tiempo de espera negativo ({proceso.te})")
        comprobar(proceso.tf >= proceso.t_llegada + proceso.duracion,
                  f"{etiqueta}/{proceso.id}: termina antes de llegar más su ráfaga")
        ejecutado = sum(b.duracion for b in planificador.bloques
                        if b.id_proceso == proceso.id)
        comprobar(ejecutado == proceso.duracion,
                  f"{etiqueta}/{proceso.id}: ejecutó {ejecutado} de {proceso.duracion} unidades")


def validar_cs(planificador, etiqueta: str) -> None:
    """Comprueba la variante con cambio de contexto derivada de una política ya corrida."""
    vista_sin, vista_con = _construir_variantes([planificador])
    v0, v1 = vista_sin[0], vista_con[0]

    anterior = None
    cambios = 0
    for bloque in v0["bloques"]:
        if anterior is not None and bloque.id_proceso != anterior:
            cambios += 1
        anterior = bloque.id_proceso

    comprobar(len(v1["bloques_cs"]) == cambios,
              f"{etiqueta}: hay {len(v1['bloques_cs'])} franjas CS y {cambios} cambios de proceso")
    comprobar(all(b.duracion == TIEMPO_CONTEXT_SWITCH for b in v1["bloques_cs"]),
              f"{etiqueta}: alguna franja CS no mide {TIEMPO_CONTEXT_SWITCH}")
    comprobar(v1["tiempo_total"] == v0["tiempo_total"] + cambios * TIEMPO_CONTEXT_SWITCH,
              f"{etiqueta}: el makespan con CS no es el de sin CS más los cambios")

    linea = sorted(list(v1["bloques"]) + list(v1["bloques_cs"]), key=lambda b: b.inicio)
    anterior_fin = 0
    for bloque in linea:
        comprobar(bloque.inicio >= anterior_fin,
                  f"{etiqueta}: solape en el Gantt con CS en t={bloque.inicio}")
        anterior_fin = bloque.fin

    te_sin = {f["id"]: f["te"] for f in v0["procesos"]}
    for fila in v1["procesos"]:
        comprobar(fila["tr"] == fila["tf"] - fila["t_llegada"],
                  f"{etiqueta}/{fila['id']}: TR con CS mal calculado")
        comprobar(fila["te"] == fila["tr"] - fila["duracion"],
                  f"{etiqueta}/{fila['id']}: TE con CS mal calculado")
        comprobar(fila["te"] >= te_sin[fila["id"]],
                  f"{etiqueta}/{fila['id']}: el CS redujo el tiempo de espera")


escenarios = [
    ("procesos.txt", GestorProcesos.leer_desde_txt("procesos.txt")),
    ("un solo proceso", [Proceso("P0", 5, 1)]),
    ("todos en t=0", [Proceso(f"P{i}", 0, i % 5 + 1) for i in range(6)]),
    ("llegadas separadas", [Proceso("P0", 0, 5), Proceso("P1", 20, 2), Proceso("P2", 40, 3)]),
    ("ráfaga mínima", [Proceso("P0", 0, 1), Proceso("P1", 0, 1)]),
    ("sin nombres numéricos", [Proceso("uno", 0, 3), Proceso("dos", 1, 4),
                               Proceso("tres", 2, 2)]),
    ("ids con varios dígitos", [Proceso(f"P{i}", i, i + 1) for i in range(12)]),
]
for cantidad in (4, 10, 50, 200):
    escenarios.append((f"aleatorio N={cantidad}",
                       GestorProcesos.generar_aleatorios(cantidad, semilla=7)))

for etiqueta, procesos in escenarios:
    for quantum in (1, 2, 4, 100):
        for planificador in construir_politicas(procesos, quantum=quantum):
            planificador.ejecutar()
            validar(planificador, f"{etiqueta} q={quantum}")
            validar_cs(planificador, f"{etiqueta} q={quantum}")

# ==========================================================================
#  Comportamiento propio de cada política
# ==========================================================================

procesos = GestorProcesos.leer_desde_txt("procesos.txt")
ids_ordenados = [p.t_llegada for p in procesos]

fcfs = PlanificadorFCFS(procesos)
fcfs.ejecutar()
comprobar([b.id_proceso for b in fcfs.bloques] == [p.id for p in procesos],
          "FCFS no respeta el orden de llegada")
comprobar(fcfs.bloques[0].inicio == ids_ordenados[0],
          "FCFS no arranca en la llegada más temprana")
comprobar(len(fcfs.bloques) == len(procesos),
          "FCFS no produce un bloque por proceso (está expulsando)")

srtf = construir_politicas(procesos, quantum=2)[2]
srtf.ejecutar()
comprobar(srtf.resumen["te_prom"] <= fcfs.resumen["te_prom"],
          "SRTF empeoró el tiempo de espera promedio frente a FCFS")
comprobar(len(srtf.bloques) > len(procesos),
          "SRTF no expulsó a ningún proceso en una carga donde debería hacerlo")
ids_repetidos = [b.id_proceso for b in srtf.bloques]
comprobar(len(ids_repetidos) != len(set(ids_repetidos)),
          "SRTF no muestra ninguna expulsión en el Gantt")

for quantum in (1, 2, 4):
    rr = PlanificadorRoundRobin(procesos, quantum=quantum)
    rr.ejecutar()
    comprobar(all(b.duracion <= quantum for b in rr.bloques),
              f"RR con q={quantum}: hay bloques más largos que el quantum")
    turnos = {}
    for bloque in rr.bloques:
        turnos.setdefault(bloque.id_proceso, bloque.inicio)
    comprobar(list(turnos) == ["P0", "P1", "P2", "P3", "P4", "P5", "P6", "P7"],
              f"RR con q={quantum}: orden de primeros turnos inesperado {list(turnos)}")

rr_grande = PlanificadorRoundRobin(procesos, quantum=999)
rr_grande.ejecutar()
comprobar(len(rr_grande.bloques) == len(procesos),
          "Con quantum mayor que la ráfaga más larga, RR debe dar un bloque por proceso")

# La carga original no debe mutarse entre políticas
comprobar(all(p.restante == p.duracion and p.tf is None for p in procesos),
          "Las políticas mutaron la carga de trabajo original")

# generar_aleatorios(ordenado=True) sale en orden de llegada con IDs correlativos
ordenados = GestorProcesos.generar_aleatorios(25, semilla=5, ordenado=True)
comprobar([p.id for p in ordenados] == [f"P{i}" for i in range(25)],
          "generar_aleatorios(ordenado=True) no asigna los IDs correlativos")
comprobar(all(ordenados[i].t_llegada <= ordenados[i + 1].t_llegada
              for i in range(len(ordenados) - 1)),
          "generar_aleatorios(ordenado=True) no devuelve los procesos en orden de llegada")

# Por defecto la carga sigue saliendo barajada
barajados = GestorProcesos.generar_aleatorios(25, semilla=5)
comprobar([p.id for p in barajados] != [f"P{i}" for i in range(25)],
          "generar_aleatorios(ordenado=False) debería devolver la lista barajada")

# ==========================================================================
#  El reporte HTML
# ==========================================================================

ruta = generar_reporte_html(procesos, construir_politicas(procesos, quantum=2),
                            origen="procesos.txt", quantum=2)
html = ruta.read_text(encoding="utf-8")

comprobar(not re.search(r"__[A-Z_]+__", html),
          f"El HTML tiene marcadores sin reemplazar: {re.findall(r'__[A-Z_]+__', html)}")
for etiqueta_obligatoria in ("<!DOCTYPE html>", "<svg", "Carga de trabajo", "Comparativa",
                             "Round Robin", "PROMEDIO", "class=\"barra\"", ".globo",
                             "id=\"vista-sin-cs\"", "id=\"vista-con-cs\"",
                             "id=\"boton-cs\"", "id=\"boton-play\"", "id=\"boton-reset\"",
                             "id=\"velocidad\"", "data-cola=\"cpu\"",
                             "data-cola=\"listos\"", "data-cola=\"terminados\"",
                             "class=\"cursor\"", "class=\"barra-cs\"", "barra-cs"):
    comprobar(etiqueta_obligatoria in html,
              f"El HTML no contiene {etiqueta_obligatoria!r}")

# El JavaScript recibe exactamente los datos de la simulación
coincidencia = re.search(r"const DATOS = (\{.*?\});\n", html, re.DOTALL)
comprobar(coincidencia is not None, "No se encontró el bloque de datos JSON en el HTML")
if coincidencia:
    datos = json.loads(coincidencia.group(1))
    for clave in ("sin_cs", "con_cs"):
        comprobar(clave in datos, f"Falta la variante {clave!r} en los datos")
        comprobar(len(datos[clave]["graficos"]) == 4,
                  f"La variante {clave} lleva {len(datos[clave]['graficos'])} gráficos")

    for indice, planificador in enumerate(construir_politicas(procesos, quantum=2)):
        ejecutar_todas([planificador])
        for clave in ("sin_cs", "con_cs"):
            grafico = datos[clave]["graficos"][indice]
            comprobar(len(grafico["bloques"]) == len(planificador.bloques),
                      f"{planificador.nombre} ({clave}): los bloques del HTML no coinciden")
            comprobar(set(grafico["colores"]) == set(grafico["procesos"]),
                      f"{planificador.nombre} ({clave}): hay procesos sin color asignado")
            comprobar(all(re.fullmatch(r"#[0-9a-f]{6}", c)
                          for c in grafico["colores"].values()),
                      f"{planificador.nombre} ({clave}): hay colores con formato inválido")
            for bloque in grafico["bloques"]:
                comprobar(bloque["id"] in grafico["colores"],
                          f"{planificador.nombre} ({clave}): el bloque {bloque['id']} sin color")
            comprobar(all({"id", "llegada", "tf"} <= set(p) for p in grafico["info"]),
                      f"{planificador.nombre} ({clave}): falta información para las colas")

    # La variante sin CS no debe tener franjas CS; la con CS, sí
    comprobar(all(len(g["bloques_cs"]) == 0 for g in datos["sin_cs"]["graficos"]),
              "La variante sin CS tiene franjas de contexto")
    comprobar(all(len(g["bloques_cs"]) > 0 for g in datos["con_cs"]["graficos"]),
              "La variante con CS no tiene ninguna franja de contexto")
    comprobar(all(g["con_cs"] is True for g in datos["con_cs"]["graficos"]),
              "Los gráficos con CS no están marcados como tales")

# La paleta se reutiliza en ciclo, sin colores aleatorios
politicas_paleta = construir_politicas(procesos, quantum=2)
ejecutar_todas(politicas_paleta)
datos_directos = _datos_graficos(*_construir_variantes(politicas_paleta))
colores = list(datos_directos["sin_cs"]["graficos"][0]["colores"].values())
comprobar(len(colores) == len(set(colores)),
          "Con 8 procesos y 10 colores no debería repetirse ninguno")

# Una carga más grande que la paleta debe repetir colores, y en orden
procesos_30 = GestorProcesos.generar_aleatorios(30, semilla=3)
politicas_30 = construir_politicas(procesos_30, quantum=2)
ejecutar_todas(politicas_30)
datos_30 = _datos_graficos(*_construir_variantes(politicas_30))
colores_30 = list(datos_30["sin_cs"]["graficos"][0]["colores"].values())
comprobar(len(colores_30) == 30, "Se esperaban 30 procesos en el gráfico")
comprobar(colores_30[:10] == colores_30[10:20],
          "El ciclo de la paleta no se reinicia en el proceso 11")
comprobar(colores_30[20:] == colores_30[:10],
          "El ciclo de la paleta no se reinicia en el proceso 21")

# ==========================================================================
#  Regresiones: lo que se decidió quitar
# ==========================================================================

fuente = Path("simulador_so.py").read_text(encoding="utf-8")
comprobar("prioridad" not in fuente.lower(), "Todavía aparece 'prioridad' en el código")
comprobar("matplotlib" not in fuente, "Todavía se importa matplotlib")
comprobar("tabulate" not in fuente, "Todavía se importa tabulate")
comprobar(not list(Path(".").glob("graficos")), "Todavía existe la carpeta graficos/")
comprobar(not Path("resultados.txt").exists(), "Todavía existe resultados.txt")

# ==========================================================================

if fallos:
    print(f"FALLOS: {len(fallos)}")
    for fallo in fallos[:30]:
        print("  -", fallo)
else:
    total = sum(len(c[1]) for c in escenarios)
    print(f"OK - {len(escenarios)} escenarios x 4 políticas x 4 valores de quantum")
    print(f"     {total} procesos validados, HTML correcto, 0 fallos")
