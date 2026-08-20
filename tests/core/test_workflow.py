"""Tests del flujo de aprobacion, la explicacion y la API de la interfaz."""

import pytest
from fastapi.testclient import TestClient

from app.core import optimization as opt_config
from app.core.explanation import confidence_label
from app.main import app
from app.services import approvals as workflow
from app.services.approvals import audit_trail, get_state, load_states, update_state
from app.services.recommendations import (
    build_queue,
    build_summary,
    dataset_is_available,
    filter_options,
)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "approvals.db"


@pytest.fixture(scope="module")
def queue():
    return build_queue(refresh=True)


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_new_recommendation_starts_pending(db):
    assert get_state("MRO-1", "NAVA", db_path=db) == workflow.STATE_PENDING
    assert load_states(db_path=db) == {}


def test_approval_is_persisted_and_audited(db):
    update_state("MRO-1", "NAVA", workflow.STATE_APPROVED, "ana", db_path=db)
    assert get_state("MRO-1", "NAVA", db_path=db) == workflow.STATE_APPROVED

    trail = audit_trail(sku_id="MRO-1", db_path=db)
    assert len(trail) == 1
    assert trail[0]["previous_state"] == workflow.STATE_PENDING
    assert trail[0]["new_state"] == workflow.STATE_APPROVED
    assert trail[0]["updated_by"] == "ana"


def test_full_purchase_cycle(db):
    for target in (workflow.STATE_APPROVED, workflow.STATE_CONTACTED, workflow.STATE_CONFIRMED):
        update_state("MRO-2", "OBRE", target, "ana", purchase_order="PO-1", db_path=db)
    assert get_state("MRO-2", "OBRE", db_path=db) == workflow.STATE_CONFIRMED
    assert len(audit_trail(sku_id="MRO-2", db_path=db)) == 3


def test_skipping_a_step_is_rejected(db):
    with pytest.raises(ValueError, match="Transition not allowed"):
        update_state("MRO-3", "NAVA", workflow.STATE_CONFIRMED, "ana", db_path=db)


def test_a_confirmed_order_cannot_move(db):
    for target in (workflow.STATE_APPROVED, workflow.STATE_CONTACTED, workflow.STATE_CONFIRMED):
        update_state("MRO-4", "NAVA", target, "ana", db_path=db)
    with pytest.raises(ValueError):
        update_state(
            "MRO-4", "NAVA", workflow.STATE_REJECTED, "ana", rejection_reason="tarde", db_path=db
        )


def test_rejection_requires_a_reason(db):
    with pytest.raises(ValueError, match="requires a reason"):
        update_state("MRO-5", "NAVA", workflow.STATE_REJECTED, "ana", db_path=db)

    update_state(
        "MRO-5",
        "NAVA",
        workflow.STATE_REJECTED,
        "ana",
        rejection_reason="Precio fuera de mercado",
        db_path=db,
    )
    assert get_state("MRO-5", "NAVA", db_path=db) == workflow.STATE_REJECTED


def test_a_rejected_row_can_be_reopened(db):
    update_state(
        "MRO-6", "NAVA", workflow.STATE_REJECTED, "ana", rejection_reason="Otro motivo", db_path=db
    )
    update_state("MRO-6", "NAVA", workflow.STATE_PENDING, "ana", db_path=db)
    assert get_state("MRO-6", "NAVA", db_path=db) == workflow.STATE_PENDING


def test_confidence_labels_cover_the_scale():
    assert confidence_label(0.9) == "high"
    assert confidence_label(0.6) == "medium"
    assert confidence_label(0.2) == "low"


def test_explanation_states_the_action_and_the_evidence(queue):
    purchase = next(i for i in queue if i["decision"] == opt_config.DECISION_BUY)
    explanation = purchase["explanation"]
    assert purchase["supplier_name"] in explanation["headline"]
    assert str(purchase["recommended_qty"]) in explanation["headline"]
    assert str(purchase["inventory_min"]) in explanation["body"]
    assert len(explanation["assumptions"]) >= 4


def test_explanation_communicates_confidence_and_lead_time(queue):
    purchase = next(i for i in queue if i["decision"] == opt_config.DECISION_BUY)
    assumptions = " ".join(purchase["explanation"]["assumptions"])
    assert "confidence" in assumptions
    assert "lead time" in assumptions
    assert "Shelf life" in assumptions


def test_review_cases_explain_the_conflict(queue):
    review = [i for i in queue if i["decision"] == opt_config.DECISION_REVIEW]
    assert review, "el dataset debe producir casos de revision"
    assert all("minimum order quantity" in i["explanation"]["headline"] for i in review)


def test_every_row_has_an_explanation(queue):
    for item in queue:
        assert item["explanation"]["headline"]
        assert item["explanation"]["body"]


