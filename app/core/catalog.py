"""Construccion del maestro de piezas a partir del libro de pedidos B2B.

Funcionalidad:
    La fuente B2B-Parts-Rec trae el consumo real de repuestos industriales del
    sector de alimentos y bebidas, pero no trae maestro: el identificador de
    pieza es un hash anonimo, la descripcion viene como vector cuantizado
    irreversible, y no hay familia, criticidad ni cantidad. Este modulo compone
    esas cuatro cosas a partir de lo que si se observa.

    Hay que ser explicito sobre que es medido y que es derivado, porque la mitad
    de este modulo produce dato sintetico y el proyecto no admite pasarlo por
    observacion.

    MEDIDO en la fuente y usado tal cual:
      · el precio unitario de cada pieza
      · en cuantas maquinas distintas se consume
      · en que mes se pidio, que es el proceso de llegadas y la razon de usar
        esta fuente

    DERIVADO de lo anterior con una regla declarada:
      · la criticidad, por el numero de maquinas a las que sirve la pieza
      · la familia, por el rango de precio de la pieza contra una composicion
        de catalogo declarada

    SINTETICO, inventado sobre una distribucion:
      · la cantidad de cada pedido, que la fuente no registra
      · la descripcion comercial, que no se puede recuperar del vector

    Sobre la descripcion conviene insistir. El texto original existio, se
    convirtio en vector y el vector se comprimio con cuantizacion de producto.
    Las dos transformaciones son irreversibles, asi que el nombre real de la
    pieza no esta y no se puede reconstruir. Lo que se genera aqui es un nombre
    plausible dentro de su familia, no el nombre de la pieza. Por eso el
    identificador conserva el prefijo del hash anonimo en vez de fabricar un
    numero de parte de fabricante: el codigo dice a las claras que no es un
    catalogo real, y la descripcion sirve para que un comprador reconozca de que
    tipo de pieza se habla.

    Un intento previo fallo y conviene dejar escrito por que. La primera version
    agrupaba las piezas por co-ocurrencia en maquina y etiquetaba cada grupo con
    la banda de precio de su mediana, suponiendo que las piezas que se montan en
    los mismos equipos son del mismo tipo. Es falso: la co-ocurrencia en maquina
    agrupa piezas COMPLEMENTARIAS, no equivalentes. Una llenadora necesita a la
    vez rodamientos, sellos y sensores, asi que cada grupo mezclaba familias y su
    precio mediano colapsaba al centro de la distribucion. El resultado fue que
    dos tercios del catalogo cayeron en una sola familia. El dato de maquina si
    sirve, pero para medir el alcance de una pieza en la planta, que es lo que
    hoy alimenta la criticidad.
"""

import hashlib

import numpy as np
import pandas as pd

SKU_PREFIX = "B2B"

SEED = 20260820

CRITICALITY_SHARE_A = 0.08
CRITICALITY_SHARE_B = 0.30

QUANTITY_SCALE = 60.0
QUANTITY_EXPONENT = 0.45
QUANTITY_MAX = 60
QUANTITY_DISPERSION = 2.0

FAMILIES = [
    ("Fastener", 0.12, 3650),
    ("Seal & Gasket", 0.16, 730),
    ("Lubrication", 0.11, 180),
    ("Filter", 0.12, 365),
    ("Drive Belt", 0.11, 1095),
    ("Bearing", 0.14, 1825),
    ("Coupling", 0.09, 2555),
    ("Sensor", 0.08, 1825),
    ("Electrical", 0.07, 1825),
]

SHELF_LIFE_BY_FAMILY = {name: days for name, _, days in FAMILIES}

