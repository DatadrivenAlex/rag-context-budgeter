from fastapi import FastAPI

from context_budgeter.packer import PackRequest, PackResult, pack

app = FastAPI(title="RAG Context Budgeter", version="0.1.0")


@app.post("/pack", response_model=PackResult)
def pack_context(body: PackRequest):
    return pack(body)


@app.get("/health")
def health():
    return {"status": "ok"}
