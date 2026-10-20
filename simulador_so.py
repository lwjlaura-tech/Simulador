from __future__ import annotations

import copy
import json
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import List, Sequence


TEMA = {
    "fondo": "#151a26",         
    "fondo_alterno": "#1b2130",  
    "carta": "#1e2534",          
    "borde": "#2f3a4f",          
    "texto": "#e6ebf5",          
    "texto_suave": "#636160ff",    
    "acento": "#5b9dff",         
    "exito": "#ffffff",          
    "destacado": "#ffb454",      
}

PALETA_PROCESOS = [
    "#ffffff",  
    "#3ddc97",  
    "#ffb454",  
    "#ff6b8b",  
    "#b07cff",  
    "#4dd0e1",  
    "#f4a261",  
    "#9ccc65",  
    "#e06c9f",  
    "#7f9cf5",  
]

ACENTOS_POLITICA = {
    "FCFS": "#5b9dff", 
    "SJF": "#3ddc97",
    "SRTF": "#ffb454", 
    "Round Robin": "#ff6b8b",
}

TIEMPO_CONTEXT_SWITCH = 0.25


def color_de_proceso(indice: int) -> str:
    """Devuelve el color del proceso número `indice`, reutilizando la paleta en ciclo."""
    return PALETA_PROCESOS[indice % len(PALETA_PROCESOS)]


@dataclass
class BloqueGantt:


    id_proceso: str
    inicio: int
    fin: int

    @property
    def duracion(self) -> int:
        return self.fin - self.inicio

    def __repr__(self) -> str:
        return f"BloqueGantt({self.id_proceso}, {self.inicio}→{self.fin})"


class Proceso:
    """PCB (Process Control Block) con lo mínimo para simular la planificación."""

    def __init__(self, id_proceso: str, t_llegada: int, duracion: int):
        if int(duracion) <= 0:
            raise ValueError(f"La duración de {id_proceso} debe ser mayor que 0.")
        if int(t_llegada) < 0:
            raise ValueError(f"El tiempo de llegada de {id_proceso} no puede ser negativo.")

        self.id = str(id_proceso)
        self.t_llegada = int(t_llegada)
        self.duracion = int(duracion)
        self.restante = int(duracion)

        self.tf: int | None = None  
        self.tr: int | None = None   
        self.te: int | None = None  

    def calcular_metricas(self) -> None:
        """Deriva el tiempo de retorno y el de espera a partir del tiempo de fin."""
        if self.tf is not None:
            self.tr = self.tf - self.t_llegada
            self.te = self.tr - self.duracion

    def reiniciar(self) -> None:
        """Devuelve el proceso a su estado inicial, con la ráfaga completa."""
        self.restante = self.duracion
        self.tf = self.tr = self.te = None

    def __repr__(self) -> str:
        return f"Proceso({self.id}, llegada={self.t_llegada}, duración={self.duracion})"


#  GESTOR DE LA CARGA DE TRABAJO

class GestorProcesos:
    """Carga las listas de procesos desde un archivo o las genera al azar."""

    @staticmethod
    def leer_desde_txt(ruta_archivo: str | Path) -> List[Proceso]:
        """
        Lee los procesos de un archivo de texto, en el orden que aparezca.
        Cada línea tiene el formato:  ID  T_LLEGADA  DURACIÓN
        Se aceptan espacios, tabuladores o comas como separadores, y se ignoran
        las líneas vacías y las que empiezan con '#'.
        """
        ruta = Path(ruta_archivo)
        if not ruta.exists():
            raise FileNotFoundError(f"No se encontró el archivo de carga: {ruta}")

        procesos: List[Proceso] = []
        with ruta.open("r", encoding="utf-8") as archivo:
            for numero_linea, linea in enumerate(archivo, start=1):
                texto = linea.strip()
                if not texto or texto.startswith("#"):
                    continue

                campos = texto.replace(",", " ").replace(";", " ").split()
                if len(campos) < 3:
                    raise ValueError(
                        f"{ruta.name}, línea {numero_linea}: se esperaban 3 campos "
                        f"(ID, T_LLEGADA, DURACIÓN) y se leyeron {campos}"
                    )
                try:
                    tiempo_llegada = int(campos[1])
                    duracion = int(campos[2])
                except ValueError as error:
                    raise ValueError(
                        f"{ruta.name}, línea {numero_linea}: hay valores que no son "
                        f"números enteros en {campos}"
                    ) from error

                procesos.append(Proceso(campos[0], tiempo_llegada, duracion))

        if not procesos:
            raise ValueError(f"{ruta.name} no contiene ningún proceso válido.")
        return procesos

    @staticmethod
    def generar_aleatorios(
        cantidad: int = 10,
        llegada_maxima: int = 15,
        duracion_maxima: int = 10,
        semilla: int | None = None,
        ordenado: bool = False,
    ) -> List[Proceso]:
        """
        Genera N procesos al azar.

        Con `ordenado=True` se devuelven en orden de llegada y con los identificadores
        correlativos (P0, P1, ...), igual que en `procesos.txt`. Con `ordenado=False`
        (por defecto) la lista sale barajada, como si el archivo viniera desordenado.
        """
        if cantidad <= 0:
            raise ValueError("La cantidad de procesos debe ser mayor que 0.")

        azar = random.Random(semilla)

        if ordenado:
            parejas = [
                (azar.randint(0, llegada_maxima), azar.randint(1, duracion_maxima))
                for _ in range(cantidad)
            ]
            parejas.sort(key=lambda par: par[0])
            return [
                Proceso(f"P{i}", llegada, duracion)
                for i, (llegada, duracion) in enumerate(parejas)
            ]

        procesos = [
            Proceso(f"P{i}", azar.randint(0, llegada_maxima), azar.randint(1, duracion_maxima))
            for i in range(cantidad)
        ]
        azar.shuffle(procesos)
        return procesos


#  PLANIFICADOR BASE