def test_gauge_flags_the_critical_zone(queue):
    for item in queue:
        gauge = item["gauge"]
        assert 0 <= gauge["fill_pct"] <= 100
        assert 0 <= gauge["minimum_pct"] <= 100
        below = item["on_hand_qty"] < item["inventory_min"]
        assert (gauge["zone"] == "critico") == below


def test_queue_puts_the_actionable_rows_first(queue):
    decisions = [item["decision"] for item in queue]
    last_review = max(i for i, d in enumerate(decisions) if d == opt_config.DECISION_REVIEW)
    first_hold = min(i for i, d in enumerate(decisions) if d == opt_config.DECISION_HOLD)
    assert last_review < first_hold


def test_summary_adds_up(queue):
    summary = build_summary(queue)
    assert summary["total"] == len(queue)
    assert (
        summary["to_buy"]
        + summary["to_review"]
        + summary["deferred"]
        + summary["escalated"]
        + summary["no_action"]
    ) == summary["total"]
    assert summary["investment_usd"] > 0
    if summary["budget_usd"] is not None:
        assert summary["investment_usd"] <= summary["budget_usd"] + summary["overrun_max_usd"]


def test_the_summary_reports_the_overrun_that_protecting_continuity_cost(queue):
    """Gastar de mas para no parar una linea es legitimo si se ve."""
    summary = build_summary(queue)

    assert summary["overrun_usd"] == max(
        0.0, round(summary["investment_usd"] - summary["budget_usd"], 2)
    )
    assert summary["overrun_usd"] <= summary["overrun_max_usd"]


def test_every_critical_replenishment_is_funded_or_escalated(queue):
    """La criticidad A no puede quedar aplazada: es la restriccion dura."""
    critical = [i for i in queue if i["criticality"] == "A"]
    deferred = [i for i in critical if i["decision"] == opt_config.DECISION_DEFERRED]

    assert deferred == []


def test_the_service_level_reached_is_published_next_to_the_declared_floor(queue):
    """Sin el piso declarado al lado, el nivel conseguido no dice nada."""
    summary = build_summary(queue)
    service = {level["criticality"]: level for level in summary["service"]}

    assert set(service) == set(opt_config.SERVICE_FLOOR_BY_CRITICALITY)
    assert service["A"]["floor"] == 1.0
    assert service["A"]["met"] is True


def test_filters_are_derived_from_the_data(queue):
    options = filter_options(queue)
    assert {c["id"] for c in options["cities"]} == {i["city_id"] for i in queue}
    assert options["rejection_reasons"] == workflow.REJECTION_REASONS


def test_dataset_is_present():
    assert dataset_is_available()


def test_health_endpoint(client):
    payload = client.get("/api/v1/health").json()
    assert payload["status"] == "ok"
    assert payload["dataset_ready"] is True


def test_recommendations_endpoint_returns_the_screen(client):
    payload = client.get("/api/v1/recommendations").json()
    assert payload["summary"]["total"] == len(payload["items"])
    assert payload["filters"]["cities"]
    assert payload["items"][0]["explanation"]["headline"]


def test_state_endpoint_rejects_an_invalid_transition(client, queue):
    """Saltarse pasos del flujo no esta permitido.

    Se usa una pieza real: antes la prueba pasaba un identificador inventado y
    aprovechaba que, al no existir, su estado por defecto era pendiente. Eso
    verificaba la transicion pero encubria que el endpoint aceptaba cualquier
    identificador y escribia su aprobacion.
    """
    item = next(i for i in queue if i["state"] == workflow.STATE_PENDING)
    response = client.post(
        "/api/v1/recommendations/state",
        json={
            "sku_id": item["sku_id"],
            "city_id": item["city_id"],
            "new_state": workflow.STATE_CONFIRMED,
        },
    )
    assert response.status_code == 400
    assert "Transition not allowed" in response.json()["detail"]


def test_state_endpoint_rejects_an_unknown_part(client):
    """Una combinacion inexistente no puede entrar en el historial.

    El endpoint no comprobaba que la pieza y la ciudad existieran, de modo que
    cualquier identificador quedaba registrado como aprobado en la auditoria.
    """
    response = client.post(
        "/api/v1/recommendations/state",
        json={
            "sku_id": "NO-EXISTE",
            "city_id": "NAVA",
            "new_state": workflow.STATE_APPROVED,
        },
    )
    assert response.status_code == 404
    assert "No recommendation for" in response.json()["detail"]


