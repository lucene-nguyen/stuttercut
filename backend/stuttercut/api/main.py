"""API server (process 1). Run: uvicorn stuttercut.api.main:app --host 127.0.0.1"""

from fastapi import FastAPI

from stuttercut.api.routes import health

app = FastAPI(title="StutterCut")
app.include_router(health.router)
