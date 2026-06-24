from fastapi import APIRouter
from fastapi import UploadFile
from fastapi import File
from fastapi import HTTPException

from app.utils.validators import (
    validate_image
)

from app.utils.file_handler import (
    save_upload_file
)

from app.services.diagram_service import (
    DiagramService
)

from app.schemas.response_schema import (
    DiagramResponseSchema
)

from app.logger import logger


router = APIRouter(
    prefix="/diagram",
    tags=["Diagram"]
)


@router.post(
    "/analyze",
    response_model=DiagramResponseSchema
)
async def analyze_architecture_diagram(
    file: UploadFile = File(...)
):

    try:

        logger.info(
            f"Received file: {file.filename}"
        )

        await validate_image(
            file
        )

        saved_path = (
            await save_upload_file(
                file
            )
        )

        result = (
            await DiagramService
            .process_diagram(
                saved_path
            )
        )

        if result.get(
            "error"
        ):

            raise HTTPException(
                status_code=500,
                detail=result.get(
                    "message",
                    "Diagram analysis failed"
                )
            )

        return {

            "success": True,

            "file_name":
            file.filename,

            "data": {

                "extracted_text":
                result.get(
                    "extracted_text",
                    ""
                ),

                "detected_components":
                result.get(
                    "detected_components",
                    []
                ),

                "services":
                result.get(
                    "services",
                    []
                ),

                "gateways":
                result.get(
                    "gateways",
                    []
                ),

                "databases":
                result.get(
                    "databases",
                    []
                ),

                "queues":
                result.get(
                    "queues",
                    []
                ),

                "storage":
                result.get(
                    "storage",
                    []
                ),

                "security":
                result.get(
                    "security",
                    []
                ),

                "cloud":
                result.get(
                    "cloud",
                    []
                ),

                "containers":
                result.get(
                    "containers",
                    []
                ),

                "observability":
                result.get(
                    "observability",
                    []
                ),

                "architecture_analysis":
                result.get(
                    "architecture_analysis",
                    ""
                ),

                "mermaid_diagram":
                result.get(
                    "mermaid_diagram",
                    ""
                ),

                "markdown_documentation":
                result.get(
                    "markdown_documentation",
                    ""
                ),

                "metadata":
                result.get(
                    "metadata",
                    {}
                )
            }
        }

    except HTTPException:

        raise

    except Exception as e:

        logger.exception(
            "Unexpected error during analysis"
        )

        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