def clave_de_orden(id_proceso: str) -> tuple:
    """Ordena P2 antes que P10, y deja los nombres sin números al final."""
    numeros = re.search(r"(\d+)\s*$", id_proceso)
    if numeros:
        return (0, int(numeros.group(1)), id_proceso)
    return (1, 0, id_proceso)


class PlanificadorBase(ABC):
    """Plantilla común a todos los algoritmos de planificación."""

    descripcion = ""
    acento = TEMA["acento"]
    expulsivo = False

    def __init__(self, procesos: Sequence[Proceso], nombre: str):
        # Copia profunda: cada política trabaja sobre su propia copia y la
        # carga original queda intacta para las demás.
        self.procesos: List[Proceso] = copy.deepcopy(list(procesos))
        self.nombre = nombre
        self.bloques: List[BloqueGantt] = []

    # -- Kernel de la simulación ------------------------------------------
    def ejecutar(self) -> None:
        """
        Corre la simulación completa. Se puede llamar varias veces seguidas:
        cada vez parte de cero, así que no duplica los bloques del Gantt.
        """
        self.bloques.clear()
        for proceso in self.procesos:
            proceso.reiniciar()
        self._simular()
        self.calcular_metricas()

    @abstractmethod
    def _simular(self) -> None:
        """
        Lo que cada política hace de su propia cuenta: llenar self.bloques con
        la cronología de ejecución y fijar el TF de cada proceso.
        """
        raise NotImplementedError

    # -- Métricas -----------------------------------------------------------
    def calcular_metricas(self) -> None:
        for proceso in self.procesos:
            proceso.calcular_metricas()

    @property
    def cantidad(self) -> int:
        return len(self.procesos)

    @property
    def tiempo_total(self) -> int:
        """Instante en que termina el último proceso, es decir, el final del Gantt."""
        return max(bloque.fin for bloque in self.bloques) if self.bloques else 0

    @property
    def ids_en_orden(self) -> List[str]:
        """Identificadores ordenados: así se decide el color de cada proceso."""
        return sorted((p.id for p in self.procesos), key=clave_de_orden)

    @property
    def procesos_ordenados(self) -> List[Proceso]:
        """Los mismos procesos pero ordenados por identificador, para las tablas."""
        return sorted(self.procesos, key=lambda p: clave_de_orden(p.id))

    @property
    def resumen(self) -> dict:
        """Promedios y máximos del sistema, listos para mostrar."""
        if not self.cantidad:
            return {"tf_prom": 0.0, "tr_prom": 0.0, "te_prom": 0.0,
                    "tf_max": 0, "te_max": 0, "rafaga_total": 0.0, "cantidad": 0}
        return {
            "cantidad": self.cantidad,
            "rafaga_total": sum(p.duracion for p in self.procesos) / self.cantidad,
            "tf_prom": sum(p.tf for p in self.procesos) / self.cantidad,
            "tr_prom": sum(p.tr for p in self.procesos) / self.cantidad,
            "te_prom": sum(p.te for p in self.procesos) / self.cantidad,
            "tf_max": max(p.tf for p in self.procesos),
            "te_max": max(p.te for p in self.procesos),
        }


#  POLÍTICA 1 - FCFS  (First-Come, First-Served)


class PlanificadorFCFS(PlanificadorBase):

    descripcion = (
        "El proceso que llega primero entra primero."
    )
    acento = ACENTOS_POLITICA["FCFS"]

    def __init__(self, procesos: Sequence[Proceso]):
        super().__init__(procesos, "FCFS")

    def _simular(self) -> None:
        pendientes = sorted(self.procesos, key=lambda p: (p.t_llegada, clave_de_orden(p.id)))
        tiempo_actual = 0

        for proceso in pendientes:
            # La CPU queda ociosa hasta que llegue el proceso
            if tiempo_actual < proceso.t_llegada:
                tiempo_actual = proceso.t_llegada

            inicio = tiempo_actual
            fin = inicio + proceso.duracion
            self.bloques.append(BloqueGantt(proceso.id, inicio, fin))
            proceso.restante = 0
            proceso.tf = fin
            tiempo_actual = fin



#  POLÍTICA 2 - SJF  (Shortest Job First, no expulsivo)

class PlanificadorSJF(PlanificadorBase):

    descripcion = (
        "Entre los procesos que ya han llegado elige el de menor ráfaga y lo ejecuta "
    )
    acento = ACENTOS_POLITICA["SJF"]

    def __init__(self, procesos: Sequence[Proceso]):
        super().__init__(procesos, "SJF")

    def _simular(self) -> None:
        tiempo_actual = 0
        completados = 0
        pendientes = list(self.procesos)

        while completados < self.cantidad:
            listos = [p for p in pendientes if p.t_llegada <= tiempo_actual]

            if not listos:
                # Nadie esperando: se salta el tiempo hasta la próxima llegada
                tiempo_actual = min(p.t_llegada for p in pendientes)
                continue

            # Menor ráfaga; si empatan, el que llegó antes
            elegido = min(listos, key=lambda p: (p.duracion, p.t_llegada, clave_de_orden(p.id)))

            inicio = tiempo_actual
            fin = inicio + elegido.duracion
            self.bloques.append(BloqueGantt(elegido.id, inicio, fin))
            elegido.restante = 0
            elegido.tf = fin
            tiempo_actual = fin

            pendientes.remove(elegido)
            completados += 1



#  POLÍTICA 3 - SRTF  (Shortest Remaining Time First, expulsivo)

