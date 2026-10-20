from __future__ import annotations

import json
import webbrowser
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Sequence

from simulador_so import TEMA, _estilos_como_css


#  ESTADOS DE UN HILO

LISTO = "LISTO"
EJECUTANDO = "EJECUTANDO"
BLOQUEADO = "BLOQUEADO"
TERMINADO = "TERMINADO"

# Color con el que se pinta cada estado en la línea de tiempo.
COLOR_ESTADO = {
    LISTO: "#3ddc97",        # verde   : listo para ejecutarse
    EJECUTANDO: "#5b9dff",   # azul    : el hilo avanza en este paso
    BLOQUEADO: "#ffb454",    # naranja : esperando un mutex o un semáforo
    TERMINADO: "#55607a",    # gris    : el hilo ya concluyó
}   




class MutexSim:
    """Candado de exclusión mutua con cola FIFO de hilos esperando."""

    def __init__(self, nombre: str):
        self.nombre = nombre
        self.libre = True   #nadie lo toma
        self.cola: List["HiloSimulado"] = [] #hilos bloqueado 

    def descripcion(self) -> str:
        return "libre" if self.libre else "tomado"


class SemaforoSim:
    """
    'esperar()' decrementa  y bloquea al hilo.
    'liberar()' incrementa y despierta.
    """

    def __init__(self, nombre: str, valor: int = 0):
        self.nombre = nombre
        self.valor = valor
        self.cola: List["HiloSimulado"] = []

    def disponibles(self) -> int:
        return max(self.valor, 0)

    def esperando(self) -> int:
        return max(-self.valor, 0)

    def descripcion(self) -> str:
        return f"{self.disponibles()} disp / {self.esperando()} esperan"


#  HILOS Y PLANIFICADOR PASO A PASO

class HiloSimulado: #inf hil

    def __init__(self, nombre: str, generador: Iterator):
        self.nombre = nombre
        self.generador = generador    # produce las operaciones del hilo
        self.estado = LISTO
        self.terminado = False


class SimuladorPasos:
    def __init__(self, instantanea: Callable[[], dict]):
        self.hilos: List[HiloSimulado] = []
        self.pasos: List[dict] = []
        self.instantanea = instantanea    #recurso compartido
        self.numero_paso = 0
        self.deadlock = False

    def agregar_hilo(self, nombre: str, generador: Iterator) -> None:
        self.hilos.append(HiloSimulado(nombre, generador))

    def _estados_actuales(self) -> Dict[str, str]:
        return {hilo.nombre: hilo.estado for hilo in self.hilos}

    def _registrar(self, hilo: str, operacion: str, detalle: str) -> None:
        self.numero_paso += 1
        self.pasos.append({
            "n": self.numero_paso,
            "hilo": hilo,
            "operacion": operacion,
            "detalle": detalle,
            "estados": self._estados_actuales(),
            "recurso": self.instantanea(),
        })

    def ejecutar(self, max_pasos: int = 5000) -> None:
        """simulación hasta que todos los hilos terminen o se bloqueen."""
        cola_listos = list(self.hilos)

        while cola_listos and self.numero_paso < max_pasos:
            hilo = cola_listos.pop(0)

            # ¿El hilo ya terminó todo su trabajo?
            try:
                operacion = next(hilo.generador)
            except StopIteration:
                hilo.estado = TERMINADO
                hilo.terminado = True
                self._registrar(hilo.nombre, "fin", "el hilo termina su ejecución")
                continue

            tipo = operacion[0]
            hilo.estado = EJECUTANDO

            if tipo == "trabajo":
                self._registrar(hilo.nombre, "trabaja", operacion[1])
                hilo.estado = LISTO
                cola_listos.append(hilo)

            elif tipo == "esperar":
                semaforo: SemaforoSim = operacion[1]
                semaforo.valor -= 1
                if semaforo.valor < 0:
                    # No había recursos: el hilo se bloquea en la cola del semáforo
                    hilo.estado = BLOQUEADO
                    semaforo.cola.append(hilo)
                    self._registrar(hilo.nombre, "wait",
                                    f"esperar({semaforo.nombre}) → se bloquea")
                else:
                    self._registrar(hilo.nombre, "wait",
                                    f"esperar({semaforo.nombre}) → pasa")
                    hilo.estado = LISTO
                    cola_listos.append(hilo)

            elif tipo == "liberar":
                semaforo = operacion[1]
                semaforo.valor += 1
                detalle = f"signal({semaforo.nombre})"
                if semaforo.valor <= 0 and semaforo.cola:
                    despertado = semaforo.cola.pop(0)
                    despertado.estado = LISTO
                    cola_listos.append(despertado)
                    detalle += f" → despierta a {despertado.nombre}"
                self._registrar(hilo.nombre, "signal", detalle)
                hilo.estado = LISTO
                cola_listos.append(hilo)

            elif tipo == "adquirir":
                mutex: MutexSim = operacion[1]
                if mutex.libre:
                    mutex.libre = False
                    self._registrar(hilo.nombre, "lock",
                                    f"lock({mutex.nombre}) → adquiere")
                    hilo.estado = LISTO
                    cola_listos.append(hilo)
                else:
                    hilo.estado = BLOQUEADO
                    mutex.cola.append(hilo)
                    self._registrar(hilo.nombre, "lock",
                                    f"lock({mutex.nombre}) → se bloquea")

            elif tipo == "liberar_mutex":
                mutex = operacion[1]
                detalle = f"unlock({mutex.nombre})"
                if mutex.cola:
                    # Se lo pasa directamente al siguiente hilo de la cola
                    despertado = mutex.cola.pop(0)
                    despertado.estado = LISTO
                    cola_listos.append(despertado)
                    detalle += f" → despierta a {despertado.nombre}"
                else:
                    mutex.libre = True
                self._registrar(hilo.nombre, "unlock", detalle)
                hilo.estado = LISTO
                cola_listos.append(hilo)

        # Si la cola de listos se vació pero quedan hilos sin terminar: interbloqueo
        if cola_listos == [] and any(not h.terminado for h in self.hilos):
            self.deadlock = True


