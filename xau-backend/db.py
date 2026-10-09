from sqlalchemy import create_engine, text

eng = None


def init(url, schema_path="schema.sql"):
    global eng
    eng = create_engine(url, pool_pre_ping=True)
    with eng.begin() as c:
        for s in open(schema_path).read().split(";"):
            if s.strip():
                c.execute(text(s))


def q(sql, **p):
    with eng.connect() as c:
        return [dict(r._mapping) for r in c.execute(text(sql), p)]


def x(sql, **p):
    with eng.begin() as c:
        c.execute(text(sql), p)


def insert(table, d):  # keys are internal constants, values are bound parameters
    cols = ",".join(d)
    x(f"INSERT INTO {table} ({cols}) VALUES ({','.join(':' + k for k in d)})", **d)


def update_trade(tid, d):
    x(f"UPDATE trades SET {','.join(f'{k}=:{k}' for k in d)} WHERE id=:_id", _id=tid, **d)


def open_trade():
    r = q("SELECT * FROM trades WHERE status='OPEN' LIMIT 1")
    return r[0] if r else None


def today_stats(day_start_ms):
    n = q("SELECT COUNT(*) AS n FROM trades WHERE opened_at_ms>=:s", s=day_start_ms)[0]["n"]
    p = q("SELECT COALESCE(SUM(pnl_r),0) AS p FROM trades WHERE closed_at_ms>=:s", s=day_start_ms)[0]["p"]
    return n, float(p)


def get_setting(k, default):
    r = q("SELECT v FROM settings WHERE k=:k", k=k)
    return r[0]["v"] if r else default


def set_setting(k, v):
    x("DELETE FROM settings WHERE k=:k", k=k)
    x("INSERT INTO settings (k,v) VALUES (:k,:v)", k=k, v=str(v))
