"""Test setup.

SAFETY: the tests create and delete users, so they only ever run against a database
named in TEST_DATABASE_URL - never your normal development or production database.
Locally:  createdb salt_test   then   set TEST_DATABASE_URL=postgresql://salt_user:PASSWORD@localhost/salt_test
"""
import itertools
import os

import pytest

_ip_counter = itertools.count(1)


@pytest.fixture(scope="session")
def app():
    url = os.environ.get("TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set - skipping tests that need the app/database.")
    if url.rsplit("/", 1)[-1].split("?")[0] == "salt_portal":
        pytest.exit("TEST_DATABASE_URL points at the real 'salt_portal' database. Use a separate test database.")

    # Must be set BEFORE app.py is imported (it initialises the database on import).
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("APP_ENV", "development")
    os.environ.setdefault("SECRET_KEY", "test-secret-key")

    from app import app as flask_app

    flask_app.config.update(TESTING=True)
    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def fresh_ip():
    """A unique client IP per test, so login-throttle state never leaks between tests."""
    n = next(_ip_counter)
    return {"X-Forwarded-For": f"10.99.{n // 250}.{n % 250 + 1}"}


PASSWORD = "Test-Passw0rd!"


def _create_user(email, role):
    from werkzeug.security import generate_password_hash
    from database import get_db

    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM employees WHERE email=%s", (email,))
        c.execute(
            "INSERT INTO employees (name, email, password, role, theme) VALUES (%s,%s,%s,%s,%s)",
            (f"Test {role}", email, generate_password_hash(PASSWORD), role, "light"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def users(app):
    accounts = {
        "admin": "pytest-admin@example.test",
        "employee": "pytest-employee@example.test",
    }
    _create_user(accounts["admin"], "admin")
    _create_user(accounts["employee"], "employee")
    yield accounts

    from database import get_db
    conn = get_db()
    try:
        conn.cursor().execute("DELETE FROM employees WHERE email = ANY(%s)", (list(accounts.values()),))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()


def login(client, email, headers):
    return client.post("/login", data={"email": email, "password": PASSWORD}, headers=headers)
