from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from pydantic import BaseModel


class SystemMetricsSchema(
    BaseModel
):

    cpu_percent: float

    memory_usage_mb: float

    system_memory_percent: float

    available_memory_mb: float


class EvaluationSchema(
    BaseModel
):

    overall_confidence: float

    ocr_quality: float

    visual_quality: float = 0.0

    component_score: float

    hallucination_risk: str

    hallucination_score: float

    enterprise_score: float

    domain_bonus: float = 0.0


class GraphMetricsSchema(
    BaseModel
):

    nodes: int

    edges: int

    density: float

    critical_components: List[str]

    single_points_of_failure: List[str]


class MetadataSchema(
    BaseModel
):

    domain: str

    domain_confidence: str

    domain_score: int

    confidence: float

    ocr_characters: int

    ocr_confidence: float

    ocr_latency_ms: float

    llm_latency_ms: float

    total_latency_ms: float

    llm_fallback_used: bool = False

    system_metrics: SystemMetricsSchema

    evaluation: EvaluationSchema

    graph_metrics: GraphMetricsSchema


class DiagramDataSchema(
    BaseModel
):

    extracted_text: str

    detected_components: List[str]

    services: List[str]

    gateways: List[str]

    databases: List[str]

    queues: List[str]

    storage: List[str]

    security: List[str]

    cloud: List[str]

    containers: List[str]

    observability: List[str]

    architecture_analysis: str

    mermaid_diagram: str

    markdown_documentation: str

    metadata: MetadataSchema


class DiagramResponseSchema(
    BaseModel
):

    success: bool

    file_name: str

    data: DiagramDataSchema


class ErrorResponseSchema(
    BaseModel
):

    success: bool = False

    error: bool = True

    message: str


class DocumentationResponseSchema(
    BaseModel
):

    markdown: str

    json: Dict[str, Any]
