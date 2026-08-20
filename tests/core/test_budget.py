"""Tests del reparto del presupuesto entre las compras de una corrida."""

import pandas as pd
import pytest

from app.core.optimization import (
    COLUMNS,
    DECISION_BUY,
    DECISION_DEFERRED,
    DECISION_ESCALATE,
    DECISION_HOLD,
    DECISION_REVIEW,
    REASON_ESCALATE,
    REASON_OVER_BUDGET,
    allocate_budget,
    apply_budget,
    budget_allocation_summary,
)


def candidate(key, cost, benefit, criticality=None):
    """Arma un candidato a compra para la mochila.

    Entrada:
        key: identificador de la combinacion pieza-ciudad.
        cost: costo total de la orden.
        benefit: beneficio neto de hacerla.
        criticality: clase de criticidad de la pieza, si el caso la necesita.

    Salida:
        Diccionario con la forma que espera allocate_budget.

    Funcionalidad:
        Evita repetir la construccion en cada caso de prueba.
    """
    return {
        "key": key,
        "cost": cost,
        "benefit": benefit,
        "criticality": criticality,
        "stockout_cost": cost + benefit,
    }


def recommendation(sku, decision, cost, benefit, **extra):
    """Arma una fila de recomendacion minima.

    Entrada:
        sku: identificador de la pieza.
        decision: decision del optimizador.
        cost: costo total de la orden.
        benefit: beneficio neto de hacer la compra.
        extra: campos adicionales que el caso necesite.

    Salida:
        Diccionario con las columnas que usa el reparto de presupuesto.

    Funcionalidad:
        Solo rellena lo que apply_budget necesita, para que cada test declare
        unicamente lo que esta probando.
    """
    row = dict.fromkeys(COLUMNS)
    row.update(
        {
            "sku_id": sku,
            "city_id": "NAVA",
            "decision": decision,
            "total_cost_usd": cost,
            "net_benefit_usd": benefit,
            "stockout_cost_usd": cost + benefit,
            "recommended_qty": 10,
            "needs_review": 0,
            "reason": "motivo original",
            "inventory_min": 10,
            "on_hand_qty": 4,
            "supplier_name": "Alpha",
        }
    )
    row.update(extra)
    return row


@pytest.fixture
def table():
    return pd.DataFrame(
        [
            recommendation("MRO-1", DECISION_BUY, 600.0, 900.0),
            recommendation("MRO-2", DECISION_BUY, 300.0, 500.0),
            recommendation("MRO-3", DECISION_BUY, 300.0, 450.0),
            recommendation("MRO-4", DECISION_REVIEW, 900.0, 0.0),
            recommendation("MRO-5", DECISION_HOLD, 0.0, 0.0),
        ],
        columns=COLUMNS,
    )


def test_the_knapsack_maximises_the_benefit_it_buys():
    candidates = [
        candidate("a", 600.0, 900.0),
        candidate("b", 300.0, 500.0),
        candidate("c", 300.0, 480.0),
    ]
    chosen = allocate_budget(candidates, 600.0)

    assert chosen["approved"] == {"b", "c"}


def test_without_a_budget_every_purchase_is_approved():
    candidates = [candidate("a", 1000.0, 0.9), candidate("b", 2000.0, 0.5)]

    assert allocate_budget(candidates, None)["approved"] == {"a", "b"}


def test_a_budget_that_covers_everything_approves_everything():
    candidates = [candidate("a", 100.0, 0.9), candidate("b", 200.0, 0.5)]

    assert allocate_budget(candidates, 500.0)["approved"] == {"a", "b"}


def test_the_knapsack_beats_taking_the_most_valuable_first():
    candidates = [
        candidate("cara", 100.0, 90.0),
        candidate("barata_1", 50.0, 60.0),
        candidate("barata_2", 50.0, 60.0),
    ]
    chosen = allocate_budget(candidates, 100.0)

    assert chosen["approved"] == {"barata_1", "barata_2"}


def test_a_purchase_bigger_than_the_whole_budget_is_left_out():
    candidates = [candidate("gigante", 5000.0, 0.99), candidate("normal", 80.0, 0.10)]

    assert allocate_budget(candidates, 100.0)["approved"] == {"normal"}


def test_the_approved_purchases_never_exceed_the_budget(table):
    result = apply_budget(table, 1000.0)
    approved = result[result.decision == DECISION_BUY]

    assert approved.total_cost_usd.sum() <= 1000.0


def test_what_does_not_fit_becomes_deferred_not_discarded(table):
    result = apply_budget(table, 700.0)
    deferred = result[result.decision == DECISION_DEFERRED]

    assert len(deferred) >= 1
    assert (deferred.recommended_qty > 0).all()
    assert deferred.supplier_name.notna().all()
    assert (deferred.total_cost_usd > 0).all()


def test_a_deferred_row_explains_that_the_money_is_what_is_missing(table):
    result = apply_budget(table, 700.0)
    deferred = result[result.decision == DECISION_DEFERRED].iloc[0]

    assert REASON_OVER_BUDGET in deferred.reason
    assert "budget" in deferred.reason
    assert deferred.needs_review == 1


def test_review_rows_do_not_consume_budget(table):
    result = apply_budget(table, 1200.0)

    assert (result[result.sku_id == "MRO-4"].decision == DECISION_REVIEW).all()
    approved = result[result.decision == DECISION_BUY]
    assert approved.total_cost_usd.sum() == 1200.0


def test_rows_that_were_never_purchases_are_untouched(table):
    result = apply_budget(table, 100.0)

    assert (result[result.sku_id == "MRO-5"].decision == DECISION_HOLD).all()
    assert result[result.sku_id == "MRO-5"].iloc[0].reason == "motivo original"


