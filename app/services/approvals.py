"""Registro de aprobaciones y auditoria del flujo de compra.

Funcionalidad:
    Guarda la decision del comprador sobre cada recomendacion y el historial
    completo de cambios de estado. Usa SQLite de la biblioteca estandar, de modo
    que el MVP persiste entre sesiones sin depender de un motor externo.

    Las recomendaciones se regeneran cada vez que corre el pipeline, mientras
    que las aprobaciones son actos de una persona y deben sobrevivir a esas
    regeneraciones. Por eso viven en un almacen aparte y se cruzan por la llave
    pieza mas ciudad.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

STATE_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "state" / "approvals.db"

STATE_PENDING = "Pendiente aprobacion"
STATE_APPROVED = "Aprobado"
STATE_REJECTED = "Rechazado"
STATE_CONTACTED = "Contactado proveedor"
STATE_CONFIRMED = "Orden confirmada"

WORKFLOW_STATES = [STATE_PENDING, STATE_APPROVED, STATE_CONTACTED, STATE_CONFIRMED]

ALLOWED_TRANSITIONS = {
    STATE_PENDING: [STATE_APPROVED, STATE_REJECTED],
    STATE_APPROVED: [STATE_CONTACTED, STATE_REJECTED],
    STATE_CONTACTED: [STATE_CONFIRMED, STATE_REJECTED],
    STATE_CONFIRMED: [],
    STATE_REJECTED: [STATE_PENDING],
}

REJECTION_REASONS = [
    "Quantity too large for the operation",
    "Another supplier is preferred",
    "Price is out of market",
    "An order is already in progress",
    "Part discontinued or being redesigned",
    "Other reason",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    sku_id TEXT NOT NULL,
    city_id TEXT NOT NULL,
    state TEXT NOT NULL,
    rejection_reason TEXT,
    comment TEXT,
    purchase_order TEXT,
    expected_delivery TEXT,
    updated_by TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (sku_id, city_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku_id TEXT NOT NULL,
    city_id TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT NOT NULL,
    rejection_reason TEXT,
    comment TEXT,
    updated_by TEXT,
    updated_at TEXT NOT NULL
);
"""


def _connect(db_path=None) -> sqlite3.Connection:
    """Abre la conexion al almacen de aprobaciones.

    Entrada:
        db_path: ruta opcional a la base. Por defecto usa la configurada.

    Salida:
        Conexion de sqlite3 con filas accesibles por nombre de columna.

    Funcionalidad:
        Crea el directorio y el esquema la primera vez, de modo que la
        aplicacion arranque sin pasos manuales de instalacion.
    """
    path = db_path or STATE_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def load_states(db_path=None) -> dict:
    """Recupera el estado actual de todas las recomendaciones.

    Entrada:
        db_path: ruta opcional a la base.

    Salida:
        Diccionario indexado por la tupla (sku_id, city_id) con los campos del
        estado guardado.

    Funcionalidad:
        Devuelve solo lo persistido. Las recomendaciones que nunca se tocaron no
        aparecen y la capa que consume asume el estado inicial.
    """
    with closing(_connect(db_path)) as connection:
        rows = connection.execute("SELECT * FROM approvals").fetchall()
    return {(row["sku_id"], row["city_id"]): dict(row) for row in rows}


def get_state(sku_id: str, city_id: str, db_path=None) -> str:
    """Consulta el estado de una recomendacion concreta.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        db_path: ruta opcional a la base.

    Salida:
        Nombre del estado actual. Devuelve el estado inicial si nunca se toco.

    Funcionalidad:
        Encapsula el valor por defecto para que quien consulta no tenga que
        distinguir entre ausencia de registro y estado pendiente.
    """
    states = load_states(db_path)
    record = states.get((sku_id, city_id))
    return record["state"] if record else STATE_PENDING


def update_state(
    sku_id: str,
    city_id: str,
    new_state: str,
    updated_by: str,
    rejection_reason: str | None = None,
    comment: str | None = None,
    purchase_order: str | None = None,
    expected_delivery: str | None = None,
    db_path=None,
) -> dict:
    """Registra un cambio de estado y lo deja auditado.

    Entrada:
        sku_id: identificador de la pieza.
        city_id: identificador de la ciudad.
        new_state: estado al que se quiere mover la recomendacion.
        updated_by: quien realiza el cambio.
        rejection_reason: motivo, obligatorio al rechazar.
        comment: texto libre opcional del comprador.
        purchase_order: numero de orden del proveedor, al confirmar.
        expected_delivery: fecha de entrega esperada, al confirmar.
        db_path: ruta opcional a la base.

    Salida:
        Diccionario con el estado anterior y el nuevo.

    Funcionalidad:
        Valida que la transicion sea legal antes de aplicarla, para que la
        interfaz no pueda dejar una recomendacion en un estado incoherente.
        Cada cambio deja una entrada en el historial con quien lo hizo y cuando,
        que es lo que permite auditar despues por que se compro algo.
    """
    current = get_state(sku_id, city_id, db_path)
    allowed = ALLOWED_TRANSITIONS.get(current, [])
    if new_state not in allowed:
        raise ValueError(
            f"Transition not allowed: {current} -> {new_state}. "
            f"From {current} the only valid next states are {allowed}"
        )
    if new_state == STATE_REJECTED and not rejection_reason:
        raise ValueError("Rejecting a recommendation requires a reason")

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with closing(_connect(db_path)) as connection, connection:
        connection.execute(
            """
                INSERT INTO approvals (sku_id, city_id, state, rejection_reason,
                    comment, purchase_order, expected_delivery, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sku_id, city_id) DO UPDATE SET
                    state = excluded.state,
                    rejection_reason = excluded.rejection_reason,
                    comment = excluded.comment,
                    purchase_order = COALESCE(
                        excluded.purchase_order, approvals.purchase_order),
                    expected_delivery = COALESCE(
                        excluded.expected_delivery, approvals.expected_delivery),
                    updated_by = excluded.updated_by,
                    updated_at = excluded.updated_at
                """,
            (
                sku_id,
                city_id,
                new_state,
                rejection_reason,
                comment,
                purchase_order,
                expected_delivery,
                updated_by,
                timestamp,
            ),
        )
        connection.execute(
            """
                INSERT INTO audit_log (sku_id, city_id, previous_state, new_state,
                    rejection_reason, comment, updated_by, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
            (
                sku_id,
                city_id,
                current,
                new_state,
                rejection_reason,
                comment,
                updated_by,
                timestamp,
            ),
        )
    return {"previous_state": current, "new_state": new_state, "updated_at": timestamp}


def audit_trail(sku_id: str | None = None, city_id: str | None = None, db_path=None) -> list:
    """Recupera el historial de cambios.

    Entrada:
        sku_id: filtra por pieza si se indica.
        city_id: filtra por ciudad si se indica.
        db_path: ruta opcional a la base.

    Salida:
        Lista de movimientos ordenada del mas reciente al mas antiguo.

    Funcionalidad:
        Permite reconstruir quien aprobo que y cuando, tanto para una pieza
        concreta como para toda la operacion.
    """
    query = "SELECT * FROM audit_log"
    conditions = []
    params = []
    if sku_id:
        conditions.append("sku_id = ?")
        params.append(sku_id)
    if city_id:
        conditions.append("city_id = ?")
        params.append(city_id)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC"

    with closing(_connect(db_path)) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]