#  ESTRUCTURA DE UN PROBLEMA SIMULADO


@dataclass
class ProblemaConcurrencia:
    id: str
    titulo: str
    descripcion: str
    mecanismo: str
    hilos: List[str]
    pasos: List[dict]
    deadlock: bool = False

    @property
    def total_pasos(self) -> int:
        return len(self.pasos)


#  PROBLEMA 1 - PRODUCTOR / CONSUMIDOR


def simular_productor_consumidor() -> ProblemaConcurrencia:
    CAPACIDAD = 3 # ranuras  buffer c
    ITEMS_POR_PRODUCTOR = 4 #datos x productor
    N_PRODUCTORES = 2
    N_CONSUMIDORES = 2
    CONSUMOS_POR_HILO = ITEMS_POR_PRODUCTOR * N_PRODUCTORES // N_CONSUMIDORES

    estado = {
        "buffer": [None] * CAPACIDAD,
        "indice_escritura": 0,
        "indice_lectura": 0,
        "cantidad": 0,
        "insertados": 0,
        "extraidos": 0,
    }

    mutex_buffer = MutexSim("mutex_buffer")
    vacios = SemaforoSim("vacios", CAPACIDAD) #r libres
    llenos = SemaforoSim("llenos", 0) #r datos

    def instantanea() -> dict:
        contenido = ", ".join("·" if x is None else str(x) for x in estado["buffer"])
        return {
            "Buffer": f"[ {contenido} ]",
            "Ranuras ocupadas": f"{estado['cantidad']} de {CAPACIDAD}",
            "Semáforo vacios": vacios.descripcion(),
            "Semáforo llenos": llenos.descripcion(),
            "mutex_buffer": mutex_buffer.descripcion(),
            "Datos insertados": estado["insertados"],
            "Datos extraídos": estado["extraidos"],
        }

    def productor(nombre: str) -> Iterator:
        for i in range(ITEMS_POR_PRODUCTOR):
            dato = f"{nombre[-1]}{i}"
            yield ("trabajo", f"{nombre} produce el dato {dato}")
            # Regla de oro: primero esperar una ranura libre, después el mutex
            yield ("esperar", vacios)
            yield ("adquirir", mutex_buffer)
            posicion = estado["indice_escritura"]
            estado["buffer"][posicion] = dato
            estado["indice_escritura"] = (posicion + 1) % CAPACIDAD
            estado["cantidad"] += 1
            estado["insertados"] += 1
            yield ("trabajo", f"{nombre} inserta {dato} en la ranura {posicion}")
            yield ("liberar_mutex", mutex_buffer)
            yield ("liberar", llenos)

    def consumidor(nombre: str) -> Iterator:
        for _ in range(CONSUMOS_POR_HILO):
            yield ("trabajo", f"{nombre} está listo para consumir")
            yield ("esperar", llenos)
            yield ("adquirir", mutex_buffer)
            posicion = estado["indice_lectura"]
            dato = estado["buffer"][posicion]
            estado["buffer"][posicion] = None
            estado["indice_lectura"] = (posicion + 1) % CAPACIDAD
            estado["cantidad"] -= 1
            estado["extraidos"] += 1
            yield ("trabajo", f"{nombre} extrae {dato} de la ranura {posicion}")
            yield ("liberar_mutex", mutex_buffer)
            yield ("liberar", vacios)

    simulador = SimuladorPasos(instantanea)
    simulador.agregar_hilo("Productor 1", productor("Productor 1"))
    simulador.agregar_hilo("Productor 2", productor("Productor 2"))
    simulador.agregar_hilo("Consumidor 1", consumidor("Consumidor 1"))
    simulador.agregar_hilo("Consumidor 2", consumidor("Consumidor 2"))
    simulador.ejecutar()

    return ProblemaConcurrencia(
        id="productor-consumidor",
        titulo="1. Productor - Consumidor (buffer limitado)",
        descripcion=(
            "Dos productores generan datos y los insertan en un buffer circular "
            "de tamaño fijo; dos consumidores los extraen. La sección crítica es "
            "el buffer y sus índices, protegidos con un mutex y dos semáforos "
            "contadores que evitan el desbordamiento y el subdesbordamiento."
        ),
        mecanismo=(
            "1 Mutex (mutex_buffer) + 2 Semáforos contadores: 'vacios' = N "
            "(ranuras libres) y 'llenos' = 0 (ranuras con datos). El productor "
            "hace wait(vacios) antes de insertar y signal(llenos) al terminar; el "
            "consumidor hace wait(llenos) antes de extraer y signal(vacios) al "
            "terminar. Siempre se espera el semáforo ANTES de tomar el mutex."
        ),
        hilos=[h.nombre for h in simulador.hilos],
        pasos=simulador.pasos,
        deadlock=simulador.deadlock,
    )


#  PROBLEMA 2 - LECTORES / ESCRITORES


