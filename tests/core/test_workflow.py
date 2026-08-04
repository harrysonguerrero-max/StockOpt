"""Tests del flujo de aprobacion, la explicacion y la API de la interfaz."""

import pytest
from fastapi.testclient import TestClient

from app.core import optimization as opt_config
from app.services import approvals as workflow
from app.main import app
from app.services.approvals import audit_trail, get_state, load_states, update_state
from app.core.explanation import build_explanation, confidence_label
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
    with pytest.raises(ValueError, match="Transicion no permitida"):
        update_state("MRO-3", "NAVA", workflow.STATE_CONFIRMED, "ana", db_path=db)


def test_a_confirmed_order_cannot_move(db):
    for target in (workflow.STATE_APPROVED, workflow.STATE_CONTACTED, workflow.STATE_CONFIRMED):
        update_state("MRO-4", "NAVA", target, "ana", db_path=db)
    with pytest.raises(ValueError):
        update_state("MRO-4", "NAVA", workflow.STATE_REJECTED, "ana",
                     rejection_reason="tarde", db_path=db)


def test_rejection_requires_a_reason(db):
    with pytest.raises(ValueError, match="motivo"):
        update_state("MRO-5", "NAVA", workflow.STATE_REJECTED, "ana", db_path=db)

    update_state("MRO-5", "NAVA", workflow.STATE_REJECTED, "ana",
                 rejection_reason="Precio fuera de mercado", db_path=db)
    assert get_state("MRO-5", "NAVA", db_path=db) == workflow.STATE_REJECTED


def test_a_rejected_row_can_be_reopened(db):
    update_state("MRO-6", "NAVA", workflow.STATE_REJECTED, "ana",
                 rejection_reason="Otro motivo", db_path=db)
    update_state("MRO-6", "NAVA", workflow.STATE_PENDING, "ana", db_path=db)
    assert get_state("MRO-6", "NAVA", db_path=db) == workflow.STATE_PENDING


def test_confidence_labels_cover_the_scale():
    assert confidence_label(0.9) == "alta"
    assert confidence_label(0.6) == "media"
    assert confidence_label(0.2) == "baja"


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
    assert "Confianza" in assumptions
    assert "Plazo de entrega" in assumptions
    assert "Vida util" in assumptions


def test_review_cases_explain_the_conflict(queue):
    review = [i for i in queue if i["decision"] == opt_config.DECISION_REVIEW]
    assert review, "el dataset debe producir casos de revision"
    assert all("lote minimo" in i["explanation"]["headline"] for i in review)


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
    assert summary["to_buy"] + summary["to_review"] + summary["no_action"] == summary["total"]
    assert summary["investment_usd"] > 0


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


def test_state_endpoint_rejects_an_invalid_transition(client):
    response = client.post("/api/v1/recommendations/state", json={
        "sku_id": "NO-EXISTE", "city_id": "NAVA", "new_state": workflow.STATE_CONFIRMED,
    })
    assert response.status_code == 400
    assert "Transicion no permitida" in response.json()["detail"]


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
    assert "StockOpt" in response.text


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
    response = client.get(
        f"/api/v1/recommendations/{item['sku_id']}/{item['city_id']}/explanation"
    )
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
            return {"answer": "texto del modelo", "_trace_id": "t1"}

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
            return {"answer": "Compra 99999 unidades a otro proveedor."}

    monkeypatch.setattr(llm_agent, "api_key_available", lambda: True)
    monkeypatch.setattr(llm_agent, "_get_agent", lambda: FakeAgent())
    monkeypatch.setattr(llm_agent, "_cache", {})

    record = queue[0]
    deterministic = record["explanation"]
    generated = llm_agent.explain_with_model(record)

    assert generated["headline"] == deterministic["headline"]
    assert generated["assumptions"] == deterministic["assumptions"]
