import os
import aiofiles
from uuid import uuid4
from app.config import settings


async def save_upload_file(file):
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)

    file_extension = file.filename.split(".")[-1]

    file_name = f"{uuid4()}.{file_extension}"

    file_path = os.path.join(settings.UPLOAD_DIR, file_name)

    async with aiofiles.open(file_path, "wb") as out_file:
        content = await file.read()
        await out_file.write(content)

    return file_path