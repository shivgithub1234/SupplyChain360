from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from app.analytics import kpis
from app.db import ROOT, initialize, rows
from app.workflow import configure_logging, run_pipeline

@asynccontextmanager
async def lifespan(app):
    initialize()
    configure_logging()
    yield

app = FastAPI(title='SupplyChain360',version='1.0.0',lifespan=lifespan)

@app.get('/',include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / 'static' / 'index.html')

@app.get('/api/health')
def health():
    return {'status':'ok'}

@app.get('/api/kpis')
def metrics():
    return kpis()

@app.get('/api/data/{table}')
def data(table: str):
    try:
        return rows(table)
    except ValueError as exc:
        raise HTTPException(404,str(exc)) from exc

@app.post('/api/workflows/run')
def run(request: Request):
    # Require JSON so an unrelated web page cannot submit a simple cross-origin form.
    if request.headers.get('content-type','').split(';')[0] != 'application/json':
        raise HTTPException(415,'Use application/json')
    try:
        return run_pipeline()
    except RuntimeError as exc:
        raise HTTPException(409,str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422,'Workflow failed. See execution history for details.') from exc

@app.get('/api/reports/latest')
def report():
    from app.db import runtime
    files = list((runtime() / 'reports').glob('run-*.json'))
    if not files:
        raise HTTPException(404,'Run a successful workflow first')
    latest = max(files,key=lambda p: int(p.stem.split('-')[1]))
    return FileResponse(latest,media_type='application/json',filename=latest.name)