def simular_lectores_escritores() -> ProblemaConcurrencia:
    estado = {"valor_bd": 0, "num_lectores": 0, "lecturas": 0, "escrituras": 0}

    mutex_contador = MutexSim("mutex_contador")   # protege num_lectores
    acceso_bd = MutexSim("acceso_bd")             # protege la base de datos

    def instantanea() -> dict:
        return {
            "Base de datos (valor)": estado["valor_bd"],
            "num_lectores": estado["num_lectores"],
            "acceso_bd": acceso_bd.descripcion(),
            "mutex_contador": mutex_contador.descripcion(),
            "Lecturas realizadas": estado["lecturas"],
            "Escrituras realizadas": estado["escrituras"],
        }

    def lector(nombre: str, espera_inicial: int) -> Iterator:
        for _ in range(espera_inicial):
            yield ("trabajo", f"{nombre} piensa antes de leer")
        for _ in range(2):
            yield ("trabajo", f"{nombre} quiere leer")
            # Patrón Lightswitch: solo el primer lector bloquea a los escritores
            yield ("adquirir", mutex_contador)
            estado["num_lectores"] += 1
            if estado["num_lectores"] == 1:
                yield ("adquirir", acceso_bd)
            yield ("liberar_mutex", mutex_contador)
            estado["lecturas"] += 1
            yield ("trabajo",
                   f"{nombre} lee la base de datos (valor {estado['valor_bd']})")
            # El último lector en salir libera la base de datos
            yield ("adquirir", mutex_contador)
            estado["num_lectores"] -= 1
            if estado["num_lectores"] == 0:
                yield ("liberar_mutex", acceso_bd)
            yield ("liberar_mutex", mutex_contador)

    def escritor(nombre: str, espera_inicial: int) -> Iterator:
        for _ in range(espera_inicial):
            yield ("trabajo", f"{nombre} piensa antes de escribir")
        yield ("trabajo", f"{nombre} quiere escribir")
        yield ("adquirir", acceso_bd)
        estado["valor_bd"] += 1
        estado["escrituras"] += 1
        yield ("trabajo",
               f"{nombre} escribe la base de datos (valor {estado['valor_bd']})")
        yield ("liberar_mutex", acceso_bd)

    simulador = SimuladorPasos(instantanea)
    simulador.agregar_hilo("Lector 1", lector("Lector 1", 2))
    simulador.agregar_hilo("Lector 2", lector("Lector 2", 2))
    simulador.agregar_hilo("Lector 3", lector("Lector 3", 3))
    simulador.agregar_hilo("Escritor 1", escritor("Escritor 1", 5))
    simulador.agregar_hilo("Escritor 2", escritor("Escritor 2", 8))
    simulador.ejecutar()

    return ProblemaConcurrencia(
        id="lectores-escritores",
        titulo="2. Lectores - Escritores",
        descripcion=(
            "Varios lectores pueden consultar la base de datos al mismo tiempo, "
            "pero un escritor necesita acceso exclusivo. La sección crítica es la "
            "base de datos y la variable compartida num_lectores que cuenta "
            "cuántos lectores hay activos en cada instante."
        ),
        mecanismo=(
            "Patrón Lightswitch con 2 Mutex: 'mutex_contador' protege el "
            "incremento y decremento de num_lectores, y 'acceso_bd' protege la "
            "base de datos. El primer lector (num_lectores == 1) toma acceso_bd "
            "para bloquear a los escritores; el último lector en salir "
            "(num_lectores == 0) lo libera."
        ),
        hilos=[h.nombre for h in simulador.hilos],
        pasos=simulador.pasos,
        deadlock=simulador.deadlock,
    )


#  PROBLEMA 3 - FILÓSOFOS COMENSALES


def simular_filosofos() -> ProblemaConcurrencia:
    N = 5
    VECES_QUE_COME = 2

    estado = {"comidas": [0] * N, "comiendo": [False] * N}

    tenedores = [MutexSim(f"tenedor {i}") for i in range(N)]
    comensales = SemaforoSim("comensales", N - 1)   # mayordomo: máximo N-1

    def instantanea() -> dict:
        comiendo = [f"Filósofo {i}" for i in range(N) if estado["comiendo"][i]]
        datos = {
            "Semáforo comensales": comensales.descripcion(),
            "Comiendo ahora": ", ".join(comiendo) if comiendo else "nadie",
            "Comidas por filósofo": ", ".join(str(c) for c in estado["comidas"]),
        }
        for i in range(N):
            datos[f"Tenedor {i}"] = tenedores[i].descripcion()
        return datos

    def filosofo(i: int) -> Iterator:
        izquierdo = i
        derecho = (i + 1) % N
        for _ in range(VECES_QUE_COME):
            yield ("trabajo", f"Filósofo {i} piensa")
            # El mayordomo limita a N-1 filósofos compitiendo por N tenedores
            yield ("esperar", comensales)
            # Ruptura de simetría: pares toman izquierda primero, impares derecha
            if i % 2 == 0:
                primero, segundo = izquierdo, derecho
            else:
                primero, segundo = derecho, izquierdo
            yield ("adquirir", tenedores[primero])
            yield ("adquirir", tenedores[segundo])
            estado["comiendo"][i] = True
            yield ("trabajo",
                   f"Filósofo {i} come usando los tenedores {primero} y {segundo}")
            estado["comiendo"][i] = False
            estado["comidas"][i] += 1
            yield ("liberar_mutex", tenedores[primero])
            yield ("liberar_mutex", tenedores[segundo])
            yield ("liberar", comensales)

    simulador = SimuladorPasos(instantanea)
    for i in range(N):
        simulador.agregar_hilo(f"Filósofo {i}", filosofo(i))
    simulador.ejecutar()

    return ProblemaConcurrencia(
        id="filosofos",
        titulo="3. Filósofos Comensales",
        descripcion=(
            "Cinco filósofos alternan entre pensar y comer. Para comer necesitan "
            "los dos tenedores que los rodean (el de su izquierda y el de su "
            "derecha), que son recursos exclusivos compartidos con sus vecinos."
        ),
        mecanismo=(
            "5 Mutex (un tenedor cada uno) + ruptura de simetría + semáforo "
            "mayordomo 'comensales' = N-1 = 4. Los filósofos pares toman primero "
            "el tenedor izquierdo y los impares el derecho, rompiendo la espera "
            "circular; además, el mayordomo garantiza que nunca compitan los 5 a "
            "la vez por los 5 tenedores, evitando así el interbloqueo."
        ),
        hilos=[h.nombre for h in simulador.hilos],
        pasos=simulador.pasos,
        deadlock=simulador.deadlock,
    )


