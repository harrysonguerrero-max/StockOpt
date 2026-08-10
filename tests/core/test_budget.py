"""Tests del reparto del presupuesto entre las compras de una corrida."""

import pandas as pd
import pytest

from app.core.optimization import (
    COLUMNS,
    DECISION_BUY,
    DECISION_DEFERRED,
    DECISION_HOLD,
    DECISION_REVIEW,
    REASON_OVER_BUDGET,
    allocate_budget,
    apply_budget,
)


def candidate(key, cost, benefit):
    """Arma un candidato a compra para la mochila.

    Entrada:
        key: identificador de la combinacion pieza-ciudad.
        cost: costo total de la orden.
        benefit: beneficio neto de hacerla.

    Salida:
        Diccionario con la forma que espera allocate_budget.

    Funcionalidad:
        Evita repetir la construccion en cada caso de prueba.
    """
    return {"key": key, "cost": cost, "benefit": benefit}


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

    assert chosen == {"b", "c"}


def test_without_a_budget_every_purchase_is_approved():
    candidates = [candidate("a", 1000.0, 0.9), candidate("b", 2000.0, 0.5)]

    assert allocate_budget(candidates, None) == {"a", "b"}


def test_a_budget_that_covers_everything_approves_everything():
    candidates = [candidate("a", 100.0, 0.9), candidate("b", 200.0, 0.5)]

    assert allocate_budget(candidates, 500.0) == {"a", "b"}


def test_the_knapsack_beats_taking_the_most_valuable_first():
    candidates = [
        candidate("cara", 100.0, 90.0),
        candidate("barata_1", 50.0, 60.0),
        candidate("barata_2", 50.0, 60.0),
    ]
    chosen = allocate_budget(candidates, 100.0)

    assert chosen == {"barata_1", "barata_2"}


def test_a_purchase_bigger_than_the_whole_budget_is_left_out():
    candidates = [candidate("gigante", 5000.0, 0.99), candidate("normal", 80.0, 0.10)]

    assert allocate_budget(candidates, 100.0) == {"normal"}


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
    assert "presupuesto" in deferred.reason
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
