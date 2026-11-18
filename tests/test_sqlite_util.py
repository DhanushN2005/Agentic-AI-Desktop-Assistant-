"""Shared SQLite connections: correctness under threads and drop-in semantics."""
import sqlite3
import threading

from utils.sqlite_util import close_all, fast_connect


def _db(tmp_path):
    path = str(tmp_path / "t.db")
    conn = fast_connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    return path


def test_same_path_shares_one_connection_and_close_is_a_noop(tmp_path):
    path = _db(tmp_path)
    a, b = fast_connect(path), fast_connect(path)
    assert a._s is b._s
    a.execute("INSERT INTO t VALUES ('x', '1')")
    a.commit()
    a.close()  # must not close the shared connection
    assert b.execute("SELECT v FROM t WHERE k='x'").fetchone() == ("1",)


def test_with_block_commits_on_success_and_rolls_back_on_error(tmp_path):
    path = _db(tmp_path)
    with fast_connect(path) as conn:
        conn.execute("INSERT INTO t VALUES ('ok', '1')")
    try:
        with fast_connect(path) as conn:
            conn.execute("INSERT INTO t VALUES ('bad', '1')")
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    rows = dict(fast_connect(path).execute("SELECT k, v FROM t").fetchall())
    assert rows == {"ok": "1"}


def test_cursor_style_usage_and_rowcount(tmp_path):
    path = _db(tmp_path)
    c = fast_connect(path).cursor()
    c.execute("INSERT INTO t VALUES ('a', '1')")
    c.execute("INSERT INTO t VALUES ('b', '2')")
    c.execute("SELECT k FROM t ORDER BY k")
    assert [r[0] for r in c.fetchall()] == ["a", "b"]
    res = fast_connect(path).execute("DELETE FROM t WHERE k='a'")
    assert res.rowcount == 1


def test_many_threads_writing_do_not_corrupt_or_lose_rows(tmp_path):
    path = _db(tmp_path)
    errors = []

    def worker(n):
        try:
            conn = fast_connect(path)
            for i in range(50):
                conn.execute("INSERT OR REPLACE INTO t VALUES (?, ?)", (f"{n}-{i}", "v"))
                conn.commit()
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert fast_connect(path).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 400


def test_data_survives_closing_all_connections(tmp_path):
    path = _db(tmp_path)
    fast_connect(path).execute("INSERT INTO t VALUES ('keep', 'me')")
    fast_connect(path).commit()
    close_all()
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT v FROM t WHERE k='keep'").fetchone() == ("me",)
