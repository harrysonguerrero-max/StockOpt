"""Tests del explorador de tablas del dataset."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import data_views
from app.services.dictionary import TABLES, describe_table, render_markdown


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_only_catalogued_tables_are_readable():
    assert data_views.is_known_table("suppliers.csv")
    assert data_views.is_known_table("quality/demand_outliers.csv")
    assert not data_views.is_known_table("../../.env")
    assert not data_views.is_known_table("app/core/config.py")


def test_a_name_outside_the_catalogue_is_rejected_before_touching_disk(client):
    for name in ["../../.env", "..%2F..%2Fsecrets", "app/main.py", "inventado.csv"]:
        assert client.get(f"/api/v1/data/tables/{name}").status_code == 404
        assert client.get(f"/api/v1/data/files/{name}").status_code == 404


def test_every_catalogued_table_documents_its_columns():
    for name in TABLES:
        described = describe_table(name)
        assert described["title"]
        assert described["summary"]
        assert described["columns"]
        for column in described["columns"]:
            assert column["name"]
            assert column["description"]


def test_the_catalogue_matches_the_columns_actually_on_disk():
    for name in TABLES:
        path = data_views.table_path(name)
        if not path.exists():
            continue
        documented = {column["name"] for column in describe_table(name)["columns"]}
        actual = set(data_views.load_table(name).columns)
        assert actual == documented, f"{name}: el diccionario no coincide con el CSV"


def test_the_document_is_rendered_from_the_catalogue():
    document = render_markdown()

    assert "# Diccionario de datos - MVP SupplyOpt" in document
    for name in TABLES:
        assert f"## {name}" in document


def test_null_and_infinite_values_become_none():
    assert data_views.json_safe(np.nan) is None
    assert data_views.json_safe(float("inf")) is None
    assert data_views.json_safe(None) is None
    assert data_views.json_safe(np.int64(7)) == 7
    assert data_views.json_safe("SUP-01") == "SUP-01"


def test_a_record_with_empty_fields_can_be_serialised():
    record = {"supplier_id": np.nan, "qty": np.int64(3), "name": "Alpha"}

    assert data_views.json_safe_record(record) == {
        "supplier_id": None, "qty": 3, "name": "Alpha",
    }
    assert data_views.json_safe_record(None) is None


def test_the_catalogue_reports_the_size_of_each_table(client):
    payload = client.get("/api/v1/data/tables").json()
    by_name = {table["name"]: table for table in payload["tables"]}

    assert set(by_name) == set(TABLES)
    assert by_name["cities.csv"]["row_count"] == 2
    assert by_name["demand_history.csv"]["row_count"] == 2880


def test_rows_travel_as_lists_aligned_with_the_columns(client):
    payload = client.get("/api/v1/data/tables/cities.csv").json()

    assert [column["name"] for column in payload["columns"]] == [
        "city_id", "city_name", "country", "warehouse_id",
    ]
    assert payload["row_count"] == len(payload["rows"]) == 2
    for row in payload["rows"]:
        assert len(row) == len(payload["columns"])


def test_a_table_in_a_subfolder_is_served(client):
    response = client.get("/api/v1/data/tables/quality/demand_outliers.csv")

    assert response.status_code == 200
    assert response.json()["title"] == "Meses de consumo atipico"
