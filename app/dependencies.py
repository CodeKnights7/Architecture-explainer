from fastapi import HTTPException
from fastapi import status


async def common_responses():
    return {
        "message": "Dependency loaded successfully"
    }


def raise_not_found(message: str):
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=message
    )