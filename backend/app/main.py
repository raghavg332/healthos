from fastapi import FastAPI
from app.routes import ingest, jobs, query

app = FastAPI(title="HealthOS API", version="0.1.0")

app.include_router(ingest.router)
app.include_router(jobs.router)
app.include_router(query.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
