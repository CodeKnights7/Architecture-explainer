from pydantic import BaseModel
from typing import Optional


class DiagramRequest(BaseModel):
    project_name: Optional[str] = "Architecture AI"

    generate_markdown: Optional[bool] = True

    generate_json: Optional[bool] = True

    detect_services: Optional[bool] = True

    detect_databases: Optional[bool] = True

    detect_api_flow: Optional[bool] = True