#  PROBLEMA 4 - BARBERO DORMILÓN


def simular_barbero() -> ProblemaConcurrencia:
    SILLAS = 4          # sillas de espera
    N_CLIENTES = 4

    estado = {"clientes_esperando": 0, "cortes": 0, "atendidos": 0}

    mutex_sillas = MutexSim("mutex_sillas")
    clientes = SemaforoSim("clientes", 0)            # cuántos clientes esperan
    barbero_listo = SemaforoSim("barbero_listo", 0)  # avisa al cliente su turno

    def instantanea() -> dict:
        return {
            "Clientes esperando": f"{estado['clientes_esperando']} de {SILLAS}",
            "Sillas libres": SILLAS - estado["clientes_esperando"],
            "Semáforo clientes": clientes.descripcion(),
            "Semáforo barbero_listo": barbero_listo.descripcion(),
            "mutex_sillas": mutex_sillas.descripcion(),
            "Cortes realizados": estado["cortes"],
            "Clientes atendidos": estado["atendidos"],
        }

    def barbero() -> Iterator:
        for _ in range(N_CLIENTES):
            # Si no hay clientes, el barbero se duerme aquí
            yield ("esperar", clientes)
            estado["cortes"] += 1
            yield ("trabajo", f"El barbero corta el cabello (corte {estado['cortes']})")
            yield ("liberar", barbero_listo)   # avisa al cliente que fue atendido

    def cliente(nombre: str, espera_inicial: int) -> Iterator:
        for _ in range(espera_inicial):
            yield ("trabajo", f"{nombre} va en camino a la barbería")
        yield ("adquirir", mutex_sillas)
        if estado["clientes_esperando"] < SILLAS:
            estado["clientes_esperando"] += 1
            yield ("trabajo", f"{nombre} se sienta en una silla de espera")
            yield ("liberar_mutex", mutex_sillas)
            yield ("liberar", clientes)          # despierta o avisa al barbero
            yield ("esperar", barbero_listo)     # espera su turno
            yield ("adquirir", mutex_sillas)
            estado["clientes_esperando"] -= 1
            estado["atendidos"] += 1
            yield ("liberar_mutex", mutex_sillas)
            yield ("trabajo", f"{nombre} se va ya atendido")
        else:
            yield ("trabajo", f"{nombre} no encuentra silla y se retira")
            yield ("liberar_mutex", mutex_sillas)

    simulador = SimuladorPasos(instantanea)
    simulador.agregar_hilo("Barbero", barbero())
    simulador.agregar_hilo("Cliente 1", cliente("Cliente 1", 1))
    simulador.agregar_hilo("Cliente 2", cliente("Cliente 2", 2))
    simulador.agregar_hilo("Cliente 3", cliente("Cliente 3", 6))
    simulador.agregar_hilo("Cliente 4", cliente("Cliente 4", 9))
    simulador.ejecutar()

    return ProblemaConcurrencia(
        id="barbero",
        titulo="4. Barbero Dormilón",
        descripcion=(
            "Una barbería con 1 barbero, 1 silla de trabajo y N sillas de espera. "
            "Si no hay clientes, el barbero se duerme; cuando llega uno lo "
            "despierta. La sección crítica es la variable clientes_esperando y el "
            "estado coordinado de la barbería."
        ),
        mecanismo=(
            "Patrón de cita o 'rendezvous' con 3 primitivas: 1 Mutex "
            "(mutex_sillas) que protege clientes_esperando, 1 semáforo contador "
            "'clientes' = 0 donde el barbero hace wait (si es 0, duerme) y el "
            "cliente que logra sentarse hace signal, y 1 semáforo binario "
            "'barbero_listo' = 0 donde el cliente hace wait para esperar su turno "
            "y el barbero hace signal al terminar el corte."
        ),
        hilos=[h.nombre for h in simulador.hilos],
        pasos=simulador.pasos,
        deadlock=simulador.deadlock,
    )


#  PROBLEMA 5 - LOS FUMADORES


