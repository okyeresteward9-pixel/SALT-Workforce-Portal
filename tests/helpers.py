"""Tiny fakes so blueprint/decorator tests run without PostgreSQL."""
from pathlib import Path

from flask import Flask

ROOT = Path(__file__).resolve().parent.parent


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.last = ""
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.last = " ".join(sql.split())
        self.db.executed.append((self.last, params))
        for needle, row, rowcount in self.db.rules:
            if needle in self.last:
                self._row, self.rowcount = row, rowcount
                return
        self._row, self.rowcount = None, 0

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [] if self._row is None else [self._row]


class FakeDB:
    """rules: list of (sql_substring, row_or_None, rowcount)."""

    def __init__(self, rules=()):
        self.rules = list(rules)
        self.executed = []
        self.committed = False

    def __call__(self):  # acts as get_db()
        return self

    def cursor(self, cursor_factory=None):
        return FakeCursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def make_app(*blueprints):
    app = Flask(__name__, root_path=str(ROOT))
    app.secret_key = "unit-test-key"
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    for bp in blueprints:
        app.register_blueprint(bp)

    @app.route("/dashboard")
    def dashboard():  # target of the login redirect
        return "dashboard"

    return app


def set_session(client, **values):
    with client.session_transaction() as s:
        s.update(values)
