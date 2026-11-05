"""One reusable workflow for the CLI, scheduler and API."""
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from app import etl
from app.analytics import kpis
from app.db import connect, initialize, runtime
from app.rules import reconcile

LOCK = threading.Lock()
logger = logging.getLogger('supplychain360')

def now_local():
    return datetime.now(ZoneInfo(os.environ.get('SC360_TIMEZONE','Asia/Kolkata')))

def run_pipeline(kind='csv', location=None):
    if not LOCK.acquire(blocking=False):
        raise RuntimeError('A workflow is already running in this process')
    started = time.perf_counter()
    run_id = None
    lease = None
    try:
        lease = sqlite3.connect(runtime() / 'workflow-lock.db', timeout=0)
        try:
            lease.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            raise RuntimeError('A workflow is already running in another process') from exc
        initialize()
        timestamp = now_local().isoformat()
        with connect() as conn:
            run_id = conn.execute('INSERT INTO runs(started_at,status) VALUES (?,?)',(timestamp,'running')).lastrowid
        location = location or runtime() / 'source'
        frames = etl.validate(etl.extract(kind, location))
        loaded = etl.load(frames, timestamp)
        exceptions = reconcile(now_local())
        duration = (time.perf_counter()-started)*1000
        with connect() as conn:
            conn.execute('UPDATE runs SET status=?,duration_ms=?,rows_loaded=?,sla_met=? WHERE id=?',('success',duration,loaded,int(duration<=30000),run_id))
        report = runtime() / 'reports'
        report.mkdir(exist_ok=True)
        payload = {'generated_at':timestamp,'run_id':run_id,'kpis':kpis()}
        target = report / f'run-{run_id}.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload, indent=2),encoding='utf-8')
        temporary.replace(target)
        logger.info('run=%s success rows=%s exceptions=%s',run_id,loaded,exceptions)
        return {'run_id':run_id,'status':'success','rows_loaded':loaded,'active_exceptions':exceptions,'duration_ms':duration}
    except Exception as exc:
        if run_id is not None:
            with connect() as conn:
                conn.execute('UPDATE runs SET status=?,duration_ms=?,error=?,sla_met=0 WHERE id=?',('failed',(time.perf_counter()-started)*1000,str(exc),run_id))
                conn.execute('INSERT INTO notifications(created_at,kind,message) VALUES (?,?,?)',(now_local().isoformat(),'workflow_failed',f'Run {run_id}: {exc}'))
                conn.execute('INSERT INTO audit(created_at,action,detail) VALUES (?,?,?)',(now_local().isoformat(),'workflow_failed',f'Run {run_id}: {exc}'))
        logger.exception('Workflow failed')
        raise
    finally:
        if lease is not None:
            lease.close()
        LOCK.release()

def configure_logging():
    if not logger.handlers:
        handler = logging.FileHandler(runtime() / 'execution.log', encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