def simular_fumadores() -> ProblemaConcurrencia:
    # El agente coloca los pares en ciclo, de modo que cada fumador fume 2 veces.
    RONDAS = 6
    pares = [
        ("tabaco", "papel"),      # -> fuma el que tiene cerillos
        ("tabaco", "cerillos"),   # -> fuma el que tiene papel
        ("papel", "cerillos"),    # -> fuma el que tiene tabaco
        ("tabaco", "papel"),
        ("tabaco", "cerillos"),
        ("papel", "cerillos"),
    ]
    INGREDIENTES = ("tabaco", "papel", "cerillos")

    estado = {f"hay_{ing}": False for ing in INGREDIENTES}
    estado["mesa"] = "vacía"
    estado["fumadas"] = 0

    # Semáforos del agente (uno por ingrediente colocado) y el de la mesa.
    sem_agente = {ing: SemaforoSim(ing, 0) for ing in INGREDIENTES}
    agente_mesa = SemaforoSim("agente_mesa", 1)

    # Semáforos privados de cada fumador (lo despierta el pusher correspondiente).
    fumador_con_tabaco = SemaforoSim("fumador_con_tabaco", 0)
    fumador_con_papel = SemaforoSim("fumador_con_papel", 0)
    fumador_con_cerillos = SemaforoSim("fumador_con_cerillos", 0)
    sem_fumador = {
        "tabaco": fumador_con_tabaco,
        "papel": fumador_con_papel,
        "cerillos": fumador_con_cerillos,
    }

    mutex_mesa = MutexSim("mutex_mesa")   # protege las variables booleanas de la mesa

    def instantanea() -> dict:
        en_mesa = [ing for ing in INGREDIENTES if estado[f"hay_{ing}"]]
        return {
            "Ingredientes en la mesa": ", ".join(en_mesa) if en_mesa else "ninguno",
            "Última combinación puesta": estado["mesa"],
            "mutex_mesa": mutex_mesa.descripcion(),
            "agente_mesa (sem)": agente_mesa.descripcion(),
            "Cigarrillos fumados": estado["fumadas"],
        }

    def agente() -> Iterator:
        for ronda in range(RONDAS):
            par = pares[ronda]
            yield ("esperar", agente_mesa)   # espera a que la mesa quede libre
            estado["mesa"] = " + ".join(par)
            yield ("trabajo", f"El agente pone {estado['mesa']} en la mesa")
            for ing in par:
                yield ("liberar", sem_agente[ing])   # despierta al pusher del ingrediente

    def pusher_tabaco() -> Iterator:
        # Despierta cuando el agente pone tabaco. Revisa si ya había otro ingrediente.
        for _ in range(4):
            yield ("esperar", sem_agente["tabaco"])
            yield ("adquirir", mutex_mesa)
            if estado["hay_papel"]:
                estado["hay_papel"] = False
                yield ("trabajo", "Pusher de tabaco ve tabaco + papel")
                yield ("liberar", fumador_con_cerillos)
            elif estado["hay_cerillos"]:
                estado["hay_cerillos"] = False
                yield ("trabajo", "Pusher de tabaco ve tabaco + cerillos")
                yield ("liberar", fumador_con_papel)
            else:
                estado["hay_tabaco"] = True
                yield ("trabajo", "Pusher de tabaco deja el tabaco marcado en la mesa")
            yield ("liberar_mutex", mutex_mesa)

    def pusher_papel() -> Iterator:
        for _ in range(4):
            yield ("esperar", sem_agente["papel"])
            yield ("adquirir", mutex_mesa)
            if estado["hay_tabaco"]:
                estado["hay_tabaco"] = False
                yield ("trabajo", "Pusher de papel ve papel + tabaco")
                yield ("liberar", fumador_con_cerillos)
            elif estado["hay_cerillos"]:
                estado["hay_cerillos"] = False
                yield ("trabajo", "Pusher de papel ve papel + cerillos")
                yield ("liberar", fumador_con_tabaco)
            else:
                estado["hay_papel"] = True
                yield ("trabajo", "Pusher de papel deja el papel marcado en la mesa")
            yield ("liberar_mutex", mutex_mesa)

    def pusher_cerillos() -> Iterator:
        for _ in range(4):
            yield ("esperar", sem_agente["cerillos"])
            yield ("adquirir", mutex_mesa)
            if estado["hay_tabaco"]:
                estado["hay_tabaco"] = False
                yield ("trabajo", "Pusher de cerillos ve cerillos + tabaco")
                yield ("liberar", fumador_con_papel)
            elif estado["hay_papel"]:
                estado["hay_papel"] = False
                yield ("trabajo", "Pusher de cerillos ve cerillos + papel")
                yield ("liberar", fumador_con_tabaco)
            else:
                estado["hay_cerillos"] = True
                yield ("trabajo", "Pusher de cerillos deja los cerillos marcados")
            yield ("liberar_mutex", mutex_mesa)

    def fumador(nombre: str, ingrediente_propio: str) -> Iterator:
        for _ in range(2):
            yield ("esperar", sem_fumador[ingrediente_propio])
            estado["fumadas"] += 1
            yield ("trabajo", f"{nombre} (tiene {ingrediente_propio}) arma y fuma")
            yield ("liberar", agente_mesa)   # avisa al agente que la mesa está libre

    simulador = SimuladorPasos(instantanea)
    simulador.agregar_hilo("Agente", agente())
    simulador.agregar_hilo("Pusher tabaco", pusher_tabaco())
    simulador.agregar_hilo("Pusher papel", pusher_papel())
    simulador.agregar_hilo("Pusher cerillos", pusher_cerillos())
    simulador.agregar_hilo("Fumador tabaco", fumador("Fumador tabaco", "tabaco"))
    simulador.agregar_hilo("Fumador papel", fumador("Fumador papel", "papel"))
    simulador.agregar_hilo("Fumador cerillos", fumador("Fumador cerillos", "cerillos"))
    simulador.ejecutar()

    return ProblemaConcurrencia(
        id="fumadores",
        titulo="5. Los Fumadores",
        descripcion=(
            "Tres fumadores tienen cada uno un suministro infinito de un solo "
            "ingrediente (tabaco, papel o cerillos). Un agente coloca dos "
            "ingredientes distintos en la mesa y espera. Solo el fumador que "
            "tiene el tercer ingrediente puede armar su cigarrillo y fumar."
        ),
        mecanismo=(
            "Solución de los hilos 'pushers' (David Parnas): 3 semáforos del "
            "agente (tabaco, papel, cerillos), 1 semáforo 'agente_mesa' = 1, 3 "
            "semáforos privados de los fumadores, 1 Mutex y 3 booleanos que "
            "registran qué ingredientes hay. Cada pusher espera su ingrediente y, "
            "con el mutex, coordina con el otro para despertar directamente al "
            "fumador correcto, evitando que un fumador equivocado robe un "
            "ingrediente (que causaría un interbloqueo)."
        ),
        hilos=[h.nombre for h in simulador.hilos],
        pasos=simulador.pasos,
        deadlock=simulador.deadlock,
    )


#  ESTILOS DE LA SECCIÓN DE CONCURRENCIA


