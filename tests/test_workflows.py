import json
from datetime import timedelta
from unittest.mock import Mock
import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from app import etl
from app.analytics import kpis
from app.db import connect, initialize, rows, runtime
from app.demo import generate
from app.main import app
from app.rules import reconcile
from app.workflow import LOCK, now_local, run_pipeline

@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('SC360_DATA_DIR',str(tmp_path))
    initialize()
    generate()

def test_demo_kpis_and_idempotency():
    first = run_pipeline()
    assert first['rows_loaded'] == 10
    assert first['active_exceptions'] == 5
    assert len(rows('notifications')) == 5
    run_pipeline()
    assert len(rows('inventory')) == 4
    assert len(rows('notifications')) == 5
    metrics = kpis()
    assert metrics['stock_availability_pct'] == 75
    assert metrics['on_time_delivery_pct'] == 50
    assert metrics['exception_rate_pct'] == 62.5
    assert metrics['workflow_completion_pct'] == 100
    expected_turnover = (82*45+80*12+50*85+25*22)/(((100+18)/2)*45+((80+0)/2)*12+((200+150)/2)*85+((120+95)/2)*22)
    assert metrics['inventory_turnover'] == pytest.approx(expected_turnover)
    assert (runtime() / 'reports' / 'run-2.json').exists()

@pytest.mark.parametrize('column,value',[('quantity',-1),('quantity',1.5),('quantity','inf'),('supplier_id','missing'),('sku','')])
def test_invalid_import_preserves_last_snapshot(column,value):
    run_pipeline()
    before = rows('inventory')
    path = runtime() / 'source' / 'inventory.csv'
    frame = pd.read_csv(path,dtype=str)
    frame.loc[0,column] = str(value)
    frame.to_csv(path,index=False)
    with pytest.raises(ValueError):
        run_pipeline()
    assert rows('inventory') == before
    assert rows('runs')[-1]['status'] == 'failed'
    assert rows('notifications')[-1]['kind'] == 'workflow_failed'

def test_duplicate_and_bad_delivery_dates():
    frames = etl.extract('csv',runtime()/'source')
    frames['inventory'].loc[1,'sku'] = 'RM-001'
    with pytest.raises(ValueError,match='duplicate'):
        etl.validate(frames)
    frames = etl.extract('csv',runtime()/'source')
    frames['purchase_orders'].loc[2,'delivered_date'] = ''
    with pytest.raises(ValueError,match='delivery date'):
        etl.validate(frames)

def test_load_transaction_rolls_back_on_database_error():
    run_pipeline()
    before = rows('inventory')
    frames = etl.validate(etl.extract('csv',runtime()/'source'))
    frames['inventory'].loc[0,'supplier_id'] = 'missing'
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        etl.load(frames,now_local().isoformat())
    assert rows('inventory') == before
    assert len(rows('purchase_orders')) == 4

def test_escalation_resolution_and_reopening():
    run_pipeline()
    with connect() as conn:
        conn.execute('UPDATE alerts SET first_seen=?',((now_local()-timedelta(hours=25)).isoformat(),))
    reconcile(now_local())
    assert len([n for n in rows('notifications') if n['kind']=='escalation']) == 5
    reconcile(now_local())
    assert len(rows('notifications')) == 10
    with connect() as conn:
        conn.execute("UPDATE inventory SET quantity=50,counted_quantity=50 WHERE sku='RM-001'")
    reconcile(now_local())
    assert len([a for a in rows('alerts') if a['active']]) == 4
    assert rows('notifications')[-1]['kind'] == 'resolved'
    run_pipeline()
    assert rows('notifications')[-1]['kind'] == 'alert'

def test_sqlite_and_api_sources(monkeypatch):
    assert run_pipeline('sqlite',runtime()/'source'/'upstream.db')['rows_loaded'] == 10
    bundle = json.loads((runtime()/'source'/'bundle.json').read_text())
    response = httpx.Response(200,json=bundle,request=httpx.Request('GET','http://supplier.test'))
    monkeypatch.setattr(httpx,'get',lambda *a,**k:response)
    assert run_pipeline('api','http://supplier.test')['active_exceptions'] == 5

def test_retry_transient_but_not_client_error():
    fn = Mock(side_effect=[httpx.ConnectError('offline'),42])
    assert etl.retry(fn,delay=0) == 42
    assert fn.call_count == 2
    request = httpx.Request('GET','http://supplier.test')
    fn = Mock(side_effect=httpx.HTTPStatusError('bad',request=request,response=httpx.Response(400,request=request)))
    with pytest.raises(httpx.HTTPStatusError):
        etl.retry(fn,delay=0)
    assert fn.call_count == 1

def test_real_local_http_source():
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    handler = partial(SimpleHTTPRequestHandler,directory=str(runtime()/'source'))
    server = ThreadingHTTPServer(('127.0.0.1',0),handler)
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        result = run_pipeline('api',f'http://127.0.0.1:{server.server_port}/bundle.json')
        assert result['rows_loaded'] == 10
        assert result['active_exceptions'] == 5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

def test_cross_process_database_lock():
    import sqlite3
    lease = sqlite3.connect(runtime()/'workflow-lock.db')
    lease.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(RuntimeError,match='another process'):
            run_pipeline()
    finally:
        lease.close()
    assert run_pipeline()['status'] == 'success'

def test_api_and_download():
    with TestClient(app) as client:
        assert client.get('/api/reports/latest').status_code == 404
        assert client.get('/api/kpis').json()['stock_availability_pct'] is None
        assert client.get('/').status_code == 200
        assert client.post('/api/workflows/run').status_code == 415
        result = client.post('/api/workflows/run',json={})
        assert result.status_code == 200
        assert result.json()['active_exceptions'] == 5
        assert client.get('/api/data/inventory').json()[0]['sku'] == 'RM-001'
        assert client.get('/api/data/unknown').status_code == 404
        assert client.get('/api/reports/latest').json()['kpis']['stock_availability_pct'] == 75
        assert client.get('/docs').status_code == 200
        with LOCK:
            assert client.post('/api/workflows/run',json={}).status_code == 409
