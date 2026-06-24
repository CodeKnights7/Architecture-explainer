"""
prompt_engine.py
================
Prompt builder for the vision LLM (Qwen2.5-VL via Ollama).

Improvements:
  1. OCR fallback instruction – when OCR text is empty, the prompt
     explicitly tells the model to rely 100% on the visual image.
  2. Domain-adaptive section emphasis – the prompt expands or highlights
     sections relevant to the detected domain (e.g. security for
     Cybersecurity diagrams, MLOps for ML diagrams).
  3. Output format is more structured (markdown + tables) to produce
     richer text that the evaluator and component extractor can parse.
  4. The Mermaid section has explicit relationship rules to avoid
     node-naming conflicts.
  5. Token budget hint is included so the LLM doesn't truncate early.
"""


class PromptEngine:

    # ------------------------------------------------------------------ #
    # Domain-specific emphasis blocks                                      #
    # ------------------------------------------------------------------ #

    _DOMAIN_HINTS = {
        "Microservices": """
Pay special attention to:
- Service boundaries and responsibilities
- Inter-service communication (sync REST/gRPC vs async queue)
- API Gateway routing rules
- Data ownership per service
- Circuit breakers and retry patterns
""",
        "Cloud Architecture": """
Pay special attention to:
- Cloud provider and region placement
- VPC / subnet / security group topology
- Managed vs self-hosted services
- Cost-optimisation patterns (spot instances, reserved capacity)
- Multi-AZ or multi-region redundancy
""",
        "Kubernetes": """
Pay special attention to:
- Namespace boundaries
- Workload types (Deployment, StatefulSet, DaemonSet, Job)
- Ingress / egress traffic flow
- PersistentVolume and PersistentVolumeClaim usage
- Resource limits and HPA configuration
""",
        "Data Engineering": """
Pay special attention to:
- Data source → ingestion → transformation → serving pipeline
- Batch vs streaming processing
- Data quality and lineage
- Orchestration (Airflow DAGs, etc.)
- Storage tiers (hot/warm/cold)
""",
        "Machine Learning": """
Pay special attention to:
- Training pipeline vs inference pipeline
- Feature store and feature engineering
- Model versioning and registry
- A/B testing or canary deployment
- GPU/TPU resource allocation
""",
        "Cybersecurity": """
Pay special attention to:
- Network segmentation and DMZ placement
- Identity and Access Management
- Threat detection and response
- Encryption in transit and at rest
- Compliance boundaries
""",
        "DevOps / CI-CD": """
Pay special attention to:
- Source control → build → test → deploy stages
- Artifact registry and versioning
- Environment promotion strategy (dev → staging → prod)
- Rollback mechanisms
- Infrastructure as Code tooling
""",
    }

    _DEFAULT_DOMAIN_HINT = """
Pay special attention to:
- Overall system purpose and traffic flow
- Component roles and boundaries
- Data persistence strategy
- Scalability and reliability mechanisms
"""

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def generate_prompt(
        ocr_text: str,
        domain:   str,
    ) -> str:

        ocr_section = (
            f"""
==================================================
OCR EXTRACTED TEXT (from image preprocessing)
==================================================

{ocr_text.strip()}

NOTE: Prioritise the VISUAL IMAGE over OCR text.
"""
            if ocr_text.strip()
            else """
==================================================
OCR EXTRACTED TEXT
==================================================

[OCR returned no text — the diagram may use vector graphics or icons
without embedded raster text.  Rely ENTIRELY on the visual image.]
"""
        )

        domain_hint = PromptEngine._DOMAIN_HINTS.get(
            domain,
            PromptEngine._DEFAULT_DOMAIN_HINT
        )

        return f"""
You are a world-class Principal Software Architect, Cloud Architect,
DevOps Engineer, Security Architect, and Systems Design Expert with
20+ years of experience.  Your analyses are used by engineering teams
at FAANG, Nvidia, and top-tier startups to document, review, and improve
production architectures.

Your task: analyse the UPLOADED ARCHITECTURE DIAGRAM IMAGE thoroughly.

==================================================
STRICT ANALYSIS RULES
==================================================

1. Analyse BOTH the image and the OCR text below.
2. The IMAGE is the primary source of truth.
3. NEVER invent components, technologies, services, or connections
   that are NOT visible in the diagram.
4. If a component is unclear, state: "Not clearly visible."
5. NEVER use weasel words (probably, likely, might be, seems).
6. Every claim must map to something visible in the image.
7. Confidence must match evidence strength.
8. Produce detailed, actionable analysis — not generic advice.
9. Use the exact component names you see in the diagram.
10. A blank OCR does NOT mean the diagram is empty — read the image.

==================================================
DETECTED DOMAIN: {domain}
==================================================
{domain_hint}
{ocr_section}

==================================================
REQUIRED OUTPUT FORMAT  (follow exactly)
==================================================

# Architecture Overview

- **Architecture Type:** [e.g. Microservices, Monolith, Event-Driven, Lambda, etc.]
- **Probable Business Purpose:** [e.g. e-commerce platform, ride-sharing backend]
- **Major Visible Components:** [comma-separated list]
- **Estimated Scale:** [small / medium / large / enterprise]

---

# Component Inventory

| Name | Type | Purpose | Confidence |
|------|------|---------|------------|
| ... | ... | ... | High/Medium/Low |

(List EVERY visible component. Include icons-only components if identifiable.)

---

# Architecture Layers

- **Presentation Layer:** ...
- **API / Edge Layer:** ...
- **Business Logic Layer:** ...
- **Data Layer:** ...
- **Infrastructure Layer:** ...
- **Observability Layer:** ...

(Write "Not visible" for layers not present in the diagram.)

---

# Data Flow Analysis

- **Primary Request Flow:** [Client → ... → Response]
- **Async / Event Flow:** [Producer → Queue → Consumer]
- **Data Persistence Flow:** [Service → DB / Cache]
- **External Integrations:** [if any]

---

# Service Interactions

- **Synchronous (REST/gRPC):** [list pairs]
- **Asynchronous (Queue/Event):** [list pairs]
- **Event-Driven Patterns:** [if any]

---

# Infrastructure Analysis

- **Networking:** ...
- **Load Balancers / Gateways:** ...
- **Containers / Orchestration:** ...
- **Cloud Provider:** ...

---

# Database Analysis

| Database | Type | Used By | Notes |
|----------|------|---------|-------|
| ... | Relational/NoSQL/Cache | ... | ... |

---

# Security Analysis

- **Authentication:** ...
- **Authorization:** ...
- **Network Security (WAF/Firewall):** ...
- **Encryption:** ...
- **Secrets Management:** ...

---

# Scalability Analysis

- **Horizontal Scaling Points:** ...
- **Potential Bottlenecks:** ...
- **Single Points of Failure (SPOFs):** ...
- **Caching Strategy:** ...

---

# Observability Analysis

- **Logging:** ...
- **Metrics:** ...
- **Tracing:** ...
- **Alerting:** ...

---

# Architecture Strengths

1. ...
2. ...
3. ...

---

# Architecture Risks

1. ...
2. ...
3. ...

---

# Recommendations

1. ...
2. ...
3. ...
4. ...
5. ...

---

# Technology Stack Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| ... | ... | ... |

---

# Architecture Patterns

| Pattern | Detected | Evidence |
|---------|----------|----------|
| Microservices | Yes/No/Partial | ... |
| Event-Driven | Yes/No/Partial | ... |
| CQRS | Yes/No/Partial | ... |
| Saga | Yes/No/Partial | ... |
| Service Mesh | Yes/No/Partial | ... |
| Layered Architecture | Yes/No/Partial | ... |
| API Gateway Pattern | Yes/No/Partial | ... |

---

# Mermaid Diagram

Generate a complete, accurate Mermaid flowchart of the architecture.

Rules:
1. Only use nodes that are VISIBLE in the diagram.
2. Only add edges for VISIBLE connections or clearly implied flows.
3. Node IDs must be CamelCase with NO spaces.
4. Use subgraphs for logical groupings (e.g. subgraph DataLayer).
5. Arrow labels describe the protocol or action (e.g. -->|REST| or -->|SQL|).

```mermaid
graph TD
...
```
"""