def test_no_budget_leaves_the_table_exactly_as_it_was(table):
    result = apply_budget(table, None)

    pd.testing.assert_frame_equal(result, table)


def test_the_budget_maximises_the_benefit_it_buys(table):
    result = apply_budget(table, 600.0)
    approved = result[result.decision == DECISION_BUY]

    assert set(approved.sku_id) == {"MRO-2", "MRO-3"}
    assert approved.net_benefit_usd.sum() > table.iloc[0].net_benefit_usd
    assert approved.total_cost_usd.sum() <= 600.0


def test_the_most_valuable_piece_can_be_left_out_if_it_blocks_two_others(table):
    result = apply_budget(table, 600.0)
    valiosa = result[result.sku_id == "MRO-1"].iloc[0]

    assert valiosa.decision == DECISION_DEFERRED
    assert REASON_OVER_BUDGET in valiosa.reason


def critical_table():
    """Arma una corrida donde lo critico no cabe en el presupuesto nominal.

    Entrada:
        Ninguna.

    Salida:
        DataFrame de recomendaciones con dos piezas A y dos discrecionales.

    Funcionalidad:
        Es el caso que separa el modelo nuevo del anterior: las piezas A rinden
        menos por dolar que las B, asi que una mochila que solo mirara el
        beneficio neto las dejaria fuera.
    """
    return pd.DataFrame(
        [
            recommendation("CRIT-1", DECISION_BUY, 900.0, 400.0, criticality="A"),
            recommendation("CRIT-2", DECISION_BUY, 800.0, 300.0, criticality="A"),
            recommendation("FLEX-1", DECISION_BUY, 400.0, 900.0, criticality="B"),
            recommendation("FLEX-2", DECISION_BUY, 400.0, 850.0, criticality="B"),
        ],
        columns=COLUMNS,
    )


def test_a_critical_part_is_funded_even_when_it_yields_less_per_dollar():
    """La continuidad de produccion no compite: se financia primero."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=1000.0)
    decisions = dict(zip(result.sku_id, result.decision, strict=False))

    assert decisions["CRIT-1"] == DECISION_BUY
    assert decisions["CRIT-2"] == DECISION_BUY


def test_the_discretionary_purchases_yield_to_the_critical_ones():
    """Lo que rinde mas por dolar cede cuando lo otro para una linea."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=1000.0)
    decisions = dict(zip(result.sku_id, result.decision, strict=False))

    assert decisions["FLEX-1"] == DECISION_DEFERRED
    assert decisions["FLEX-2"] == DECISION_DEFERRED


def test_the_authorised_overrun_is_what_makes_the_critical_purchase_fit():
    """1.700 USD de compras criticas contra 1.000 de presupuesto nominal."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=1000.0)
    bought = result[result.decision == DECISION_BUY]

    assert bought.total_cost_usd.sum() == 1700.0
    assert budget_allocation_summary(result, 1000.0, 1000.0)["overrun_usd"] == 700.0


def test_a_critical_purchase_that_does_not_fit_is_escalated_not_deferred():
    """Escalar y aplazar son decisiones de personas distintas."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=0.0)
    escalated = result[result.decision == DECISION_ESCALATE]

    assert len(escalated) == 1
    assert REASON_ESCALATE in escalated.iloc[0].reason
    assert escalated.iloc[0].needs_review == 1


def test_the_escalated_critical_part_is_the_one_that_prevents_less_stockout():
    """Cuando no caben todas, se cubre primero la que mas quiebre evita."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=0.0)
    decisions = dict(zip(result.sku_id, result.decision, strict=False))

    assert decisions["CRIT-1"] == DECISION_BUY
    assert decisions["CRIT-2"] == DECISION_ESCALATE


def test_the_summary_reports_the_service_level_reached_by_class():
    """La politica declarada y la conseguida se publican juntas."""
    result = apply_budget(critical_table(), 1000.0, overrun_max=1000.0)
    service = {
        level["criticality"]: level
        for level in budget_allocation_summary(result, 1000.0, 1000.0)["service"]
    }

    assert service["A"]["funded"] == 2
    assert service["A"]["achieved"] == 1.0
    assert service["A"]["met"] is True
    assert service["B"]["achieved"] == 0.0
    assert service["B"]["met"] is False


def test_continuity_is_reported_as_protected_when_nothing_is_escalated():
    """Es la cifra que encabeza la pantalla del comprador."""
    covered = budget_allocation_summary(
        apply_budget(critical_table(), 1000.0, overrun_max=1000.0), 1000.0, 1000.0
    )
    exposed = budget_allocation_summary(
        apply_budget(critical_table(), 1000.0, overrun_max=0.0), 1000.0, 0.0
    )

    assert covered["continuity_protected"] is True
    assert exposed["continuity_protected"] is False


def test_the_service_floor_is_respected_when_the_money_allows_it():
    """Con solo piezas B, el piso del 80 % obliga a financiar cuatro de cinco."""
    candidates = [candidate(f"b{index}", 100.0, 500.0 - index, "B") for index in range(5)]
    chosen = allocate_budget(candidates, 450.0, overrun_max=0.0)

    assert len(chosen["approved"]) == 4


def test_the_service_floor_gives_way_before_declaring_the_model_infeasible():
    """Si ni el piso cabe, se suelta y se informa, no se falla en silencio."""
    candidates = [candidate(f"b{index}", 100.0, 500.0 - index, "B") for index in range(5)]
    chosen = allocate_budget(candidates, 150.0, overrun_max=0.0)

    assert len(chosen["approved"]) == 1
    assert chosen["escalated"] == set()
