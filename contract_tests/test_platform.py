"""Meaningful platform limits against real PostgreSQL."""
import concurrent.futures
import multiprocessing
import os
from pathlib import Path
import pytest
from sqlalchemy import select,text
from fastapi import HTTPException
from app.betrieb import belasten,pdf_slot
from app.modelle import BetriebsLimit
from tests.conftest import anmelden

def test_two_independent_clients_share_persistent_login_failures(fabrik,schulen):
    from fastapi.testclient import TestClient
    from app.main import erstelle_app
    a,_=schulen
    with TestClient(erstelle_app(fabrik)) as one,TestClient(erstelle_app(fabrik)) as two:
        for i in range(10):
            assert anmelden(one if i%2 else two,a.email,"wrong-password").status_code==401
        assert anmelden(two,a.email).status_code==429
    with TestClient(erstelle_app(fabrik)) as restarted:
        assert anmelden(restarted,a.email).status_code==429

def test_parallel_reservations_do_not_overbook_and_store_only_hashes(fabrik):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(lambda _:belasten(fabrik,["synthetic-private-key"],3,60),range(8)))
    assert results.count(True)==3
    with fabrik.intern_kontext() as s:
        rows=s.execute(select(BetriebsLimit)).scalars().all()
        assert len(rows)==1 and len(rows[0].schluessel)==64 and rows[0].anzahl==3

def test_expired_limit_is_removed(fabrik):
    assert belasten(fabrik,["expired"],1,-1)
    assert belasten(fabrik,["expired"],1,60)

def _competing_export(queue):
    try:
        with pdf_slot():queue.put("accepted")
    except HTTPException as error:queue.put(error.status_code)

def test_pdf_slot_shared_between_processes_and_recovers_after_release():
    context=multiprocessing.get_context("spawn");queue=context.Queue()
    with pdf_slot():
        child=context.Process(target=_competing_export,args=(queue,));child.start();child.join(10)
        assert child.exitcode==0 and queue.get(timeout=1)==503
    with pdf_slot():pass

def test_chunked_body_limit_without_content_length(client):
    response=client.post("/api/p/synthetic-token-which-is-long/events",
        content=iter([b"x"*1_100_000,b"x"*1_100_000]),headers={"Content-Type":"application/json"})
    assert response.status_code==413

def test_migration_exclusive_and_preserves_ids(engine,schulen):
    from alembic import command
    from alembic.config import Config
    from app.migrate import LOCK, SCHEMA_REVISION
    from tests.conftest import PROJEKT
    with engine.begin() as held:
        held.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":LOCK})
        with engine.connect() as competing:
            assert competing.execute(text("SELECT pg_try_advisory_xact_lock(:key)"),{"key":LOCK}).scalar_one() is False
    with engine.begin() as connection:
        config=Config(str(PROJEKT/"alembic.ini"));config.attributes["connection"]=connection
        command.upgrade(config,"head")
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()==SCHEMA_REVISION
        assert connection.execute(text("SELECT id FROM schule ORDER BY id")).scalars().all()==[schulen[0].schule,schulen[1].schule]
