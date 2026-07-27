"""
Data-access layer: a uniform read_sql / execute / write_df interface backed
by either a local SQLite file or a Turso (libSQL) database, so the rest of
the app doesn't need two code paths.

Turso is reached over its plain HTTP "pipeline" API (Hrana-over-HTTP)
rather than its native Python client. That's a deliberate choice, not a
shortcut: the native client (`libsql-experimental`) ships no prebuilt
wheels for any platform -- installing it means compiling a Rust extension
locally, which fails without a full Rust+MSVC toolchain (confirmed while
building this), and would likely fail the same way in Streamlit Community
Cloud's build step. The HTTP API needs nothing but `requests`, which is
already a dependency, and behaves identically on every platform.
"""

import sqlite3

import pandas as pd
import requests


class SqliteStore:
    """Backed by a local SQLite file. Used when no Turso credentials are configured."""

    def __init__(self, db_path):
        self.db_path = db_path

    def read_sql(self, sql, params=None, parse_dates=None):
        conn = sqlite3.connect(self.db_path)
        try:
            return pd.read_sql(sql, conn, params=params, parse_dates=parse_dates)
        finally:
            conn.close()

    def execute(self, sql, params=None):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(sql, params or [])
            conn.commit()
        finally:
            conn.close()

    def execute_script(self, sql_statements):
        conn = sqlite3.connect(self.db_path)
        try:
            for stmt in sql_statements:
                if stmt.strip():
                    conn.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    def write_df(self, table, df, mode="append"):
        conn = sqlite3.connect(self.db_path)
        try:
            df.to_sql(table, conn, if_exists=mode, index=False)
            conn.commit()
        finally:
            conn.close()

    def table_exists(self, table):
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def row_count(self, table):
        if not self.table_exists(table):
            return 0
        conn = sqlite3.connect(self.db_path)
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            conn.close()


class TursoStore:
    """
    Backed by a Turso (libSQL) database over its HTTP pipeline API. Values
    travel as {"type": ..., "value": ...} objects -- integers as strings
    (Turso's own convention, to dodge JS float-precision limits on 64-bit
    ints), floats as raw JSON numbers, verified empirically against a live
    database before this was written.
    """

    def __init__(self, url, token):
        https_url = url.replace("libsql://", "https://", 1) if url.startswith("libsql://") else url
        self.endpoint = https_url.rstrip("/") + "/v2/pipeline"
        self.headers = {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _encode(v):
        if v is None:
            return {"type": "null"}
        try:
            if pd.isna(v):
                return {"type": "null"}
        except (TypeError, ValueError):
            pass
        if isinstance(v, bool):
            return {"type": "integer", "value": str(int(v))}
        type_name = type(v).__name__
        if isinstance(v, int) or "int" in type_name:
            return {"type": "integer", "value": str(int(v))}
        if isinstance(v, float) or "float" in type_name:
            return {"type": "float", "value": float(v)}
        return {"type": "text", "value": str(v)}

    @staticmethod
    def _decode(cell):
        t, v = cell.get("type"), cell.get("value")
        if t == "null" or v is None:
            return None
        if t == "integer":
            return int(v)
        if t == "float":
            return float(v)
        return v

    def _pipeline(self, stmt_requests):
        body = {"requests": stmt_requests + [{"type": "close"}]}
        resp = requests.post(self.endpoint, json=body, headers=self.headers, timeout=90)
        if not resp.ok:
            # Streamlit Cloud redacts exception messages on its public error
            # page, so a bare raise_for_status() shows nothing diagnosable.
            # Surface the status/reason/body here (never the token) so a
            # misconfigured secret is debuggable without needing dashboard
            # log access.
            raise RuntimeError(
                f"Turso HTTP {resp.status_code} {resp.reason} calling {self.endpoint.split('://', 1)[-1].split('/')[0]} "
                f"-- response: {resp.text[:300]}"
            )
        data = resp.json()
        out = []
        for r in data["results"][: len(stmt_requests)]:
            if r["type"] == "error":
                raise RuntimeError(f"Turso error: {r.get('error', {}).get('message', r)}")
            out.append(r["response"])
        return out

    def execute(self, sql, params=None):
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [self._encode(p) for p in params]
        self._pipeline([{"type": "execute", "stmt": stmt}])

    def execute_script(self, sql_statements, batch_size=20):
        reqs = [{"type": "execute", "stmt": {"sql": s}} for s in sql_statements if s.strip()]
        for i in range(0, len(reqs), batch_size):
            self._pipeline(reqs[i:i + batch_size])

    def read_sql(self, sql, params=None, parse_dates=None):
        stmt = {"sql": sql}
        if params:
            stmt["args"] = [self._encode(p) for p in params]
        result = self._pipeline([{"type": "execute", "stmt": stmt}])[0]["result"]
        cols = [c["name"] for c in result["cols"]]
        rows = [[self._decode(cell) for cell in row] for row in result["rows"]]
        df = pd.DataFrame(rows, columns=cols)
        if parse_dates:
            for c in parse_dates:
                if c in df.columns:
                    df[c] = pd.to_datetime(df[c])
        return df

    def write_df(self, table, df, mode="append", rows_per_stmt=1000, stmts_per_call=5):
        """
        Bulk-loads a DataFrame as batched multi-row INSERTs. Empirically
        verified up to 1000 rows x 20 columns (20,000 placeholders) per
        statement in well under a second -- comfortably inside Turso's
        limits, so a 75K-row table only takes ~15-20 HTTP round trips.
        """
        if mode == "replace":
            self.execute(f"DELETE FROM {table}")
        if df.empty:
            return
        cols = list(df.columns)
        col_list = ", ".join(cols)
        one_row = "(" + ", ".join(["?"] * len(cols)) + ")"
        records = list(df.itertuples(index=False, name=None))

        i = 0
        while i < len(records):
            batch_reqs = []
            for _ in range(stmts_per_call):
                chunk = records[i:i + rows_per_stmt]
                if not chunk:
                    break
                sql = f"INSERT INTO {table} ({col_list}) VALUES {', '.join([one_row] * len(chunk))}"
                args = [self._encode(v) for row in chunk for v in row]
                batch_reqs.append({"type": "execute", "stmt": {"sql": sql, "args": args}})
                i += len(chunk)
            if batch_reqs:
                self._pipeline(batch_reqs)

    def table_exists(self, table):
        df = self.read_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", params=[table]
        )
        return not df.empty

    def row_count(self, table):
        if not self.table_exists(table):
            return 0
        df = self.read_sql(f"SELECT COUNT(*) AS n FROM {table}")
        return int(df["n"].iloc[0])


def get_store(url=None, token=None, sqlite_path=None):
    """Returns a TursoStore if credentials are given, else a SqliteStore."""
    if url and token:
        return TursoStore(url, token)
    return SqliteStore(sqlite_path)
