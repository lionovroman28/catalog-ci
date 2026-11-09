"""Behavior tests for the educational catalog using a temporary SQLite database."""
from __future__ import annotations

import hashlib
import socket
import sqlite3
from pathlib import Path

import pytest

from app import create_app


PRODUCTS = [
    ("B001", "Ромашковый день", "Ромашки; декоративная зелень", 1200, 0),
    ("B002", "Летний вечер", "Лаванда; эустома", 2500, 2),
    ("B007", "Большое спасибо", "Розы и эустомы", 4950, 4),
    ("B010", "Утренний свет", "Тюльпаны", 1800, 1),
]


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail loudly if a test tries to open a network connection."""

    def deny(*args, **kwargs):
        raise AssertionError("Network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)


@pytest.fixture()
def database(tmp_path: Path) -> Path:
    path = tmp_path / "catalog-test.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE products ("
            "sku TEXT PRIMARY KEY, "
            "name TEXT NOT NULL, "
            "composition TEXT NOT NULL, "
            "price INTEGER NOT NULL CHECK(price > 0), "
            "stock INTEGER NOT NULL CHECK(stock >= 0))"
        )
        db.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", PRODUCTS)
    return path


@pytest.fixture()
def app(database: Path):
    application = create_app(database=database, title="Тестовый каталог")
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def text(response) -> str:
    return response.get_data(as_text=True)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_b007_price_and_positive_stock_label(client):
    response = client.get("/?q=B007")
    html = text(response)

    assert response.status_code == 200
    assert "B007" in html
    assert "4 950 руб." in html
    assert "В наличии: 4 шт." in html
    assert "Нет в наличии" not in html


def test_zero_stock_uses_clean_absence_label(client):
    response = client.get("/?q=B001")
    html = text(response)

    assert response.status_code == 200
    assert "B001" in html
    assert "Нет в наличии" in html
    assert "В наличии: 0 шт." not in html


@pytest.mark.parametrize("query", ["большое", "БОЛЬШОЕ", "Большое"])
def test_search_by_name_is_case_insensitive(client, query):
    html = text(client.get("/", query_string={"q": query}))

    assert "B007" in html
    assert "B002" not in html


def test_search_by_sku_is_case_insensitive(client):
    html = text(client.get("/", query_string={"q": "b007"}))

    assert "B007" in html
    assert "4 950 руб." in html


def test_available_filter_excludes_zero_stock(client):
    available = text(client.get("/?available=1"))
    assert "B007" in available
    assert "B002" in available
    assert "B001" not in available

    all_products = text(client.get("/?available=0"))
    assert "B001" in all_products


def test_about_page_reports_database_total(client):
    response = client.get("/about")
    html = text(response)

    assert response.status_code == 200
    assert "Как работает каталог" in html
    assert "Сейчас в SQLite 4 товаров." in html


@pytest.mark.parametrize(
    "url",
    [
        "/?available=2",
        "/?q=a&q=b",
        "/?extra=1",
        "/?page=0",
        "/?page=abc",
        "/?page=%D9%A1",
        "/?q=" + "x" * 81,
    ],
)
def test_invalid_parameters_return_400(client, url):
    response = client.get(url)

    assert response.status_code == 400
    assert "Неизвестный режим каталога" in text(response)


def test_page_beyond_last_returns_404(client):
    response = client.get("/?page=99")

    assert response.status_code == 404
    assert "Такой страницы нет" in text(response)


def test_no_routes_expose_database_or_env_files(app, client):
    rules = {rule.rule.lower() for rule in app.url_map.iter_rules()}
    assert not any("download" in rule for rule in rules)
    assert not any(rule.endswith(".db") or rule.endswith(".env") for rule in rules)

    for url in (
        "/data/catalog.db",
        "/catalog.db",
        "/.env",
        "/.env.local",
        "/.git/config",
        "/static/../data/catalog.db",
        "/static/%2e%2e/data/catalog.db",
    ):
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 404, url


def test_database_file_is_unchanged_by_requests(database, client):
    before = digest(database)

    for url in (
        "/",
        "/?q=B007",
        "/?available=1",
        "/about",
        "/?page=99",
        "/?available=2",
        "/data/catalog.db",
        "/.env",
    ):
        client.get(url)

    assert digest(database) == before
    assert not database.with_name(database.name + "-wal").exists()
    assert not database.with_name(database.name + "-shm").exists()


def test_security_headers_are_present(client):
    response = client.get("/")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"