DESCRIPTION_MODELS = {
    "Fastener": ["Hex Bolt", "Socket Head Screw", "Lock Washer Set", "Threaded Rod",
                 "Retaining Ring", "Stud Assembly"],
    "Seal & Gasket": ["O-Ring NBR", "Lip Seal", "Flange Gasket", "CIP Gasket EPDM",
                      "Shaft Seal", "Rotary Seal Kit"],
    "Lubrication": ["Food Grade Grease", "Gear Oil", "Chain Lubricant", "Grease Cartridge",
                    "Hydraulic Fluid", "Lubrication Nipple"],
    "Filter": ["Air Filter Cartridge", "Hydraulic Filter Element", "Membrane Filter",
               "Filter Candle", "Breather Filter", "Coalescing Element"],
    "Drive Belt": ["V-Belt", "Poly-V Belt", "Timing Belt", "Conveyor Belt Section",
                   "Flat Belt", "Toothed Belt"],
    "Bearing": ["Deep Groove Ball Bearing", "Cylindrical Roller Bearing",
                "Spherical Roller Bearing", "Angular Contact Bearing",
                "Tapered Roller Bearing", "Pillow Block Unit"],
    "Coupling": ["Jaw Coupling", "Flexible Coupling", "Gear Coupling", "Torque Limiter",
                 "Shaft Collar Assembly", "Universal Joint"],
    "Sensor": ["Proximity Sensor", "Photoelectric Sensor", "Pressure Transmitter",
               "Temperature Probe", "Flow Meter", "Level Sensor"],
    "Electrical": ["Contactor", "Servo Drive", "Frequency Inverter", "PLC Input Module",
                   "Motor Starter", "Safety Relay"],
}


def sku_from_item(item_id: str) -> str:
    """Traduce el identificador anonimo de la fuente a un codigo de pieza.

    Entrada:
        item_id: hash anonimo del item en la fuente B2B.

    Salida:
        Codigo de pieza con el prefijo del proyecto.

    Funcionalidad:
        Conserva el hash de origen en lugar de fabricar un numero de parte de
        fabricante. Es deliberado: un codigo con forma de referencia real
        invitaria a buscarla en un catalogo donde no existe, mientras que este
        deja claro de un vistazo que la pieza viene de una fuente anonimizada.
    """
    return f"{SKU_PREFIX}-{item_id[:8].upper()}"