class PlanificadorSRTF(PlanificadorBase):

    descripcion = (
        "Se parece a SJF pero de forma expulsiva."
    )
    acento = ACENTOS_POLITICA["SRTF"]
    expulsivo = True

    def __init__(self, procesos: Sequence[Proceso]):
        super().__init__(procesos, "SRTF")

    def _simular(self) -> None:
        tiempo_actual = 0
        completados = 0
        proceso_en_cpu: Proceso | None = None
        inicio_bloque = 0

        def cerrar_bloque(hasta: int) -> None:
            """Cierra la franja abierta del proceso que venía en la CPU."""
            nonlocal proceso_en_cpu
            if proceso_en_cpu is not None and hasta > inicio_bloque:
                self.bloques.append(BloqueGantt(proceso_en_cpu.id, inicio_bloque, hasta))
            proceso_en_cpu = None

        while completados < self.cantidad:
            listos = [p for p in self.procesos
                      if p.t_llegada <= tiempo_actual and p.restante > 0]

            if not listos:
                # Cola vacía: cerrar la franja en curso y saltar a la próxima llegada
                cerrar_bloque(tiempo_actual)
                futuras = [p.t_llegada for p in self.procesos if p.restante > 0]
                if not futuras:
                    break
                tiempo_actual = min(futuras)
                continue

            # Menor tiempo restante; si empatan, el que llegó antes
            elegido = min(listos, key=lambda p: (p.restante, p.t_llegada, clave_de_orden(p.id)))

            # Conmutación: cerrar la franja anterior y abrir la del nuevo proceso
            if elegido.id != (proceso_en_cpu.id if proceso_en_cpu else None):
                cerrar_bloque(tiempo_actual)
                proceso_en_cpu = elegido
                inicio_bloque = tiempo_actual

            # Una unidad de tiempo de CPU
            elegido.restante -= 1
            tiempo_actual += 1

            if elegido.restante == 0:
                elegido.tf = tiempo_actual
                completados += 1
                cerrar_bloque(tiempo_actual)

        cerrar_bloque(tiempo_actual)


#  POLÍTICA 4 - ROUND ROBIN  (quantum configurable)


class PlanificadorRoundRobin(PlanificadorBase):
    """Turnos circulares de q unidades; al agotar el quantum vuelve al final de la cola."""

    descripcion = (
        "Cada proceso recibe la CPU durante q unidades y después pasa al final de la cola"
    )
    acento = ACENTOS_POLITICA["Round Robin"]

    def __init__(self, procesos: Sequence[Proceso], quantum: int = 2):
        if int(quantum) <= 0:
            raise ValueError("El quantum debe ser un entero mayor que 0.")
        super().__init__(procesos, f"Round Robin (q={int(quantum)})")
        self.quantum = int(quantum)

    def _simular(self) -> None:
        tiempo_actual = 0
        completados = 0
        cola_listos: List[Proceso] = []
        sin_llegar = sorted(self.procesos, key=lambda p: (p.t_llegada, clave_de_orden(p.id)))

        while completados < self.cantidad:
            # Los recién llegados entran al final de la cola
            while sin_llegar and sin_llegar[0].t_llegada <= tiempo_actual:
                cola_listos.append(sin_llegar.pop(0))

            # Cola vacía: la CPU espera hasta la próxima llegada
            if not cola_listos:
                if not sin_llegar:
                    break
                tiempo_actual = sin_llegar[0].t_llegada
                continue

            proceso = cola_listos.pop(0)
            inicio = tiempo_actual
            ejecucion = min(self.quantum, proceso.restante)
            fin = inicio + ejecucion

            self.bloques.append(BloqueGantt(proceso.id, inicio, fin))
            proceso.restante -= ejecucion
            tiempo_actual = fin

            # Los que llegaron durante este turno también entran al final
            while sin_llegar and sin_llegar[0].t_llegada <= tiempo_actual:
                cola_listos.append(sin_llegar.pop(0))

            if proceso.restante > 0:
                cola_listos.append(proceso)   # se agotó el quantum, vuelve al final
            else:
                proceso.tf = tiempo_actual
                completados += 1




#  UTILIDADES DE LA SIMULACIÓN

def construir_politicas(procesos: Sequence[Proceso], quantum: int = 2) -> List[PlanificadorBase]:
    return [
        PlanificadorFCFS(procesos),
        PlanificadorSJF(procesos),
        PlanificadorSRTF(procesos),
        PlanificadorRoundRobin(procesos, quantum=quantum),
    ]


def ejecutar_todas(planificadores: Sequence[PlanificadorBase]) -> List[PlanificadorBase]:
    """Corre cada política y devuelve la misma lista, ya simulada."""
    for planificador in planificadores:
        planificador.ejecutar()
    return list(planificadores)


#  VARIANTES CON Y SIN CAMBIO DE CONTEXTO
#
#  El cambio de contexto se deriva del resultado ya simulado: cada vez que dos
#  franjas consecutivas pertenecen a procesos distintos hay una conmutación.
#  Se inserta una franja "CS" y se desplaza el resto del Gantt hacia la derecha,
#  con lo cual las métricas suben (Round Robin, que conmuta más, es la más
#  castigada). El orden de atención no cambia: solo se corre el tiempo.

def _desplazar_bloques(
    bloques: Sequence[BloqueGantt], cs: int
) -> tuple[List[BloqueGantt], List[BloqueGantt]]:
    """Devuelve los bloques desplazados por el CS y las franjas de cambio de contexto."""
    if cs <= 0:
        return [BloqueGantt(b.id_proceso, b.inicio, b.fin) for b in bloques], []

    desplazamiento = 0
    salida: List[BloqueGantt] = []
    franjas_cs: List[BloqueGantt] = []
    anterior: str | None = None

    for bloque in bloques:
        if anterior is not None and bloque.id_proceso != anterior:
            inicio_cs = bloque.inicio + desplazamiento
            franjas_cs.append(BloqueGantt("CS", inicio_cs, inicio_cs + cs))
            desplazamiento += cs

        salida.append(BloqueGantt(
            bloque.id_proceso, bloque.inicio + desplazamiento, bloque.fin + desplazamiento
        ))
        anterior = bloque.id_proceso

    return salida, franjas_cs


