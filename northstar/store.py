"""Storage layer: SingleStore when SINGLESTORE_URL is set, otherwise local SQLite.

SingleStore holds three things for North Star:
  * events      - a mirror of every product event (the agent runs its stats here, in real time)
  * experiments - the experiment registry (spec, status, killed variants, final result)
  * audit       - the decision log: every step, which model made it, what it cost
SQL is kept deliberately portable (no autoincrement, no vendor functions) so both backends work.
"""
import json
import sqlite3
import threading
import time
import uuid

from . import config

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS events (
        id VARCHAR(40) PRIMARY KEY, ts DOUBLE, user_id VARCHAR(64), experiment_id VARCHAR(40),
        variant VARCHAR(64), device VARCHAR(16), event VARCHAR(32), value DOUBLE)""",
    """CREATE TABLE IF NOT EXISTS experiments (
        id VARCHAR(40) PRIMARY KEY, name VARCHAR(200), status VARCHAR(20), created_at DOUBLE,
        spec_json TEXT, killed_json TEXT, result_json TEXT, statsig_ref VARCHAR(200))""",
    """CREATE TABLE IF NOT EXISTS audit (
        id VARCHAR(40) PRIMARY KEY, ts DOUBLE, step VARCHAR(32), actor VARCHAR(64),
        model VARCHAR(64), summary TEXT, detail_json TEXT, cost_usd DOUBLE, tokens INT)""",
    """CREATE TABLE IF NOT EXISTS memory (
        id VARCHAR(40) PRIMARY KEY, ts DOUBLE, text TEXT)""",
]


class Store:
    def __init__(self):
        self._lock = threading.Lock()
        if config.SINGLESTORE_URL:
            import singlestoredb as s2  # optional dependency

            self.conn = s2.connect(config.SINGLESTORE_URL)
            self.ph = "%s"
            self.backend = "singlestore"
        else:
            self.conn = sqlite3.connect(config.SQLITE_PATH, check_same_thread=False)
            self.ph = "?"
            self.backend = "sqlite"
        for stmt in SCHEMA:
            self._exec(stmt)

    # -- low level -------------------------------------------------------------
    def _sql(self, sql: str) -> str:
        return sql.replace("?", self.ph)

    def _exec(self, sql: str, params=()):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), params)
            self.conn.commit()

    def _many(self, sql: str, rows):
        with self._lock:
            cur = self.conn.cursor()
            cur.executemany(self._sql(sql), rows)
            self.conn.commit()

    def query(self, sql: str, params=()) -> list[dict]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute(self._sql(sql), params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def reset(self):
        for t in ("events", "experiments", "audit", "memory"):
            self._exec(f"DELETE FROM {t}")

    # -- events ----------------------------------------------------------------
    def insert_events(self, events: list[dict]):
        rows = [
            (uuid.uuid4().hex, e["ts"], e["user_id"], e.get("experiment_id") or "",
             e.get("variant") or "", e["device"], e["event"], e.get("value", 0.0))
            for e in events
        ]
        self._many(
            "INSERT INTO events (id, ts, user_id, experiment_id, variant, device, event, value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    def funnel(self, experiment_id: str = "", device: str | None = None) -> dict:
        """Distinct users per (variant, event) plus revenue sums, for one experiment ('' = baseline)."""
        sql = ("SELECT variant, event, COUNT(DISTINCT user_id) AS users, SUM(value) AS total, "
               "SUM(value * value) AS total_sq FROM events WHERE experiment_id = ?")
        params: list = [experiment_id]
        if device:
            sql += " AND device = ?"
            params.append(device)
        sql += " GROUP BY variant, event"
        out: dict = {}
        for r in self.query(sql, params):
            v = out.setdefault(r["variant"] or "control", {})
            v[r["event"]] = {"users": int(r["users"]), "total": float(r["total"] or 0),
                             "total_sq": float(r["total_sq"] or 0)}
        return out

    # -- experiments -------------------------------------------------------------
    def create_experiment(self, name: str, spec: dict) -> str:
        exp_id = "exp_" + uuid.uuid4().hex[:8]
        self._exec(
            "INSERT INTO experiments (id, name, status, created_at, spec_json, killed_json, result_json, statsig_ref) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (exp_id, name, "pending_approval", time.time(), json.dumps(spec), "[]", "", ""))
        return exp_id

    def update_experiment(self, exp_id: str, **fields):
        mapping = {"status": "status", "killed": "killed_json", "result": "result_json",
                   "statsig_ref": "statsig_ref", "spec": "spec_json"}
        for k, v in fields.items():
            col = mapping[k]
            val = json.dumps(v) if col.endswith("_json") else v
            self._exec(f"UPDATE experiments SET {col} = ? WHERE id = ?", (val, exp_id))

    def get_experiment(self, exp_id: str) -> dict | None:
        rows = self.query("SELECT * FROM experiments WHERE id = ?", (exp_id,))
        return self._hydrate(rows[0]) if rows else None

    def list_experiments(self) -> list[dict]:
        return [self._hydrate(r) for r in self.query("SELECT * FROM experiments ORDER BY created_at DESC")]

    @staticmethod
    def _hydrate(r: dict) -> dict:
        r["spec"] = json.loads(r.pop("spec_json") or "{}")
        r["killed"] = json.loads(r.pop("killed_json") or "[]")
        res = r.pop("result_json")
        r["result"] = json.loads(res) if res else None
        return r

    # -- audit -----------------------------------------------------------------
    def audit(self, step: str, summary: str, detail: dict | None = None, actor: str = "agent",
              model: str = "", cost_usd: float = 0.0, tokens: int = 0):
        self._exec(
            "INSERT INTO audit (id, ts, step, actor, model, summary, detail_json, cost_usd, tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, time.time(), step, actor, model, summary,
             json.dumps(detail or {}, default=str), cost_usd, tokens))

    def audit_log(self, limit: int = 200) -> list[dict]:
        rows = self.query("SELECT * FROM audit ORDER BY ts DESC LIMIT ?", (limit,))
        for r in rows:
            r["detail"] = json.loads(r.pop("detail_json") or "{}")
        return rows

    # -- memory (local fallback for Cognee) ---------------------------------------
    def remember(self, text: str):
        self._exec("INSERT INTO memory (id, ts, text) VALUES (?, ?, ?)", (uuid.uuid4().hex, time.time(), text))

    def memories(self, limit: int = 20) -> list[str]:
        return [r["text"] for r in self.query("SELECT text FROM memory ORDER BY ts DESC LIMIT ?", (limit,))]


store = Store()
