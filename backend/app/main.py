from fastapi import FastAPI

from app.auth_routes import router as auth_router
from app.email_routes import router as email_router

app = FastAPI()
app.include_router(auth_router)
app.include_router(email_router)


@app.get("/health")
def health():
    return {"status": "ok"}
