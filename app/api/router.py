from fastapi import APIRouter

from app.api.routes.health import (
    router as health_router
)

from app.api.routes.diagram import (
    router as diagram_router
)

from app.api.routes.docs import (
    router as docs_router
)

api_router = APIRouter()

api_router.include_router(
    health_router,
    prefix="/health",
    tags=["Health"]
)

api_router.include_router(
    diagram_router,
    prefix="/diagram",
    tags=["Diagram"]
)

api_router.include_router(
    docs_router,
    prefix="/docs",
    tags=["Documentation"]
)