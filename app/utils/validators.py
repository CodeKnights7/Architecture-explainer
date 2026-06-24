from fastapi import HTTPException
from app.constants import ALLOWED_IMAGE_TYPES


async def validate_image(file):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unsupported image format"
        )