def _vista(planificador: PlanificadorBase, con_cs: bool) -> dict:
    """
    Construye la vista de una política para la variante pedida: bloques (ya
    desplazados si corresponde), franjas de CS, métricas por proceso y resumen.
    """
    cs = TIEMPO_CONTEXT_SWITCH if con_cs else 0
    bloques, franjas_cs = _desplazar_bloques(planificador.bloques, cs)

    tf_por_id: dict[str, int] = {}
    for bloque in bloques:
        tf_por_id[bloque.id_proceso] = bloque.fin   # el último valor es el final real

    filas = []
    for proceso in planificador.procesos_ordenados:
        tf = tf_por_id[proceso.id]
        tr = tf - proceso.t_llegada
        te = tr - proceso.duracion
        filas.append({
            "id": proceso.id,
            "t_llegada": proceso.t_llegada,
            "duracion": proceso.duracion,
            "tf": tf,
            "tr": tr,
            "te": te,
        })

    cantidad = len(filas)
    resumen = {
        "cantidad": cantidad,
        "rafaga_total": sum(p.duracion for p in planificador.procesos) / cantidad,
        "tf_prom": sum(f["tf"] for f in filas) / cantidad,
        "tr_prom": sum(f["tr"] for f in filas) / cantidad,
        "te_prom": sum(f["te"] for f in filas) / cantidad,
        "tf_max": max(f["tf"] for f in filas),
        "te_max": max(f["te"] for f in filas),
    }

    return {
        "nombre": planificador.nombre,
        "descripcion": planificador.descripcion,
        "acento": planificador.acento,
        "expulsivo": planificador.expulsivo,
        "con_cs": con_cs,
        "ids": planificador.ids_en_orden,
        "bloques": bloques,
        "bloques_cs": franjas_cs,
        "tiempo_total": max((b.fin for b in bloques), default=0),
        "procesos": filas,
        "resumen": resumen,
    }


def _construir_variantes(planificadores: Sequence[PlanificadorBase]) -> tuple[list, list]:
    """Devuelve (vistas sin CS, vistas con CS) para cada política."""
    sin_cs = [_vista(p, False) for p in planificadores]
    con_cs = [_vista(p, True) for p in planificadores]
    return sin_cs, con_cs


#  HOJAS DE ESTILO Y SCRIPT DE LA PANTALLA

_ESTILO_BASE = """
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; padding: 0 20px 80px; }
.envoltorio { max-width: 1180px; margin: 0 auto; }
h1, h2, h3 { margin: 0; font-weight: 700; letter-spacing: -0.4px; }
p { margin: 0; }
.seccion {
    background: var(--carta);
    border: 1px solid var(--borde);
    border-radius: 16px;
    padding: 26px 28px 30px;
    margin: 22px 0;
}
.portada { text-align: center; padding: 46px 28px 34px; }
.portada h1 { font-size: 30px; }
.portada .subtitulo { color: var(--texto-suave); margin-top: 10px; font-size: 15px; }
.controles {
    position: sticky; top: 0; z-index: 50;
    display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
    background: var(--carta); border: 1px solid var(--borde);
    border-radius: 13px; padding: 12px 16px; margin: 22px 0;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
}
.boton {
    font: inherit; font-size: 14px; cursor: pointer;
    background: var(--fondo-alterno); color: var(--texto);
    border: 1px solid var(--borde); border-radius: 9px; padding: 8px 15px;
}
.boton:hover { border-color: var(--acento); }
.boton-primario { background: var(--acento); color: #12161f; border-color: var(--acento); font-weight: 600; }
.boton[aria-pressed="true"] { border-color: var(--destacado); color: var(--destacado); }
.control-velocidad {
    margin-left: auto; display: flex; align-items: center; gap: 8px;
    color: var(--texto-suave); font-size: 13px;
}
.control-velocidad select {
    font: inherit; background: var(--fondo-alterno); color: var(--texto);
    border: 1px solid var(--borde); border-radius: 8px; padding: 6px 10px;
}
.titulo-seccion {
    display: flex; align-items: baseline; gap: 12px;
    font-size: 22px; margin-bottom: 6px;
}
.numero {
    display: inline-flex; align-items: center; justify-content: center;
    width: 32px; height: 32px; border-radius: 9px; flex: 0 0 32px;
    font-size: 15px; color: #12161f; background: var(--acento-seccion);
}
.descripcion { color: var(--texto-suave); font-size: 14.5px; max-width: 78ch; margin-bottom: 20px; }
.rotulo { font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px;
          color: var(--texto-suave); margin: 22px 0 9px; }
.tabla { width: 100%; border-collapse: collapse; font-size: 14px; }
.tabla th {
    text-align: right; padding: 10px 12px; color: var(--texto-suave);
    font-size: 11.5px; text-transform: uppercase; letter-spacing: 0.9px;
    border-bottom: 1px solid var(--borde); white-space: nowrap;
}
.tabla th:first-child, .tabla td:first-child { text-align: left; }
.tabla td { padding: 9px 12px; border-bottom: 1px solid var(--borde); text-align: right; }
.tabla tbody tr:nth-child(even) { background: var(--fondo-alterno); }
.tabla tfoot td {
    font-weight: 700; text-align: right; color: var(--acento);
    border-bottom: none; border-top: 2px solid var(--acento); padding-top: 11px;
}
.tabla tfoot td:first-child { text-align: left; }
.tabla td.mejor { color: var(--exito); font-weight: 700; }
.contiene-gantt { overflow-x: auto; border-radius: 11px; background: var(--fondo-alterno); }
.colas { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 4px; }
.cola {
    background: var(--fondo-alterno); border: 1px solid var(--borde);
    border-radius: 11px; padding: 11px 13px; min-height: 74px;
}
.cola h4 {
    font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
    color: var(--texto-suave); margin: 0 0 9px;
}
.cola .chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
    display: inline-flex; align-items: center; gap: 6px;
    background: var(--carta); border: 1px solid var(--borde); border-radius: 20px;
    padding: 3px 11px 3px 8px; font-size: 12.5px;
    font-family: 'Cascadia Mono', Consolas, monospace;
}
.chip i { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
.vacio { color: var(--texto-suave); font-size: 12.5px; }
.cursor { stroke: var(--destacado); stroke-width: 1.6; }
.resumen-linea {
    display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; list-style: none; padding: 0;
}
.resumen-linea li {
    background: var(--fondo-alterno); border: 1px solid var(--borde);
    border-radius: 9px; padding: 8px 14px; font-size: 13.5px; color: var(--texto-suave);
}
.resumen-linea b { color: var(--texto); }
.aviso-expulsion {
    border-left: 3px solid var(--destacado); background: var(--fondo-alterno);
    padding: 10px 15px; border-radius: 0 9px 9px 0; font-size: 13.5px;
    color: var(--texto-suave); margin-bottom: 18px;
}
.aviso-expulsion b { color: var(--destacado); }
.pie { text-align: center; color: var(--texto-suave); font-size: 13px; margin-top: 34px; }
.pie code { background: var(--fondo-alterno); padding: 2px 7px; border-radius: 5px; }
.aviso-error {
    border-left: 3px solid var(--destacado); background: var(--fondo-alterno);
    padding: 16px 20px; border-radius: 0 9px 9px 0; margin: 26px 0; font-size: 14px;
}
"""