ESTILO_CONCURRENCIA = """
.boletin-conc { color: var(--texto-suave); font-size: 14.5px; max-width: 90ch; margin-bottom: 16px; }
.pestanas-conc { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 20px; }
.pestana-conc {
    font: inherit; font-size: 13.5px; cursor: pointer;
    background: var(--fondo-alterno); color: var(--texto);
    border: 1px solid var(--borde); border-radius: 9px; padding: 8px 14px;
}
.pestana-conc:hover { border-color: var(--acento); }
.pestana-conc.activa { background: var(--acento); color: #12161f; border-color: var(--acento); font-weight: 600; }
.conc-panel { }
.conc-subtitulo { font-size: 21px; margin-bottom: 8px; }
.mecanismo-conc {
    background: var(--fondo-alterno); border-left: 3px solid var(--acento);
    border-radius: 0 9px 9px 0; padding: 11px 15px; font-size: 13.5px;
    color: var(--texto-suave); margin-bottom: 18px;
}
.reproductor-conc { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin: 14px 0 6px; }
.conc-paso-label { color: var(--texto-suave); font-size: 13px; font-family: 'Cascadia Mono', Consolas, monospace; margin-left: 4px; }
.timeline { overflow-x: auto; background: var(--fondo-alterno); border: 1px solid var(--borde); border-radius: 11px; padding: 12px; }
.tl-fila { display: flex; align-items: center; gap: 10px; height: 20px; }
.tl-nombre {
    width: 132px; flex: 0 0 132px; text-align: right; font-size: 12px;
    font-family: 'Cascadia Mono', Consolas, monospace; color: var(--texto);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tl-celdas { display: flex; gap: 2px; }
.tl-celda { width: 9px; height: 14px; border-radius: 2px; display: inline-block; }
.tl-celda.oculto { visibility: hidden; }
.tl-celda.cursor-paso { box-shadow: 0 0 0 2px var(--destacado); }
.leyenda { display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--texto-suave); margin-top: 12px; }
.leyenda span { display: inline-flex; align-items: center; gap: 6px; }
.leyenda i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.dos-columnas { display: grid; grid-template-columns: 1fr 1.3fr; gap: 16px; margin-top: 18px; }
@media (max-width: 900px) { .dos-columnas { grid-template-columns: 1fr; } }
.conc-recurso { background: var(--fondo-alterno); border: 1px solid var(--borde); border-radius: 11px; padding: 12px 15px; min-height: 120px; }
.rec-linea { display: flex; justify-content: space-between; gap: 12px; padding: 5px 0; border-bottom: 1px dashed var(--borde); font-size: 13px; }
.rec-linea:last-child { border-bottom: none; }
.rec-clave { color: var(--texto-suave); }
.rec-valor { font-family: 'Cascadia Mono', Consolas, monospace; color: var(--texto); text-align: right; }
.eventos-caja { max-height: 380px; overflow: auto; border: 1px solid var(--borde); border-radius: 11px; }
.eventos-tabla { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.eventos-tabla th {
    text-align: left; padding: 8px 10px; color: var(--texto-suave); font-size: 11px;
    text-transform: uppercase; letter-spacing: 0.8px; border-bottom: 1px solid var(--borde);
    position: sticky; top: 0; background: var(--carta);
}
.eventos-tabla td { padding: 6px 10px; border-bottom: 1px solid var(--borde); }
.eventos-tabla tbody tr.oculto-fila { visibility: hidden; }
.eventos-tabla tbody tr.fila-actual { background: rgba(91, 157, 255, 0.18); }
.eventos-tabla td:nth-child(1) { color: var(--texto-suave); font-family: monospace; }
.eventos-tabla td:nth-child(2) { white-space: nowrap; }
.eventos-tabla td:nth-child(3) { color: var(--acento); font-family: monospace; }
"""


#  CONSTRUCCIÓN DE UN PROBLEMA EN HTML


def _leyenda_html() -> str:
    partes = ['<div class="leyenda">']
    etiquetas = {
        LISTO: "Listo",
        EJECUTANDO: "Ejecutando (avanza este paso)",
        BLOQUEADO: "Bloqueado (esperando recurso)",
        TERMINADO: "Terminado",
    }
    for estado, texto in etiquetas.items():
        partes.append(
            f'<span><i style="background:{COLOR_ESTADO[estado]}"></i>{texto}</span>'
        )
    partes.append("</div>")
    return "".join(partes)


def _timeline_html(problema: ProblemaConcurrencia) -> str:
    filas = []
    for hilo in problema.hilos:
        celdas = []
        for paso in problema.pasos:
            estado = paso["estados"].get(hilo, "")
            color = COLOR_ESTADO.get(estado, "#333")
            activa = " cursor-paso" if paso["hilo"] == hilo else ""
            celdas.append(
                f'<span class="tl-celda{activa}" data-paso="{paso["n"]}" '
                f'style="background:{color}" '
                f'title="Paso {paso["n"]} · {escape(hilo)} · {escape(estado)}"></span>'
            )
        filas.append(
            f'<div class="tl-fila">'
            f'<span class="tl-nombre" title="{escape(hilo)}">{escape(hilo)}</span>'
            f'<div class="tl-celdas">{"".join(celdas)}</div>'
            f'</div>'
        )
    return "".join(filas)


def _eventos_html(problema: ProblemaConcurrencia) -> str:
    filas = []
    for paso in problema.pasos:
        filas.append(
            f'<tr data-paso="{paso["n"]}">'
            f'<td>{paso["n"]}</td>'
            f'<td>{escape(paso["hilo"])}</td>'
            f'<td>{escape(paso["operacion"])}</td>'
            f'<td>{escape(paso["detalle"])}</td>'
            f'</tr>'
        )
    return (
        '<table class="eventos-tabla"><thead><tr>'
        '<th>#</th><th>Hilo</th><th>Operación</th><th>Detalle</th>'
        '</tr></thead><tbody>' + "".join(filas) + '</tbody></table>'
    )


def _aviso_interbloqueo(problema: ProblemaConcurrencia) -> str:
    if not problema.deadlock:
        return ""
    return (
        '<div class="aviso-error"><b>Aviso:</b> la simulación detectó que todos '
        'los hilos quedaron bloqueados (posible interbloqueo).</div>'
    )


