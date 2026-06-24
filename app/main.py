from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

from app.api.routes import (
    diagram,
    docs
)


app = FastAPI(

    title=settings.APP_NAME,

    version=settings.APP_VERSION,

    description=
    "AI Architecture Diagram Explainer",

    docs_url="/docs",

    redoc_url="/redoc"
)


# -------------------------
# CORS
# -------------------------

app.add_middleware(

    CORSMiddleware,

    allow_origins=[
        "*"
    ],

    allow_credentials=True,

    allow_methods=[
        "*"
    ],

    allow_headers=[
        "*"
    ]
)


# -------------------------
# ROUTERS
# -------------------------

app.include_router(
    diagram.router
)

app.include_router(
    docs.router
)


# -------------------------
# HEALTH CHECK
# -------------------------

@app.get(
    "/health"
)
async def health_check():

    return {

        "status":
        "healthy",

        "application":
        settings.APP_NAME,

        "version":
        settings.APP_VERSION
    }


# -------------------------
# ROOT
# -------------------------

@app.get("/")
async def root():

    return {

        "message":
        "AI Architecture Diagram Explainer",

        "version":
        settings.APP_VERSION,

        "docs":
        "/docs",

        "health":
        "/health"
    }