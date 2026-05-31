from fastapi import APIRouter

router = APIRouter(prefix="/query", tags=["query"])


@router.get("/status")
async def get_status():
    # TODO: return today's log so far
    return {"status": "not implemented"}


@router.get("/ask")
async def ask(q: str):
    # TODO: vector search → Claude → response
    return {"status": "not implemented", "question": q}