def _stable_index(sku_id: str, size: int) -> int:
    """Elige una posicion reproducible a partir del codigo de la pieza.

    Entrada:
        sku_id: codigo de la pieza.
        size: numero de opciones disponibles.

    Salida:
        Indice entre 0 y size - 1.

    Funcionalidad:
        Deriva la eleccion del propio codigo en lugar de un generador aleatorio,
        de modo que la misma pieza reciba siempre la misma descripcion aunque el
        dataset se reconstruya en otro orden o en otra maquina.
    """
    digest = hashlib.sha1(sku_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(size, 1)


def build_description(sku_id: str, family: str) -> str:
    """Redacta un nombre comercial plausible para una pieza.

    Entrada:
        sku_id: codigo de la pieza.
        family: familia a la que quedo asignada.

    Salida:
        Descripcion en el formato que usa un catalogo de refacciones.

    Funcionalidad:
        Es dato sintetico y no debe leerse de otra forma: el nombre real se
        perdio en la anonimizacion de la fuente. Lo que se conserva del original
        es el orden de precio, que si es observado, asi que la gama de la pieza
        es defendible aunque el modelo concreto no lo sea.

        El sufijo numerico sale del propio codigo, de modo que dos piezas
        distintas no compartan nombre y la tabla no parezca repetida.
    """
    models = DESCRIPTION_MODELS.get(family, ["Spare Part"])
    model = models[_stable_index(sku_id, len(models))]
    size = 10 + _stable_index(sku_id + "size", 190)
    return f"{model} {size}"


def assign_families(items: pd.DataFrame) -> pd.Series:
    """Asigna una familia a cada pieza segun su lugar en la escala de precio.

    Entrada:
        items: tabla de piezas con la columna unit_cost_usd.

    Salida:
        Serie con la familia de cada pieza.

    Funcionalidad:
        Ordena el catalogo por costo unitario y lo reparte entre las nueve
        familias segun la composicion declarada en FAMILIES, que va de la mas
        barata a la mas cara. La tornilleria y los sellos son consumibles de
        pocos dolares y alta rotacion; un variador o un modulo de control cuesta
        miles y se pide una vez cada varios anos.

        Se reparte por cuota y no por umbrales fijos en dolares. Un umbral
        absoluto depende de que catalogo salga del filtro de actividad: como las
        piezas frecuentes son las baratas, el catalogo seleccionado es mucho mas
        economico que la fuente completa, y unos cortes pensados para la fuente
        dejarian las familias caras vacias. Repartir por cuantil garantiza que
        las nueve se pueblen y conserva la senal, que es el orden de precio.

        Es dato derivado. La familia real de cada pieza se perdio con la
        anonimizacion; lo que se afirma aqui es que una pieza del percentil mas
        bajo de precio se comporta como tornilleria, no que lo sea.
    """
    order = items["unit_cost_usd"].rank(method="first", ascending=True)
    position = (order - 1) / max(len(items), 1)

    labels = pd.Series(FAMILIES[-1][0], index=items.index, dtype=object)
    lower = 0.0
    for name, share, _ in FAMILIES:
        upper = lower + share
        labels.loc[(position >= lower) & (position < upper)] = name
        lower = upper
    return labels


def derive_criticality(items: pd.DataFrame) -> pd.Series:
    """Deduce la criticidad de cada pieza por su alcance en planta.

    Entrada:
        items: tabla de piezas con las columnas machine_count y unit_cost_usd.

    Salida:
        Serie con la criticidad A, B o C de cada pieza.

    Funcionalidad:
        Una pieza que sirve a muchas maquinas distintas detiene mas cosas cuando
        falta, asi que el numero de equipos que dependen de ella es el mejor
        proxy observable de criticidad que ofrece la fuente. El precio rompe los
        empates, porque entre dos piezas de igual alcance la cara suele ser la
        que para la linea.

        Es el unico uso que se le da al dato de maquina, y es donde de verdad
        aporta: mide alcance, que es lo que la co-ocurrencia no sabia decir.

        Las proporciones se imponen por cuota y no por umbral: A el 8 % y B el
        30 % siguiente. Un umbral fijo sobre el numero de maquinas daria un
        reparto distinto en cada corrida segun como quede el catalogo, y la
        politica de servicio del sistema se declara sobre las clases, no sobre
        el corte.

        Es dato derivado, no observado. Si la etiqueta esta mal puesta, el
        modelo protege la pieza equivocada con dinero real, que es el supuesto
        16 del inventario de limitaciones.
    """
    order = items.sort_values(
        ["machine_count", "unit_cost_usd"], ascending=[False, False]
    ).index
    total = len(order)
    cut_a = int(round(total * CRITICALITY_SHARE_A))
    cut_b = cut_a + int(round(total * CRITICALITY_SHARE_B))

    labels = pd.Series("C", index=items.index, dtype=object)
    labels.loc[order[:cut_a]] = "A"
    labels.loc[order[cut_a:cut_b]] = "B"
    return labels


def expected_quantity(price: float) -> float:
    """Estima cuantas unidades se piden de una pieza en un pedido.

    Entrada:
        price: precio unitario de la pieza.

    Salida:
        Cantidad media esperada por evento de pedido.

    Funcionalidad:
        La fuente registra que se pidio una pieza pero no cuantas, asi que la
        cantidad hay que reconstruirla. El precio es el mejor predictor
        disponible y ademas el mas intuitivo: una junta torica de tres dolares
        se compra por decenas y un variador de ocho mil se compra de uno en uno.

        La relacion es de potencia con exponente menor que uno, de modo que la
        cantidad caiga con el precio pero mucho mas despacio, que es como se
        comporta en un almacen real.
    """
    if price <= 0:
        return float(QUANTITY_MAX)
    return float(np.clip(QUANTITY_SCALE / (price**QUANTITY_EXPONENT), 1.0, QUANTITY_MAX))


def synthesize_quantities(prices: np.ndarray, rng) -> np.ndarray:
    """Genera la cantidad pedida en cada linea de pedido.

    Entrada:
        prices: precio unitario de cada linea.
        rng: generador aleatorio ya sembrado.

    Salida:
        Vector de cantidades enteras, siempre mayores que cero.

    Funcionalidad:
        Sortea sobre una binomial negativa centrada en la cantidad esperada del
        precio. Se usa binomial negativa y no Poisson porque el tamano de pedido
        de refacciones tiene mas dispersion de la que admite una Poisson, y esa
        dispersion es justo lo que decide en que cuadrante de la clasificacion
        de patrones cae la serie.

        Es la unica pieza del dataset que no puede validarse contra la fuente,
        porque la fuente no la trae. Lo que si se valida es su consecuencia: el
        coeficiente de variacion resultante tiene que dejar las series en el
        regimen irregular que describe la literatura de refacciones.
    """
    means = np.array([expected_quantity(price) for price in prices], dtype=float)
    dispersion = QUANTITY_DISPERSION
    probability = dispersion / (dispersion + means)
    return np.maximum(1, rng.negative_binomial(dispersion, probability) + 1)
