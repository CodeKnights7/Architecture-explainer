from fastapi import APIRouter
from app.services.documentation_service import (
    DocumentationService
)

router = APIRouter()


@router.post("/generate")
async def generate_docs(payload: dict):

    ai_response = payload.get(
        "architecture_analysis",
        ""
    )

    result = await DocumentationService.generate_documentation(
        ai_response
    )

    return {
        "success": True,
        "documentation": result
    }