def _seccion_problema(problema: ProblemaConcurrencia) -> str:
    """Contenido completo de un problema: título, descripción, controles y paneles."""
    return (
        f'<h3 class="conc-subtitulo">{escape(problema.titulo)}</h3>'
        f'<p class="descripcion">{escape(problema.descripcion)}</p>'
        f'<p class="rotulo">Mecanismo de sincronización</p>'
        f'<p class="mecanismo-conc">{escape(problema.mecanismo)}</p>'
        f'<div class="reproductor-conc">'
        f'<button class="boton boton-primario conc-play" type="button">Reproducir</button>'
        f'<button class="boton conc-paso-siguiente" type="button">Paso a paso</button>'
        f'<button class="boton conc-reset" type="button">Reiniciar</button>'
        f'<span class="conc-paso-label">Paso 0 / {problema.total_pasos}</span>'
        f'</div>'
        f'<p class="rotulo">Línea de tiempo de los hilos</p>'
        f'<div class="timeline">{_timeline_html(problema)}</div>'
        f'{_leyenda_html()}'
        f'<div class="dos-columnas">'
        f'<div><p class="rotulo">Estado del recurso compartido</p>'
        f'<div class="conc-recurso"><p class="vacio">La simulación todavía no ha '
        f'comenzado.</p></div></div>'
        f'<div><p class="rotulo">Registro de eventos</p>'
        f'<div class="eventos-caja">{_eventos_html(problema)}</div></div>'
        f'</div>'
        f'{_aviso_interbloqueo(problema)}'
    )


def cuerpo_concurrencia(problemas: Sequence[ProblemaConcurrencia]) -> str:
    """Pestañas de los 5 problemas + el panel de cada uno (el primero activo)."""
    botones, paneles = [], []
    for indice, problema in enumerate(problemas):
        activa = " activa" if indice == 0 else ""
        display = "" if indice == 0 else "display:none"
        botones.append(
            f'<button class="pestana-conc{activa}" data-conc="{problema.id}" '
            f'type="button">{escape(problema.titulo)}</button>'
        )
        paneles.append(
            f'<div class="conc-panel" id="conc-panel-{problema.id}" '
            f'style="{display}">{_seccion_problema(problema)}</div>'
        )
    intro = (
        '<p class="boletin-conc">Los cinco problemas clásicos de concurrencia, '
        'resueltos con los mecanismos de sincronización descritos en la guía. '
        'Elija un problema, reproduzca la simulación paso a paso y observe el '
        'estado de los hilos y del recurso compartido en cada instante.</p>'
    )
    return (
        f'<section class="seccion">{intro}'
        f'<div class="pestanas-conc">{"".join(botones)}</div>'
        f'{"".join(paneles)}</section>'
    )


def datos_concurrencia(problemas: Sequence[ProblemaConcurrencia]) -> list:
    """Datos que consume el JavaScript para animar cada problema."""
    return [
        {
            "id": problema.id,
            "titulo": problema.titulo,
            "hilos": problema.hilos,
            "pasos": problema.pasos,
        }
        for problema in problemas
    ]


#  SCRIPT DE ANIMACIÓN DE CONCURRENCIA

SCRIPT_CONCURRENCIA = """
(function () {
    const DATOS = __DATOS_CONC__;
    const CONTROL = {};

    function pintar(id) {
        const reg = CONTROL[id];
        if (!reg) return;
        const actual = reg.pasoActual;

        reg.celdas.forEach(function (c) {
            const n = +c.getAttribute('data-paso');
            c.classList.toggle('oculto', n > actual);
            c.classList.toggle('cursor-paso', n === actual);
        });
        reg.filas.forEach(function (f) {
            const n = +f.getAttribute('data-paso');
            f.classList.toggle('oculto-fila', n > actual);
            f.classList.toggle('fila-actual', n === actual);
        });

        if (actual === 0) {
            reg.recurso.innerHTML =
                '<p class="vacio">La simulación todavía no ha comenzado.</p>';
            reg.etiqueta.textContent = 'Paso 0 / ' + reg.total;
            return;
        }
        const p = reg.pasos[actual - 1];
        let html = '';
        Object.keys(p.recurso).forEach(function (k) {
            html += '<div class="rec-linea"><span class="rec-clave">' + k +
                    '</span><span class="rec-valor">' + p.recurso[k] + '</span></div>';
        });
        reg.recurso.innerHTML = html;
        reg.etiqueta.textContent = 'Paso ' + actual + ' / ' + reg.total +
            ' · ' + p.hilo + ' → ' + p.operacion;
    }

    function pausar(id) {
        const reg = CONTROL[id];
        reg.corriendo = false;
        if (reg.botonPlay) reg.botonPlay.textContent = 'Reproducir';
        clearInterval(reg.timer);
        reg.timer = null;
    }

    function alternar(id) {
        const reg = CONTROL[id];
        if (reg.corriendo) { pausar(id); return; }
        if (reg.pasoActual >= reg.total) reg.pasoActual = 0;
        reg.corriendo = true;
        reg.botonPlay.textContent = 'Pausa';
        pintar(id);
        reg.timer = setInterval(function () {
            if (reg.pasoActual >= reg.total) { pausar(id); return; }
            reg.pasoActual += 1;
            pintar(id);
            if (reg.pasoActual >= reg.total) pausar(id);
        }, 300);
    }

    function reiniciar(id) {
        const reg = CONTROL[id];
        pausar(id);
        reg.pasoActual = 0;
        pintar(id);
    }

    function avanzar(id) {
        const reg = CONTROL[id];
        pausar(id);
        if (reg.pasoActual < reg.total) {
            reg.pasoActual += 1;
            pintar(id);
        }
    }

    DATOS.forEach(function (p) {
        const panel = document.getElementById('conc-panel-' + p.id);
        if (!panel) return;
        CONTROL[p.id] = {
            pasos: p.pasos,
            total: p.pasos.length,
            pasoActual: 0,
            corriendo: false,
            timer: null,
            celdas: Array.from(panel.querySelectorAll('.tl-celda')),
            filas: Array.from(panel.querySelectorAll('.eventos-tabla tbody tr')),
            recurso: panel.querySelector('.conc-recurso'),
            etiqueta: panel.querySelector('.conc-paso-label'),
            botonPlay: panel.querySelector('.conc-play'),
        };
        const reg = CONTROL[p.id];
        reg.botonPlay.addEventListener('click', function () { alternar(p.id); });
        panel.querySelector('.conc-reset').addEventListener('click', function () { reiniciar(p.id); });
        panel.querySelector('.conc-paso-siguiente').addEventListener('click', function () { avanzar(p.id); });
        pintar(p.id);
    });

    const botones = document.querySelectorAll('.pestana-conc');
    botones.forEach(function (b) {
        b.addEventListener('click', function () {
            botones.forEach(function (x) { x.classList.remove('activa'); });
            b.classList.add('activa');
            document.querySelectorAll('.conc-panel').forEach(function (panel) {
                panel.style.display = 'none';
            });
            const activo = document.getElementById('conc-panel-' + b.getAttribute('data-conc'));
            activo.style.display = '';
        });
    });
})();
"""


