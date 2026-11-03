"""Shared PostgreSQL limits and process-safe local export slot."""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import wraps
import fcntl
import hashlib
import os

from fastapi import HTTPException
from sqlalchemy import delete, func, select, text

from app.modelle import BetriebsLimit

LIMIT_LOCK = 762431801

def belasten(fabrik, keys, maximum, seconds):
    """Reserve before expensive work. Fixed windows, shared across workers/restarts."""
    keys=sorted({hashlib.sha256(k.encode()).hexdigest() for k in keys})
    with fabrik.intern_kontext() as session:
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":LIMIT_LOCK})
        now=datetime.now(UTC)
        session.execute(delete(BetriebsLimit).where(BetriebsLimit.bis<=now))
        rows={key:session.get(BetriebsLimit,key) for key in keys}
        if any(row is not None and row.anzahl>=maximum for row in rows.values()):
            return False
        count=session.execute(select(func.count()).select_from(BetriebsLimit)).scalar_one()
        if count+sum(row is None for row in rows.values())>10000:
            return False
        for key,row in rows.items():
            if row is None:
                session.add(BetriebsLimit(schluessel=key,anzahl=1,bis=now+timedelta(seconds=seconds)))
            else:
                row.anzahl+=1
        return True

def entlasten(fabrik, keys):
    keys=sorted({hashlib.sha256(k.encode()).hexdigest() for k in keys})
    with fabrik.intern_kontext() as session:
        session.execute(text("SET LOCAL lock_timeout = '2s'"))
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":LIMIT_LOCK})
        for key in keys:
            row=session.get(BetriebsLimit,key)
            if row is not None:
                row.anzahl=max(0,row.anzahl-1)

class PostenBremse:
    def __init__(self,fabrik):self.fabrik=fabrik
    def erlaubt(self,key):return belasten(self.fabrik,["posten:"+key],120,60)

@contextmanager
def pdf_slot():
    descriptor=os.open("/tmp/fahrrad-pdf.lock",os.O_CREAT|os.O_RDWR,0o600)
    try:
        try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(503,"PDF-Erzeugung belegt",headers={"Retry-After":"10"}) from None
        yield
    finally:
        os.close(descriptor)

def begrenzter_export(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        with pdf_slot():return function(*args,**kwargs)
    return wrapped

class BodyLimit:
    def __init__(self,app,maximum=2_100_000):self.app,self.maximum=app,maximum
    async def __call__(self,scope,receive,send):
        if scope["type"]!="http" or scope["method"] not in ("POST","PUT","PATCH"):
            return await self.app(scope,receive,send)
        chunks=[];size=0
        while True:
            message=await receive()
            if message["type"]=="http.disconnect":return
            size+=len(message.get("body",b""))
            if size>self.maximum:
                from starlette.responses import JSONResponse
                return await JSONResponse({"fehler":"Anfrage zu groß"},413)(scope,receive,send)
            chunks.append(message)
            if not message.get("more_body",False):break
        async def replay():
            if chunks:return chunks.pop(0)
            return await receive()
        await self.app(scope,replay,send)