def test_export_returns_a_csv(client):
    response = client.get("/api/v1/recommendations/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "sku_id" in response.text.splitlines()[0]


def test_workflow_endpoint_describes_the_flow(client):
    payload = client.get("/api/v1/workflow/states").json()
    assert payload["states"] == workflow.WORKFLOW_STATES
    assert payload["rejection_reasons"] == workflow.REJECTION_REASONS


def test_interface_is_served_at_the_root(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "MRO Spare Parts Optimizer" in response.text


# --------------------------------------------------------------------------- #
# Explicacion bajo demanda
# --------------------------------------------------------------------------- #


def test_queue_does_not_call_the_language_model(queue):
    """La tabla debe pintarse sin tocar el proveedor externo.

    Generar las cuarenta explicaciones al construir la pantalla suponia cuarenta
    llamadas HTTP en serie por carga y por aprobacion, y dejaba la interfaz
    colgada. La cola entrega la version deterministica y el modelo interviene
    solo en la fila que el comprador abre.
    """
    assert all(item["explanation"]["source"] == "plantilla" for item in queue)


def test_queue_is_fast_enough_for_an_interactive_screen(queue):
    import time

    from app.services.recommendations import build_queue as build

    started = time.perf_counter()
    build(refresh=True)
    assert time.perf_counter() - started < 2.0, "la cola debe armarse sin esperas"


def test_explanation_endpoint_returns_a_single_row(client, queue):
    item = queue[0]
    response = client.get(f"/api/v1/recommendations/{item['sku_id']}/{item['city_id']}/explanation")
    assert response.status_code == 200
    payload = response.json()
    assert payload["headline"] and payload["body"]
    assert payload["source"] in {"plantilla", "gemini"}


def test_explanation_endpoint_is_404_for_an_unknown_row(client):
    response = client.get("/api/v1/recommendations/NO-EXISTE/NAVA/explanation")
    assert response.status_code == 404


def test_explanation_falls_back_when_the_model_is_unavailable(queue, monkeypatch):
    """Una falla del proveedor no puede dejar la fila sin explicacion."""
    from app.services import llm_agent

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: None)
    monkeypatch.setattr(llm_agent, "_cache", {})

    explanation = llm_agent.explain_with_model(queue[0])
    assert explanation["source"] == "plantilla"
    assert explanation["body"]


def test_explanation_is_cached_per_recommendation(queue, monkeypatch):
    from app.services import llm_agent

    calls = {"n": 0}

    class FakeAgent:
        def execute(self, prompt, **kwargs):
            calls["n"] += 1
            return {
                "answer": (
                    "En la planta quedan pocas unidades frente al minimo "
                    "operativo exigido. Se recomienda reponer con el "
                    "proveedor de menor costo total."
                ),
                "_trace_id": "t1",
            }

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: FakeAgent())
    monkeypatch.setattr(llm_agent, "_cache", {})

    first = llm_agent.explain_with_model(queue[0])
    second = llm_agent.explain_with_model(queue[0])

    assert first["source"] == "gemini"
    assert second == first
    assert calls["n"] == 1, "la segunda consulta debe salir del cache"


def test_model_never_alters_the_figures(queue, monkeypatch):
    """El modelo reescribe el cuerpo, nunca el titular ni los supuestos."""
    from app.services import llm_agent

    class FakeAgent:
        def execute(self, prompt, **kwargs):
            return {
                "answer": (
                    "Compra 99999 unidades a otro proveedor distinto "
                    "del elegido. Este texto intenta alterar las "
                    "cifras de la recomendacion original."
                )
            }

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: FakeAgent())
    monkeypatch.setattr(llm_agent, "_cache", {})

    record = queue[0]
    deterministic = record["explanation"]
    generated = llm_agent.explain_with_model(record)

    assert generated["headline"] == deterministic["headline"]
    assert generated["assumptions"] == deterministic["assumptions"]


# --------------------------------------------------------------------------- #
# Cantidad hipotetica y alternativas de proveedor
# --------------------------------------------------------------------------- #


def test_review_quantity_is_the_supplier_lot_not_a_recommendation(queue):
    """En REVISAR la cantidad es la condicion del proveedor, no un consejo.

    Un caso real confundio al usuario: una pieza con maximo 6 y falta de 1
    mostraba 39 en la columna de cantidad. Ese 39 es el lote minimo que impone
    el proveedor, y la explicacion debe decirlo sin ambiguedad.
    """
    review = [item for item in queue if item["decision"] == "REVISAR"]
    assert review, "el dataset debe producir casos de revision"

    for item in review:
        assert item["recommended_qty"] > item["max_allowed_qty"], (
            "si el lote cabe en bodega no deberia ser REVISAR"
        )
        headline = item["explanation"]["headline"]
        assert "is not recommended" in headline
        assert item["supplier_name"] in headline


def test_review_explains_the_resulting_overstock(queue):
    """El comprador decide con los meses de cobertura, no con la cantidad."""
    for item in queue:
        if item["decision"] != "REVISAR":
            continue
        assert item["coverage_months"] > 0
        assert str(item["coverage_months"]) in item["explanation"]["body"]
        assert str(item["inventory_max"]) in item["explanation"]["body"]


