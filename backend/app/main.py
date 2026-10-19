from fastapi import FastAPI

from app.auth_routes import router as auth_router
from app.classification_routes import router as classification_router
from app.draft_generation_routes import router as draft_generation_router
from app.email_routes import router as email_router
from app.gmail_import_routes import router as gmail_import_router
from app.draft_reply_routes import router as draft_reply_router
from app.summary_routes import router as summary_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(classification_router)
app.include_router(draft_generation_router)
app.include_router(email_router)
app.include_router(gmail_import_router)
app.include_router(draft_reply_router)
app.include_router(summary_router)


@app.get("/health")
def health():
    return {"status": "ok"}