_SCRIPT_GANT = """
(function () {
    const DATOS = __DATOS__;
    const ANCHO = 1140;
    const ALTO = 26;
    const MARGEN = { arriba: 16, derecha: 18, abajo: 32, izquierda: 74 };
    const COLOR_CS = "#55607a";

    const estado = { variante: "sin_cs", t: 0, corriendo: false, timer: null };
    const REGISTRO = {};

    function escalaTiempo(datos) {
        const util = ANCHO - MARGEN.izquierda - MARGEN.derecha;
        const total = Math.max(datos.tiempo_total, 1);
        return (instante) => MARGEN.izquierda + (instante / total) * util;
    }

    function dibujarMarco(datos) {
        const contenedor = document.getElementById(datos.contenedor);
        if (!datos.bloques.length) {
            contenedor.innerHTML = '<p class="descripcion">Sin bloques de ejecucion.</p>';
            return;
        }

        const est = DATOS.estilos;
        const posicionX = escalaTiempo(datos);
        const filas = datos.procesos.length + (datos.con_cs ? 1 : 0);
        const alto = MARGEN.arriba + filas * ALTO + MARGEN.abajo;
        const partes = [];

        partes.push('<svg viewBox="0 0 ' + ANCHO + ' ' + alto + '" width="100%" ' +
                    'height="' + alto + '" role="img" aria-label="Diagrama de Gantt">');

        const paso = Math.max(1, Math.ceil(datos.tiempo_total / 16));
        for (let t = 0; t <= datos.tiempo_total; t += paso) {
            const x = posicionX(t);
            partes.push('<line x1="' + x + '" y1="' + MARGEN.arriba + '" x2="' + x +
                        '" y2="' + (alto - MARGEN.abajo) + '" stroke="' + est.borde +
                        '" stroke-width="1" stroke-dasharray="3 4"/>');
            partes.push('<text x="' + x + '" y="' + (alto - MARGEN.abajo + 17) +
                        '" fill="' + est.textoSuave + '" font-size="11" ' +
                        'text-anchor="middle" font-family="monospace">' + t + '</text>');
        }
        partes.push('<line x1="' + MARGEN.izquierda + '" y1="' + (alto - MARGEN.abajo) +
                    '" x2="' + (ANCHO - MARGEN.derecha) + '" y2="' + (alto - MARGEN.abajo) +
                    '" stroke="' + est.borde + '" stroke-width="1.5"/>');
        partes.push('<text x="' + (ANCHO - MARGEN.derecha) + '" y="' + (alto - 4) +
                    '" fill="' + est.textoSuave + '" font-size="11" text-anchor="end">tiempo (t)</text>');

        datos.procesos.forEach(function (id, fila) {
            const y = MARGEN.arriba + fila * ALTO + ALTO / 2;
            partes.push('<text x="' + (MARGEN.izquierda - 12) + '" y="' + (y + 4) +
                        '" fill="' + est.texto + '" font-size="12" text-anchor="end" ' +
                        'font-family="monospace">' + id + '</text>');
            partes.push('<line x1="' + MARGEN.izquierda + '" y1="' + y + '" x2="' +
                        (ANCHO - MARGEN.derecha) + '" y2="' + y + '" stroke="' + est.fondo +
                        '" stroke-width="' + (ALTO - 6) + '"/>');
        });

        if (datos.con_cs) {
            const fila = datos.procesos.length;
            const y = MARGEN.arriba + fila * ALTO + ALTO / 2;
            partes.push('<text x="' + (MARGEN.izquierda - 12) + '" y="' + (y + 4) +
                        '" fill="' + est.textoSuave + '" font-size="12" text-anchor="end" ' +
                        'font-family="monospace">CS</text>');
            partes.push('<line x1="' + MARGEN.izquierda + '" y1="' + y + '" x2="' +
                        (ANCHO - MARGEN.derecha) + '" y2="' + y + '" stroke="' + est.fondo +
                        '" stroke-width="' + (ALTO - 6) + '"/>');
        }

        datos.bloques.forEach(function (bloque) {
            const x = posicionX(bloque.inicio);
            const ancho = Math.max(2, posicionX(bloque.fin) - x);
            const y = MARGEN.arriba + datos.procesos.indexOf(bloque.id) * ALTO + 3;
            partes.push('<rect class="barra" data-id="' + bloque.id + '" data-inicio="' +
                        bloque.inicio + '" data-fin="' + bloque.fin + '" x="' + x +
                        '" y="' + y + '" width="' + ancho + '" height="' + (ALTO - 6) +
                        '" rx="3" fill="' + datos.colores[bloque.id] + '" stroke="' +
                        est.borde + '" stroke-width="1" style="opacity:0;pointer-events:none"/>');
        });

        if (datos.con_cs) {
            const fila = datos.procesos.length;
            const y = MARGEN.arriba + fila * ALTO + 3;
            datos.bloques_cs.forEach(function (bloque) {
                const x = posicionX(bloque.inicio);
                const ancho = Math.max(2, posicionX(bloque.fin) - x);
                partes.push('<rect class="barra-cs" data-inicio="' + bloque.inicio +
                            '" data-fin="' + bloque.fin + '" x="' + x + '" y="' + y +
                            '" width="' + ancho + '" height="' + (ALTO - 6) + '" rx="3" fill="' +
                            COLOR_CS + '" stroke="' + est.borde +
                            '" stroke-width="1" style="opacity:0;pointer-events:none"/>');
            });
        }

        partes.push('<line class="cursor" x1="0" y1="' + MARGEN.arriba + '" x2="0" y2="' +
                    (alto - MARGEN.abajo) + '" style="opacity:0"/>');
        partes.push('</svg>');
        contenedor.innerHTML = partes.join('');

        REGISTRO[datos.contenedor] = {
            posicionX: posicionX,
            cursor: contenedor.querySelector('line.cursor'),
            barras: Array.from(contenedor.querySelectorAll('rect.barra')),
            barrasCs: Array.from(contenedor.querySelectorAll('rect.barra-cs')),
        };
    }

    function chip(id, datos) {
        return '<span class="chip"><i style="background:' + datos.colores[id] + '"></i>' +
               id + '</span>';
    }

    function actualizarColas(datos) {
        const cont = document.getElementById(datos.colas);
        if (!cont) return;

        let cpu = null;
        datos.bloques.forEach(function (b) {
            if (b.inicio <= estado.t && estado.t < b.fin && cpu === null) cpu = b.id;
        });

        const terminados = datos.info
            .filter(function (p) { return p.tf <= estado.t; })
            .sort(function (a, b) { return a.tf - b.tf; })
            .map(function (p) { return p.id; });
        const setTerminados = new Set(terminados);

        const proximoInicio = {};
        datos.bloques.forEach(function (b) {
            if (b.inicio >= estado.t) {
                if (proximoInicio[b.id] === undefined || b.inicio < proximoInicio[b.id]) {
                    proximoInicio[b.id] = b.inicio;
                }
            }
        });
        const listos = datos.info
            .filter(function (p) {
                return p.llegada <= estado.t && !setTerminados.has(p.id) && p.id !== cpu;
            })
            .map(function (p) { return p.id; })
            .sort(function (a, b) {
                return (proximoInicio[a] ?? 1e9) - (proximoInicio[b] ?? 1e9);
            });

        const escribir = function (clave, ids) {
            const caja = cont.querySelector('[data-cola="' + clave + '"] .chips');
            caja.innerHTML = ids.length
                ? ids.map(function (id) { return chip(id, datos); }).join('')
                : '<span class="vacio">—</span>';
        };
        escribir('cpu', cpu ? [cpu] : []);
        escribir('listos', listos);
        escribir('terminados', terminados);
    }

    function actualizar() {
        DATOS[estado.variante].graficos.forEach(function (datos) {
            const reg = REGISTRO[datos.contenedor];
            if (!reg) return;
            const pintar = function (lista) {
                lista.forEach(function (el) {
                    const inicio = +el.getAttribute('data-inicio');
                    const fin = +el.getAttribute('data-fin');
                    if (estado.t < inicio) {
                        el.style.opacity = '0';
                        el.style.pointerEvents = 'none';
                        return;
                    }
                    el.style.opacity = '1';
                    el.style.pointerEvents = 'auto';
                    const x = reg.posicionX(inicio);
                    el.setAttribute('x', x);
                    el.setAttribute('width',
                        Math.max(0, reg.posicionX(Math.min(fin, estado.t)) - x));
                });
            };
            pintar(reg.barras);
            pintar(reg.barrasCs);

            const xc = reg.posicionX(estado.t);
            reg.cursor.setAttribute('x1', xc);
            reg.cursor.setAttribute('x2', xc);
            reg.cursor.style.opacity = estado.t > 0 ? '1' : '0';

            actualizarColas(datos);
        });
    }

    function maxTiempo() {
        return Math.max.apply(null, DATOS[estado.variante].graficos
            .map(function (c) { return c.tiempo_total; }).concat([1]));
    }

    function pasoActual() {
        return Math.max(1, Math.ceil(maxTiempo() / 200));
    }

    function intervaloMs() {
        const valores = { lenta: 140, normal: 65, rapida: 28 };
        const actual = document.getElementById('velocidad').value;
        return valores[actual] || 65;
    }

    function tick() {
        estado.t += pasoActual();
        if (estado.t >= maxTiempo()) {
            estado.t = maxTiempo();
            actualizar();
            pausar();
            return;
        }
        actualizar();
    }

    function reproducir() {
        if (estado.t >= maxTiempo()) reiniciar();
        estado.corriendo = true;
        document.getElementById('boton-play').textContent = 'Pausa';
        clearInterval(estado.timer);
        estado.timer = setInterval(tick, intervaloMs());
    }

    function pausar() {
        estado.corriendo = false;
        document.getElementById('boton-play').textContent = 'Reproducir';
        clearInterval(estado.timer);
        estado.timer = null;
    }

    function reiniciar() {
        pausar();
        estado.t = 0;
        actualizar();
    }

    function actualizarBotonCs() {
        const boton = document.getElementById('boton-cs');
        boton.textContent = 'Cambio de contexto: ' +
            (estado.variante === 'con_cs' ? 'ON' : 'OFF');
        boton.setAttribute('aria-pressed', estado.variante === 'con_cs' ? 'true' : 'false');
    }

    function cambiarVariante(clave) {
        estado.variante = clave;
        document.getElementById('vista-sin-cs').style.display =
            clave === 'sin_cs' ? '' : 'none';
        document.getElementById('vista-con-cs').style.display =
            clave === 'con_cs' ? '' : 'none';
        actualizarBotonCs();
        reiniciar();
    }

    const globo = document.createElement('div');
    globo.className = 'globo';
    document.body.appendChild(globo);

    document.addEventListener('mousemove', function (evento) {
        const barra = evento.target.closest('rect.barra, rect.barra-cs');
        if (!barra || barra.style.opacity === '0') { globo.style.opacity = '0'; return; }
        const inicio = barra.getAttribute('data-inicio');
        const fin = barra.getAttribute('data-fin');
        if (barra.classList.contains('barra-cs')) {
            globo.innerHTML = '<b>Cambio de contexto</b> &nbsp;t ' + inicio + ' → ' + fin +
                              ' &nbsp;(' + (fin - inicio) + ' u)';
        } else {
            globo.innerHTML = '<b>' + barra.getAttribute('data-id') + '</b> &nbsp;t ' +
                              inicio + ' → ' + fin + ' &nbsp;(' + (fin - inicio) + ' u)';
        }
        globo.style.opacity = '1';
        globo.style.left = Math.min(evento.clientX + 14, window.innerWidth - 260) + 'px';
        globo.style.top = (evento.clientY + 16) + 'px';
    });

    document.getElementById('boton-cs').addEventListener('click', function () {
        cambiarVariante(estado.variante === 'sin_cs' ? 'con_cs' : 'sin_cs');
    });
    document.getElementById('boton-play').addEventListener('click', function () {
        if (estado.corriendo) { pausar(); } else { reproducir(); }
    });
    document.getElementById('boton-reset').addEventListener('click', reiniciar);
    document.getElementById('velocidad').addEventListener('change', function () {
        if (estado.corriendo) {
            clearInterval(estado.timer);
            estado.timer = setInterval(tick, intervaloMs());
        }
    });

    DATOS.sin_cs.graficos.forEach(dibujarMarco);
    DATOS.con_cs.graficos.forEach(dibujarMarco);
    document.getElementById('vista-con-cs').style.display = 'none';
    estado.variante = 'sin_cs';
    actualizarBotonCs();
    reiniciar();
})();
"""