#  PLANTILLA PARA UN REPORTE INDIVIDUAL


PLANTILLA_INDIVIDUAL = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__ - Simulador de concurrencia</title>
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
h1, h2, h3 { margin: 0; font-weight: 700; letter-spacing: -0.4px; }
p { margin: 0; }
.seccion {
    background: var(--carta);
    border: 1px solid var(--borde);
    border-radius: 16px;
    padding: 26px 28px 30px;
    margin: 22px 0;
}
.portada { text-align: center; padding: 42px 28px 32px; }
.portada h1 { font-size: 28px; }
.portada .subtitulo { color: var(--texto-suave); margin-top: 10px; font-size: 15px; }
.boton {
    font: inherit; font-size: 14px; cursor: pointer;
    background: var(--fondo-alterno); color: var(--texto);
    border: 1px solid var(--borde); border-radius: 9px; padding: 8px 15px;
}
.boton:hover { border-color: var(--acento); }
.boton-primario { background: var(--acento); color: #12161f; border-color: var(--acento); font-weight: 600; }
.titulo-seccion { display: flex; align-items: baseline; gap: 12px; font-size: 22px; margin-bottom: 6px; }
.descripcion { color: var(--texto-suave); font-size: 14.5px; max-width: 90ch; margin-bottom: 8px; }
.rotulo { font-size: 12px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--texto-suave); margin: 20px 0 9px; }
.vacio { color: var(--texto-suave); font-size: 13px; }
.aviso-error {
    border-left: 3px solid var(--destacado); background: var(--fondo-alterno);
    padding: 14px 18px; border-radius: 0 9px 9px 0; margin: 22px 0; font-size: 14px;
}
.pie { text-align: center; color: var(--texto-suave); font-size: 13px; margin-top: 30px; }
__ESTILO_CONC__
</style>
</head>
<body>
<div class="envoltorio">
  <header class="seccion portada">
    <h1>Simulador de concurrencia</h1>
    <p class="subtitulo">__TITULO__</p>
  </header>
  <section class="seccion">
    <div class="conc-panel" id="conc-panel-__ID__">__CUERPO__</div>
  </section>
  <p class="pie">Problemas clásicos de concurrencia · Sistemas Operativos</p>
</div>
<script>
__SCRIPT__
</script>
</body>
</html>
"""


#  API PÚBLICA


PROBLEMAS_DISPONIBLES = [
    simular_productor_consumidor,
    simular_lectores_escritores,
    simular_filosofos,
    simular_barbero,
    simular_fumadores,
]


def construir_problemas() -> List[ProblemaConcurrencia]:
    """Simula los 5 problemas y devuelve sus resultados ya calculados."""
    return [constructor() for constructor in PROBLEMAS_DISPONIBLES]


def generar_reporte_individual(problema: ProblemaConcurrencia,
                               ruta_salida: str | Path) -> Path:
    """Escribe un reporte HTML con un único problema."""
    destino = Path(ruta_salida)
    cuerpo = _seccion_problema(problema)
    datos = json.dumps(datos_concurrencia([problema]), ensure_ascii=True)
    script = SCRIPT_CONCURRENCIA.replace("__DATOS_CONC__", datos)

    html = (
        PLANTILLA_INDIVIDUAL
        .replace("__VARIABLES_TEMA__", _estilos_como_css())
        .replace("__ESTILO_CONC__", ESTILO_CONCURRENCIA)
        .replace("__TITULO__", escape(problema.titulo))
        .replace("__ID__", problema.id)
        .replace("__CUERPO__", cuerpo)
        .replace("__SCRIPT__", script)
    )
    destino.write_text(html, encoding="utf-8")
    return destino


def generar_reportes_individuales(carpeta: str | Path) -> List[Path]:
    """Genera un reporte por cada problema en la carpeta indicada."""
    base = Path(carpeta)
    rutas = []
    for problema in construir_problemas():
        nombre = f"reporte_concurrencia_{problema.id.replace('-', '_')}.html"
        rutas.append(generar_reporte_individual(problema, base / nombre))
    return rutas


def main() -> None:
    """Genera los 5 reportes individuales y abre el primero."""
    carpeta = Path(__file__).parent
    rutas = generar_reportes_individuales(carpeta)
    for ruta in rutas:
        print(f"Reporte generado : {ruta.name}")
    webbrowser.open(rutas[0].resolve().as_uri())


if __name__ == "__main__":
    main()