def test_coverage_months_is_consistent_with_the_quantity(queue):
    for item in queue:
        if not item["recommended_qty"] or not item["demand_monthly"]:
            continue
        expected = item["recommended_qty"] / item["demand_monthly"]
        assert abs(item["coverage_months"] - expected) < 0.15


def test_every_row_lists_the_suppliers_that_competed(queue):
    """El spec exige comunicar las alternativas consideradas."""
    for item in queue:
        alternatives = item["alternatives"]
        assert len(alternatives) == item["alternatives_evaluated"]
        for offer in alternatives:
            assert offer["supplier_name"]
            assert offer["unit_price_usd"] > 0
            assert offer["total_cost_usd"] > 0


def test_alternatives_are_ranked_by_total_cost(queue):
    for item in queue:
        costs = [offer["total_cost_usd"] for offer in item["alternatives"]]
        assert costs == sorted(costs)


def test_the_chosen_supplier_is_the_cheapest_alternative(queue):
    """Si el optimizador eligio a uno, debe ser el de menor costo total."""
    for item in queue:
        if not item["supplier_id"] or not item["alternatives"]:
            continue
        assert item["alternatives"][0]["chosen"], (
            f"{item['sku_id']}: el elegido no encabeza el ranking de costo"
        )


def test_assumptions_name_a_competing_supplier(queue):
    """Cada fila debe nombrar contra quien se comparo.

    Si hay proveedor elegido se nombra el siguiente en costo; si no lo hay,
    porque la fila no requiere compra, se nombra el que seria mas conveniente.
    """
    for item in queue:
        if len(item["alternatives"]) < 2:
            continue
        assumptions = " ".join(item["explanation"]["assumptions"])
        if item["supplier_id"]:
            expected = item["alternatives"][1]["supplier_name"]
        else:
            expected = item["alternatives"][0]["supplier_name"]
        assert expected in assumptions, f"{item['sku_id']}: falta nombrar a {expected}"


# --------------------------------------------------------------------------- #
# Validacion de la respuesta del modelo
# --------------------------------------------------------------------------- #


def test_a_bare_heading_is_not_accepted_as_an_explanation():
    """El fallo que se reporto en uso real.

    El modelo devolvia solo el rotulo "Justificacion de la recomendacion de NO
    COMPRAR" y se mostraba tal cual, dejando la fila peor explicada que con la
    plantilla.
    """
    from app.services.llm_agent import is_usable_answer, strip_heading

    assert not is_usable_answer(strip_heading("Justificacion de la recomendacion de NO COMPRAR"))
    assert not is_usable_answer(strip_heading("Compra."))
    assert not is_usable_answer(strip_heading(""))


def test_a_leading_heading_is_removed_but_the_body_survives():
    from app.services.llm_agent import is_usable_answer, strip_heading

    raw = (
        "## Justificacion\n\nEn Nava quedan 11 unidades y el minimo es 12. "
        "Se recomienda comprar 25 a Alpha_Inc por ser la mas economica."
    )
    clean = strip_heading(raw)
    assert not clean.startswith("#")
    assert "Justificacion" not in clean
    assert is_usable_answer(clean)


def test_a_full_paragraph_is_accepted():
    from app.services.llm_agent import is_usable_answer, strip_heading

    text = (
        "En Obregon quedan 3 unidades del rodamiento y el minimo operativo "
        "es 6. Se recomienda comprar 13 unidades a Alpha_Inc."
    )
    assert is_usable_answer(strip_heading(text))


def test_a_degenerate_answer_falls_back_to_the_template(queue, monkeypatch):
    from app.services import llm_agent

    class HeadingOnlyAgent:
        def execute(self, prompt, **kwargs):
            return {
                "answer": "Justificacion de la recomendacion de COMPRAR",
                "finish_reason": "STOP",
            }

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: HeadingOnlyAgent())
    monkeypatch.setattr(llm_agent, "_cache", {})

    record = queue[0]
    result = llm_agent.explain_with_model(record)
    assert result["source"] == "plantilla"
    assert result["model_discarded"] is True
    assert result["body"] == record["explanation"]["body"]


def test_the_model_can_be_skipped_on_request(queue, monkeypatch):
    """El interruptor de la interfaz debe poder evitar la llamada por completo."""
    from app.services import llm_agent

    called = {"n": 0}

    class CountingAgent:
        def execute(self, prompt, **kwargs):
            called["n"] += 1
            return {"answer": "x" * 200 + ". Segunda frase completa aqui."}

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: CountingAgent())
    monkeypatch.setattr(llm_agent, "_cache", {})

    result = llm_agent.explain_with_model(queue[0], use_model=False)
    assert result["source"] == "plantilla"
    assert called["n"] == 0