#  GENERACIÓN DEL REPORTE HTML

_PLANTILLA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Políticas de planificación de CPU</title>
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
}
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
__ESTILO_BASE__
</style>
</head>
<body>
<div class="envoltorio">
__CUERPO__
</div>
<script>
__SCRIPT__
</script>
</body>
</html>
"""


def _tabla_html(encabezados: Sequence[str], filas: Sequence[Sequence],
                pie: Sequence | None = None,
                celdas_destacadas: Sequence[bool] | None = None) -> str:
    """Arma una tabla HTML. `celdas_destacadas` marca con la clase 'mejor'."""
    partes = ['<table class="tabla"><thead><tr>']
    partes += [f"<th>{escape(titulo)}</th>" for titulo in encabezados]
    partes.append("</tr></thead><tbody>")

    for indice, fila in enumerate(filas):
        partes.append("<tr>")
        for posicion, celda in enumerate(fila):
            clase = ""
            if celdas_destacadas and indice in celdas_destacadas and posicion == 1:
                clase = ' class="mejor"'
            partes.append(f"<td{clase}>{escape(str(celda))}</td>")
        partes.append("</tr>")

    partes.append("</tbody>")
    if pie:
        partes.append("<tfoot><tr>")
        partes += [f"<td>{escape(str(celda))}</td>" for celda in pie]
        partes.append("</tr></tfoot>")
    partes.append("</table>")
    return "".join(partes)


def _seccion_carga(procesos: Sequence[Proceso]) -> str:
    """La primera sección: la tabla con los N procesos que se van a simular."""
    filas = [[p.id, p.t_llegada, p.duracion] for p in procesos]
    return f"""
<section class="seccion">
  <h2 class="titulo-seccion"><span class="numero">N</span>Carga de trabajo</h2>
  {_tabla_html(["Proceso", "T. Llegada", "Duración"], filas)}
</section>
"""


def _controles_html() -> str:
    """Barra con el interruptor de contexto y los controles de reproducción."""
    return """
<div class="controles">
  <button id="boton-cs" class="boton" type="button" aria-pressed="false">Cambio de contexto: OFF</button>
  <button id="boton-play" class="boton boton-primario" type="button">Reproducir</button>
  <button id="boton-reset" class="boton" type="button">Reiniciar</button>
  <label class="control-velocidad">Velocidad
    <select id="velocidad">
      <option value="lenta">Lenta</option>
      <option value="normal" selected>Normal</option>
      <option value="rapida">Rápida</option>
    </select>
  </label>
</div>
"""


def _seccion_politica(vista: dict, numero: int, indice: int, clave: str) -> str:
    """Una sección por política: su Gantt, sus colas y su tabla de métricas."""
    resumen = vista["resumen"]
    filas = [
        [p["id"], p["t_llegada"], p["duracion"], p["tf"], p["tr"], p["te"]]
        for p in vista["procesos"]
    ]
    pie = [
        "PROMEDIO", "",
        round(resumen["rafaga_total"], 2),
        round(resumen["tf_prom"], 2),
        round(resumen["tr_prom"], 2),
        round(resumen["te_prom"], 2),
    ]

    return f"""
<section class="seccion" style="--acento-seccion: {vista['acento']}">
  <h2 class="titulo-seccion">
    <span class="numero">{numero}</span>{escape(vista['nombre'])}
  </h2>
  <p class="descripcion">{escape(vista['descripcion'])}</p>
  <p class="rotulo">Diagrama de Gantt</p>
  <div class="contiene-gantt"><div id="gantt-{clave}-{indice}"></div></div>
  <p class="rotulo">Estado de las colas</p>
  <div class="colas" id="colas-{clave}-{indice}">
    <div class="cola" data-cola="cpu"><h4>CPU</h4><div class="chips"></div></div>
    <div class="cola" data-cola="listos"><h4>Listos</h4><div class="chips"></div></div>
    <div class="cola" data-cola="terminados"><h4>Terminados</h4><div class="chips"></div></div>
  </div>
  <p class="rotulo">Métricas por proceso</p>
  {_tabla_html(["Proceso", "T. Llegada", "Ráfaga", "T. Fin (TF)", "Retorno (TR)",
                 "Espera (TE)"], filas, pie=pie)}
</section>
"""


def _seccion_comparativa(vistas: Sequence[dict], con_cs: bool) -> str:
    """Tabla final que enfrenta a las cuatro políticas de una variante."""
    mejor_te = min(v["resumen"]["te_prom"] for v in vistas)
    indice_mejor = next(
        i for i, v in enumerate(vistas) if v["resumen"]["te_prom"] == mejor_te
    )

    encabezados = ["Política", "Espera prom.", "Retorno prom.", "TF prom.",
                   "Peor espera", "Franjas"]
    if con_cs:
        encabezados.append("Cambios")
    encabezados.append("Duración total")

    filas, destacadas = [], []
    for indice, vista in enumerate(vistas):
        resumen = vista["resumen"]
        fila = [
            vista["nombre"],
            f"{resumen['te_prom']:.2f}",
            f"{resumen['tr_prom']:.2f}",
            f"{resumen['tf_prom']:.2f}",
            resumen["te_max"],
            len(vista["bloques"]),
        ]
        if con_cs:
            fila.append(len(vista["bloques_cs"]))
        fila.append(vista["tiempo_total"])
        filas.append(fila)
        if indice == indice_mejor:
            destacadas.append(indice)

    return f"""
<section class="seccion">
  <h2 class="titulo-seccion"><span class="numero">Σ</span>Comparativa de las cuatro políticas</h2>
  {_tabla_html(encabezados, filas, celdas_destacadas=destacadas)}
</section>
"""


def _datos_graficos(vistas_sin_cs: Sequence[dict], vistas_con_cs: Sequence[dict]) -> dict:
    """Arma el diccionario que el JavaScript usa para dibujar y animar."""

    def juego(vistas: Sequence[dict], clave: str, con_cs: bool) -> dict:
        graficos = []
        for indice, vista in enumerate(vistas):
            ids = vista["ids"]
            colores = {id_proceso: color_de_proceso(posicion)
                       for posicion, id_proceso in enumerate(ids)}
            graficos.append({
                "contenedor": f"gantt-{clave}-{indice}",
                "colas": f"colas-{clave}-{indice}",
                "tiempo_total": vista["tiempo_total"],
                "procesos": ids,
                "colores": colores,
                "con_cs": con_cs,
                "bloques": [
                    {"id": b.id_proceso, "inicio": b.inicio, "fin": b.fin}
                    for b in vista["bloques"]
                ],
                "bloques_cs": [
                    {"inicio": b.inicio, "fin": b.fin} for b in vista["bloques_cs"]
                ],
                "info": [
                    {"id": f["id"], "llegada": f["t_llegada"], "tf": f["tf"]}
                    for f in vista["procesos"]
                ],
            })
        return {"graficos": graficos}

    return {
        "sin_cs": juego(vistas_sin_cs, "sin-cs", False),
        "con_cs": juego(vistas_con_cs, "con-cs", True),
        "estilos": {
            "borde": TEMA["borde"],
            "fondo": TEMA["carta"],
            "texto": TEMA["texto"],
            "textoSuave": TEMA["texto_suave"],
        },
    }


def _estilos_como_css() -> str:
    """Vuelca TEMA como variables CSS, para que la vista sea editable desde Python."""
    return "\n".join(f"    --{clave.replace('_', '-')}: {valor};" for clave, valor in TEMA.items())


def _cuerpo_html(vistas_sin_cs: Sequence[dict], vistas_con_cs: Sequence[dict],
                 procesos: Sequence[Proceso], origen: str, quantum: int) -> str:
    """Construye todo el contenido visible de la página."""
    portada = f"""
<header class="seccion portada">
  <h1>Simulador de políticas de planificación de CPU</h1>
  <p class="subtitulo">FCFS &nbsp;·&nbsp; SJF &nbsp;·&nbsp; SRTF &nbsp;·&nbsp; Round Robin</p>
</header>
"""

    def vista_completa(vistas: Sequence[dict], clave: str, con_cs: bool) -> str:
        secciones = []
        for numero, vista in enumerate(vistas, start=1):
            secciones.append(_seccion_politica(vista, numero, numero - 1, clave))
        secciones.append(_seccion_comparativa(vistas, con_cs))
        return "".join(secciones)

    return (
        portada
        + _controles_html()
        + _seccion_carga(procesos)
        + f'<div id="vista-sin-cs">{vista_completa(vistas_sin_cs, "sin-cs", False)}</div>'
        + f'<div id="vista-con-cs">{vista_completa(vistas_con_cs, "con-cs", True)}</div>'
    )


def generar_reporte_html(
    procesos: Sequence[Proceso],
    planificadores: Sequence[PlanificadorBase],
    ruta_salida: str | Path = "reporte.html",
    origen: str = "",
    quantum: int = 2,
) -> Path:
    """
    Escribe el reporte completo en un solo archivo HTML y devuelve su ruta.
    Las políticas se simulan aquí si aún no se habían corrido.
    No necesita internet ni librerías externas: el archivo se abre con doble clic.
    """
    ejecutar_todas(planificadores)
    vistas_sin_cs, vistas_con_cs = _construir_variantes(planificadores)
    destino = Path(ruta_salida)

    cuerpo = _cuerpo_html(vistas_sin_cs, vistas_con_cs, procesos, origen, quantum)
    datos = json.dumps(_datos_graficos(vistas_sin_cs, vistas_con_cs), ensure_ascii=True)
    script = _SCRIPT_GANT.replace("__DATOS__", datos)

    html = (
        _PLANTILLA
        .replace("__VARIABLES_TEMA__", _estilos_como_css())
        .replace("__ESTILO_BASE__", _ESTILO_BASE)
        .replace("__CUERPO__", cuerpo)
        .replace("__SCRIPT__", script)
    )

    destino.write_text(html, encoding="utf-8")
    return destino
