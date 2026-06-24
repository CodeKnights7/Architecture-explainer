# AI Architecture Diagram Explainer — Full Project Description

## Project Overview

**AI Architecture Diagram Explainer** is a production-grade, fully local REST API service that accepts an architecture diagram image (PNG, JPEG, WebP) and returns a deeply structured analysis of it — including component extraction, domain classification, a Mermaid flowchart, a full Markdown documentation report, Wikipedia enrichment paragraphs, topology graph metrics, quality scoring, and a structured JSON breakdown of all detected components.

The pipeline is designed to run entirely offline (CPU-only) on commodity hardware such as an AMD Ryzen 7 7730U with 16 GB RAM. No cloud services, no paid APIs, no GPU required. All AI inference is performed locally via **Ollama** running the **Qwen2.5-VL 7B** vision-language model.

Version: **2.1.0**

---

## Goals and Purpose

The system is designed to:
- Automatically document legacy or undocumented architecture diagrams.
- Extract every visible component from an uploaded architecture image and categorise them (services, gateways, databases, queues, storage, containers, observability, cloud services, security).
- Classify the architecture domain (Microservices, Cloud, Kubernetes, Data Engineering, ML, Cybersecurity, DevOps, IoT, Serverless, Enterprise).
- Generate a Mermaid flowchart of the architecture topology.
- Produce a professional Markdown documentation report.
- Enrich the report with Wikipedia definitions of each detected technology, made context-aware with architecture-specific roles.
- Score the analysis quality and flag hallucination risk and single points of failure.
- Return all results in a single structured JSON response consumable by any frontend or pipeline.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Web Framework** | FastAPI 0.116.1 | REST API, async routing, OpenAPI docs |
| **ASGI Server** | Uvicorn 0.35.0 (with standard extras) | Serve FastAPI in production |
| **Vision LLM** | Ollama (qwen2.5vl:7b) | Local multimodal AI inference (image + text) |
| **OCR** | EasyOCR 1.7.2 | Multi-pass text extraction from diagram images |
| **Image Processing** | OpenCV 4.12.0.88 | Preprocessing pipeline (CLAHE, denoising, thresholding, resizing) |
| **Numerical Computing** | NumPy 2.2.6 | Array operations throughout the pipeline |
| **Image Science** | scikit-image 0.25.2, SciPy 1.16.1 | Supporting image processing operations |
| **Deep Learning Runtime** | PyTorch (torch, torchvision) | EasyOCR runtime backend (CPU mode) |
| **Graph Analysis** | NetworkX 3.5 | Directed graph construction, topology metrics, shortest path, centrality |
| **Fuzzy Matching** | RapidFuzz 3.13.0 | Available for component name fuzzy-matching (imported via dependencies) |
| **Pydantic** | Pydantic 2.11.7 + pydantic-settings 2.10.1 | Data validation, response schemas, settings management |
| **HTTP Client** | Requests 2.32.4, HTTPX 0.28.1 | LLM calls (Requests), Wikipedia REST API calls |
| **System Metrics** | psutil 7.0.0 | CPU %, memory MB, available memory per request |
| **Markdown** | markdown 3.8.2 | Markdown rendering support |
| **Templating** | Jinja2 3.1.6 | Markdown report template rendering |
| **Async File I/O** | aiofiles 24.1.0 | Non-blocking image file upload handling |
| **Multipart Upload** | python-multipart 0.0.20 | FastAPI file upload support |
| **Image Pillow** | Pillow 11.2.1 | Image loading support |
| **MCP Server** | Node.js (http, https modules) | Wikipedia MCP server (wiki-server.js) |
| **Containerisation** | Docker + Docker Compose | Production deployment |
| **Environment Config** | python-dotenv 1.1.1 | `.env` configuration loading |

---

## Project Structure

```
ai-architecture-explainer/
├── app/
│   ├── main.py                         # FastAPI app, CORS, routers
│   ├── config.py                       # Pydantic settings with .env
│   ├── constants.py                    # Allowed MIME types
│   ├── logger.py                       # Global logging config
│   ├── dependencies.py                 # FastAPI dependency helpers
│   ├── api/
│   │   ├── router.py                   # API router aggregation
│   │   └── routes/
│   │       ├── diagram.py              # POST /api/v1/diagram/analyze
│   │       ├── docs.py                 # GET /api/v1/docs
│   │       └── health.py              # GET /health
│   ├── core/
│   │   ├── llm_engine.py               # Ollama API caller, base64 encoder, retry logic
│   │   ├── prompt_engine.py            # Domain-adaptive prompt builder
│   │   ├── ocr_engine.py               # Multi-pass EasyOCR engine, IoU dedup
│   │   ├── image_processor.py          # OpenCV preprocessing, smart resize, candidate building
│   │   ├── component_extractor.py      # Keyword-based component category detector
│   │   ├── domain_classifier.py        # Weighted keyword domain classifier (OCR + visual)
│   │   ├── graph_engine.py             # NetworkX graph builder, Mermaid renderer, metrics
│   │   ├── architecture_evaluator.py   # Quality scoring, hallucination risk, enterprise score
│   │   ├── json_generator.py           # Regex-based entity extraction from LLM output
│   │   ├── mermaid_generator.py        # Mermaid diagram generator (wraps graph engine)
│   │   ├── markdown_generator.py       # Markdown documentation report generator
│   │   ├── wiki_enrichment.py          # Wikipedia REST API enrichment with context
│   │   └── helpers/
│   │       └── metrics.py              # psutil system metrics snapshot
│   ├── services/
│   │   ├── diagram_service.py          # 11-step pipeline orchestrator
│   │   └── documentation_service.py    # Documentation retrieval helper
│   ├── schemas/
│   │   ├── diagram_schema.py           # Upload input schema
│   │   └── response_schema.py          # Full response Pydantic models
│   └── utils/
│       ├── file_handler.py             # Upload save/delete utilities
│       ├── helpers.py                  # General utility functions
│       └── validators.py               # File type/size validation
├── mcp/
│   ├── wiki-server.js                  # Node.js MCP-compatible Wikipedia server
│   └── package.json                    # Node.js dependencies (none external)
├── requirements.txt                    # Python dependencies
├── Dockerfile                          # Docker build (Python 3.11-slim + tesseract)
├── docker-compose.yml                  # Service composition
├── .env                                # Environment configuration
└── start.sh                            # Startup script
```

---

## Full Pipeline: 11 Steps

### Step 1 — OCR: Multi-Pass Text Extraction (`ocr_engine.py` + `image_processor.py`)

When an image is uploaded, the first action is text extraction via `OCREngine.extract_with_metadata()`.

**Image preprocessing (`ImageProcessor`):**
- The image is loaded with OpenCV (`cv2.imread`).
- `smart_resize()` is called: if the long edge is under 1600 px, the image is upscaled using bicubic interpolation (`cv2.INTER_CUBIC`). If over 2200 px, it is downscaled with area interpolation (`cv2.INTER_AREA`). This range is calibrated for EasyOCR accuracy vs. inference speed on the Ryzen 7 7730U.
- The image is converted to greyscale with `cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)`.
- Two preprocessing candidates are built:
  - **`clahe_otsu`**: `fastNlMeansDenoising` → CLAHE (`clipLimit=2.0, tileGridSize=(8,8)`) → Otsu thresholding. Best for white-background diagrams.
  - **`raw_gray`**: The raw greyscale image without further processing. Fast fallback that EasyOCR handles well natively.
- A best-candidate selection is performed by running EasyOCR on both with `greedy` decoder and picking the one with the highest `char_count × avg_confidence` score.
- A `DEBUG` flag can write `debug_processed.png` for inspection.

**EasyOCR passes (`OCREngine`):**
- An EasyOCR `Reader` singleton (`gpu=False, verbose=False`) is initialised once and reused.
- Pass 1: Word-level pass on `clahe_otsu` candidate (`paragraph=False`).
- Pass 2: Word-level pass on `raw_gray` candidate.
- Pass 3: Paragraph-mode pass on the best single candidate (`paragraph=True`) — merges nearby tokens cheaply.
- Optional Pass 4: 2×2 overlapping tile pass (`_run_on_tiles`) — disabled by default (`ENABLE_TILED_OCR=false`). Only fires when `ENABLE_TILED_OCR=true` and long-edge > 2000 px.

**Result normalisation (`_normalise_results`):**
EasyOCR returns different tuple shapes depending on `paragraph` and `detail` settings:
- `(bbox, text, conf)` 3-tuples from word-level passes.
- `(bbox, text)` 2-tuples from paragraph mode (no confidence — assigned `0.80`).
- Bare strings (assigned `0.80` and a dummy bounding box).
All results are normalised to `(bbox, text, conf)` 3-tuples.

**IoU Deduplication (`_deduplicate`):**
All results from all passes are pooled. Bounding box IoU (Intersection over Union) is computed for every pair. When two detections overlap by > 40%, the lower-confidence one is discarded. This eliminates duplicate extractions from multi-pass and tile-pass overlaps.

**Token cleaning and validation:**
- `_clean_token`: strips leading/trailing non-alphanumeric characters.
- `_is_valid_token`: rejects tokens under 2 characters and tokens with no alphanumeric content.
- Confidence threshold: `0.10` (very permissive to keep all diagram text).

**Output:**
```json
{
  "text": "User Service\nOrder Service\nKafka\n...",
  "average_confidence": 0.84,
  "items": [{"text": "...", "confidence": 0.91, "bbox": [...]}],
  "count": 18
}
```

---

### Step 2 — Initial Domain Classification (`domain_classifier.py`)

Before calling the LLM, a fast initial domain classification is performed on the OCR text alone using `DomainClassifier.classify()`. This is used to tailor the prompt.

**Domain taxonomy:**
10 architecture domains are defined with keyword-weight dictionaries:
- Microservices, Cloud Architecture, Kubernetes, Data Engineering, Machine Learning, Cybersecurity, DevOps/CI-CD, IoT, Serverless, Enterprise Architecture.

**Scoring logic:**
- Keywords are sorted longest-first to prevent substring shadowing.
- Each keyword occurrence multiplies its weight: `score += count × weight`.
- Compound phrases like `"api gateway"` (weight 5) beat single words like `"gateway"` (weight 3).
- The domain with the highest total score wins.
- Confidence levels: `score ≥ 10` → High, `score ≥ 5` → Medium, else Low.
- If all scores are zero (OCR returned nothing), defaults to `"Microservices"` at `Medium` confidence.

---

### Step 3 — Domain-Adaptive Prompt Building (`prompt_engine.py`)

`PromptEngine.generate_prompt()` builds a structured, multi-section prompt for the vision LLM.

**OCR section:**
- If OCR returned text: included with note "Prioritise the VISUAL IMAGE over OCR text."
- If OCR returned nothing: a fallback message tells the LLM "Rely ENTIRELY on the visual image."

**Domain hint section:**
Each domain has a dedicated `_DOMAIN_HINTS` block with 5 domain-specific focus points. For example, `Microservices` emphasises service boundaries, inter-service communication, API Gateway routing, data ownership, and circuit breakers. `Cybersecurity` emphasises network segmentation, IAM, DMZ placement, encryption, and compliance boundaries. A `_DEFAULT_DOMAIN_HINT` covers generic diagrams.

**Required output format:**
The prompt mandates a strict multi-section Markdown output with:
- Architecture Overview (type, business purpose, components, scale)
- Component Inventory table (name, type, purpose, confidence)
- Architecture Layers (presentation, API, business logic, data, infra, observability)
- Data Flow Analysis (primary, async, persistence, external integrations)
- Service Interactions (sync REST/gRPC, async, event-driven)
- Infrastructure Analysis (networking, load balancers, containers, cloud)
- Database Analysis table
- Security Analysis (auth, authz, WAF, encryption, secrets management)
- Scalability Analysis (scaling points, bottlenecks, SPOFs, caching)
- Observability Analysis (logging, metrics, tracing, alerting)
- Architecture Strengths, Risks, Recommendations
- Technology Stack Summary table
- Architecture Patterns detection table (Microservices, Event-Driven, CQRS, Saga, Service Mesh, Layered, API Gateway)
- Mermaid Diagram (graph TD with subgraphs, typed edges with protocol labels)

**10 strict analysis rules** are embedded: never invent components, always reference the image as primary source, no weasel words, blank OCR ≠ empty diagram, etc.

---

### Step 4 — Vision LLM Analysis (`llm_engine.py`)

`LLMEngine.analyze_diagram()` sends the prompt and the image to the local Ollama API.

**Image encoding:**
The image file is read in binary mode and base64-encoded (`base64.b64encode(...).decode("utf-8")`).

**Ollama API payload:**
```json
{
  "model": "qwen2.5vl:7b",
  "prompt": "<full domain-aware prompt>",
  "images": ["<base64_image>"],
  "stream": false,
  "options": {
    "temperature": 0.1,
    "top_p": 0.8,
    "num_predict": 2000,
    "num_thread": 8,
    "num_ctx": 1024,
    "repeat_last_n": 64
  }
}
```

**Performance tuning:**
- `num_thread=8`: Uses all 8 physical cores of the Ryzen 7 7730U, cutting per-token latency ~40% vs. Ollama's default of ~4 threads.
- `num_ctx=1024`: Small KV-cache window sufficient for diagram prompts + 2000-token responses, faster than 2048 or 4096.
- `num_predict=2000`: Reduced from 4000 to halve generation time on CPU.
- `repeat_last_n=64`: Reduce redundancy-penalty window for slightly faster sampling.

**Retry logic:**
The request is retried up to 3 times on any exception. Timeout is `300` seconds (5 minutes).

**Return value:**
```json
{
  "response": "<full LLM markdown analysis>",
  "llm_latency_ms": 87340.5
}
```

**Empty response fallback (v2.1 bug fix):**
If the LLM returns an empty string (timeout, overload, model failure), the pipeline does not silently fail. Instead, it logs a warning and switches to `using_ocr_fallback=True`. The OCR text is used as the `analysis_content` for all downstream steps. This recovers ~70-80% of component detection from OCR alone.

---

### Step 5 — Refined Domain Classification (`domain_classifier.py`)

After receiving the LLM response, `DomainClassifier.classify_combined()` runs a weighted combination of OCR-based and LLM-visual-based scoring:

- OCR scores are weighted at **35%**.
- LLM visual scores are weighted at **65%** (the LLM sees the image directly and produces richer domain vocabulary even when OCR fails).

The same keyword-weight taxonomy from Step 2 is applied, but now against the full LLM analysis text, which typically contains 200-2000 words of domain-specific vocabulary. This corrects domain misclassifications that occurred when OCR text alone was sparse.

---

### Step 6 — Component and Entity Extraction (`json_generator.py`)

`JSONGenerator.generate()` (or `generate_from_ocr()` in fallback mode) parses the LLM analysis text using a comprehensive set of regular expressions to extract named entities into typed lists.

**Entity types extracted:**
- **Services**: Named microservices (`User Service`, `Order Service`, etc.) using patterns like `\b([A-Z][A-Za-z]+ (?:Service|API|Backend|Worker|Engine|Manager|Handler|Consumer|Producer|Processor|Server))\b`.
- **Gateways**: API Gateway, Load Balancer, Nginx, Traefik, Kong, Envoy, Ingress, reverse proxy, etc.
- **Databases**: PostgreSQL, MySQL, MongoDB, Redis, Oracle, DynamoDB, Cassandra, Elasticsearch, Clickhouse, and generic "DB"/"Database" patterns.
- **Queues**: Kafka, RabbitMQ, ActiveMQ, SQS, Pub/Sub, EventBridge, NATS, Pulsar, and generic queue/stream/event bus patterns.
- **Storage**: S3, EFS, MinIO, Ceph, HDFS, blob storage, bucket, etc.
- **Cloud services**: AWS, EC2, EKS, Lambda, Azure, AKS, GCP, GKE, CloudFront, Route53, RDS, etc.
- **Containers**: Docker, Kubernetes, k8s, pod, Helm, ECS, Fargate.
- **Observability**: Prometheus, Grafana, ELK, Jaeger, Zipkin, Datadog, New Relic.
- **Security**: WAF, firewall, OAuth, JWT, IAM, VPN, SIEM, mTLS — extracted only when explicitly marked visible in the LLM output (visibility-verified extraction to avoid hallucination from generic prose like "No WAF visible").
- **CamelCase normalisation**: A `_camel_to_spaced()` utility converts CamelCase node IDs from the Mermaid block (e.g. `UserService`) to spaced names (`User Service`) before pattern matching.

In OCR fallback mode, `generate_from_ocr()` applies title-case normalisation first (converting `USER SERVICE` → `User Service`) so the same regex patterns work on all-caps OCR tokens.

**Output:**
```json
{
  "services": ["User Service", "Order Service", "Payment Service"],
  "gateways": ["API Gateway"],
  "databases": ["PostgreSQL", "Redis"],
  "queues": ["Kafka"],
  "storage": ["S3"],
  "cloud": ["AWS"],
  "containers": ["Kubernetes"],
  "observability": ["Prometheus", "Grafana"],
  "security": ["WAF", "JWT"],
  "detected_components": [...all merged...],
  "component_count": 12
}
```

---

### Step 7 — Graph Construction (`graph_engine.py`)

`GraphEngine.build_architecture_graph()` constructs a typed directed graph using **NetworkX** (`nx.DiGraph`).

**Node validation:**
Before adding any nodes, all lists are passed through `clean_nodes()`:
- Rejects empty, whitespace-only, and < 3-character strings.
- Rejects bare generic words: `service, services, api, gateway, database, queue, storage, microservice, backend, frontend, worker`.
- Rejects labels with > 5 tokens (prevents sentences from becoming nodes).
- Deduplicates and sorts.

**Node types:**
Each node is added to the graph with a `node_type` attribute:
- `gateway`, `service`, `database`, `queue`, `storage`, `container`, `observability`.

**Edge wiring rules:**
- **Gateway → Service**: Every gateway fans out to every service.
- **Service → Database (smart matching)**: Instead of connecting every service to every database, a two-pass matching algorithm is used:
  - Pass 1 — Exact prefix match: `_prefix_of("User Service") == "user"` matches `_prefix_of("User DB") == "user"`.
  - Pass 2 — Stem match: `_stem("Reporting Service") == "report"` matches `_stem("Report DB") == "report"`. The stem function strips category suffixes (`service`, `db`, `database`) and common English suffixes (`ing` for reporting → report).
  - Single-DB fallback: Only when exactly one database exists and a service has no match.
- **Service → Queue (async services)**: Services identified as async producers (containing keywords: `notification, email, sms, push, reporting, analytics, audit, logging, event, worker, consumer, publisher, shipping, payment`) are wired to all queues. Non-async services connect to a queue only when exactly one queue exists.
- **Queue → Async consumers**: Async services that are not already producers to a queue are wired as consumers from that queue.
- **Database → Storage**: Every database connects to every storage node.

**Graph metrics (`get_graph_metrics`):**
- `nodes`, `edges`, `density` (NetworkX `nx.density`).
- `critical_components`: Top-5 nodes by NetworkX degree centrality.
- `single_points_of_failure`: Nodes with combined in+out degree ≥ 3.

**Shortest path (`shortest_path`):**
Uses `nx.shortest_path` between any two named nodes.

**Isolated nodes (`isolated_nodes`):**
Returns nodes with no edges (in-degree = 0 and out-degree = 0).

---

### Step 8 — Mermaid Diagram Generation (`mermaid_generator.py` + `graph_engine.py`)

`MermaidGenerator.generate()` calls `GraphEngine.build_architecture_graph()` and then `GraphEngine.to_mermaid()` to produce a Mermaid `graph TD` diagram.

**Node shapes by type:**
- Gateways: stadium `([label])`
- Services: rounded box `(label)`
- Databases: cylinder `[(label)]`
- Queues: trapezoid `[/label/]`
- Storage: asymmetric `{label}`
- Containers: rectangle `[label]`
- Observability: hexagon `{{label}}`

**Subgraph structure:**
Nodes are grouped into named subgraph blocks (`subgraph Gateways`, `subgraph Services`, `subgraph Databases`, etc.). A subgraph block is only emitted when that bucket is non-empty.

**Edges:**
All edges are emitted outside subgraph blocks (Mermaid requirement for cross-subgraph arrows to work). Node identifiers use `re.sub(r"[^A-Za-z0-9_]", "_", name)` to ensure valid Mermaid IDs. Quotes in labels are replaced with single quotes.

**Fallback:**
If the graph is empty, `MermaidGenerator` falls back to generating a basic Mermaid from the component lists directly, or returns a placeholder.

---

### Step 9 — Quality Evaluation (`architecture_evaluator.py`)

`ArchitectureEvaluator.evaluate()` produces a composite quality score for the analysis.

**Scoring dimensions:**
- **OCR Quality** (`ocr_quality`): Based on OCR character count and confidence. More characters and higher confidence → higher score.
- **Visual Quality** (`visual_quality`): Based on LLM response length. A response > 500 characters scores positively; > 1500 characters scores even higher. When OCR is empty but LLM gave a long response, the visual quality compensates.
- **Component Score** (`component_score`): Based on the count and diversity of extracted components across all category types (services, gateways, databases, queues, storage, cloud, containers, observability, security). More diverse components = higher score.
- **Enterprise Score** (`enterprise_score`): Bonus for detecting enterprise-grade components (observability tools, cloud services, security components).
- **Domain Bonus** (`domain_bonus`): Applied when domain classification confidence is `High` or `Medium`, rewarding high-certainty domain detection.
- **Hallucination Score** (`hallucination_score`): Inversely related to OCR quality and component extraction confidence. High OCR confidence with many matched components → low hallucination risk.
- **Hallucination Risk** (`hallucination_risk`): Categorical label (Low / Medium / High).
- **Overall Confidence** (`overall_confidence`): A weighted combination of all above scores, capped at 100. Returned as a float 0–100.

The `confidence` field in `metadata` is `overall_confidence / 100` (0.0–1.0).

---

### Step 10 — System Metrics (`helpers/metrics.py`)

`Metrics.get_metrics_snapshot()` calls `psutil` to record a snapshot at the time of the response:
- `cpu_percent`: CPU usage at the moment of the call.
- `memory_usage_mb`: Process RSS memory in MB.
- `system_memory_percent`: System-wide memory usage %.
- `available_memory_mb`: Available system memory in MB.

These are embedded in the `metadata.system_metrics` field of every response, allowing the caller to track resource consumption per request.

---

### Step 11 — Wikipedia Enrichment + Markdown Report (`wiki_enrichment.py` + `markdown_generator.py`)

**Wikipedia Enrichment (`WikiEnrichment.enrich`):**

The enrichment module identifies up to 8 key terms from the detected components (domain, services, databases, queues, cloud, gateways, observability, containers, storage, security) and looks up each term on the Wikipedia REST API:
```
GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}
```
No authentication is required. A 0.15-second inter-request sleep is enforced to be polite.

A title normalisation map (`_WIKI_TITLE_MAP`) converts common diagram labels to canonical Wikipedia article titles: `"kafka"` → `"Apache Kafka"`, `"api gateway"` → `"API gateway"`, `"k8s"` → `"Kubernetes"`, etc.

**MCP server integration:**
Before calling Wikipedia directly, the module tries the local MCP server at `http://localhost:3333/wiki` (the Node.js `wiki-server.js`). If the MCP server is unreachable, it falls back to direct Wikipedia REST API calls. This makes the pipeline robust regardless of whether the MCP server is running.

**Architecture-aware context injection:**
Rather than returning generic textbook definitions, each Wikipedia extract is enhanced with context from the actual diagram:
- Redis: "...serves as a distributed cache layer for User Service, Order Service, reducing database load..."
- Kafka: "...enables asynchronous event-driven communication between Payment Service, Notification Service..."
- API Gateway: "...routes incoming requests across User Service, Order Service, managing load balancing..."

Up to 2 sentences from each Wikipedia extract are used, followed by the architecture-specific role sentence.

**Markdown Documentation Report (`MarkdownGenerator.generate`):**

The Markdown generator assembles the final human-readable documentation report using all pipeline outputs:
- A header with the architecture domain, confidence score, and date.
- The full LLM analysis text (or OCR fallback text).
- The Mermaid diagram block (fenced with `\`\`\`mermaid`).
- A component inventory section listing all extracted services, gateways, databases, queues, storage, cloud, containers, observability, and security components.
- The Wikipedia enrichment paragraph.
- Metadata summary (OCR quality, LLM latency, total latency, graph metrics, evaluation scores).

---

## API Endpoints

### `POST /api/v1/diagram/analyze`
- **Input**: `multipart/form-data` with field `file` (PNG, JPEG, WebP, max 10 MB).
- **Validates**: MIME type (`image/png`, `image/jpeg`, `image/jpg`, `image/webp`) and file size.
- **Saves** the uploaded file with a UUID filename to `app/uploads/`.
- **Calls** `DiagramService.process_diagram(image_path)` (the 11-step pipeline).
- **Returns**: `DiagramResponseSchema` with all structured fields.
- **Cleans up** the uploaded file after processing.

### `GET /api/v1/docs`
- Returns documentation metadata or links.

### `GET /health`
- Returns `{"status": "healthy", "application": "...", "version": "2.1.0"}`.

### `GET /`
- Returns root info with links to `/docs`, `/health`.

---

## Response Schema (Pydantic Models)

```
DiagramResponseSchema
├── success: bool
├── file_name: str
└── data: DiagramDataSchema
    ├── extracted_text: str                  # Raw OCR output
    ├── detected_components: List[str]       # All components merged
    ├── services: List[str]
    ├── gateways: List[str]
    ├── databases: List[str]
    ├── queues: List[str]
    ├── storage: List[str]
    ├── security: List[str]
    ├── cloud: List[str]
    ├── containers: List[str]
    ├── observability: List[str]
    ├── architecture_analysis: str           # Full LLM Markdown analysis
    ├── mermaid_diagram: str                 # Mermaid graph TD syntax
    ├── markdown_documentation: str          # Full Markdown report
    └── metadata: MetadataSchema
        ├── domain: str
        ├── domain_confidence: str           # High / Medium / Low
        ├── domain_score: int
        ├── confidence: float                # 0.0–1.0
        ├── ocr_characters: int
        ├── ocr_confidence: float
        ├── ocr_latency_ms: float
        ├── llm_latency_ms: float
        ├── total_latency_ms: float
        ├── llm_fallback_used: bool
        ├── system_metrics: SystemMetricsSchema
        │   ├── cpu_percent: float
        │   ├── memory_usage_mb: float
        │   ├── system_memory_percent: float
        │   └── available_memory_mb: float
        ├── evaluation: EvaluationSchema
        │   ├── overall_confidence: float
        │   ├── ocr_quality: float
        │   ├── visual_quality: float
        │   ├── component_score: float
        │   ├── hallucination_risk: str
        │   ├── hallucination_score: float
        │   ├── enterprise_score: float
        │   └── domain_bonus: float
        └── graph_metrics: GraphMetricsSchema
            ├── nodes: int
            ├── edges: int
            ├── density: float
            ├── critical_components: List[str]
            └── single_points_of_failure: List[str]
```

---

## Configuration (`.env` / `config.py`)

All settings are managed via Pydantic `BaseSettings` and can be overridden in `.env`:

| Setting | Default | Description |
|---------|---------|-------------|
| `APP_NAME` | AI Architecture Diagram Explainer | Application name |
| `APP_VERSION` | 2.1.0 | Version |
| `DEBUG` | False | Debug mode (writes debug_processed.png) |
| `OLLAMA_MODEL` | qwen2.5vl:7b | Ollama vision model |
| `OLLAMA_URL` | http://127.0.0.1:11434/api/generate | Ollama endpoint |
| `UPLOAD_DIR` | app/uploads | Upload directory |
| `MAX_FILE_SIZE` | 10485760 (10 MB) | Max image file size |
| `OCR_CONFIDENCE_THRESHOLD` | 0.10 | Min confidence to keep OCR token |
| `MIN_OCR_UPSCALE_PX` | 1600 | Minimum long-edge for OCR upscaling |
| `MAX_OCR_UPSCALE_PX` | 2200 | Maximum long-edge cap |
| `MAX_LLM_TOKENS` | 2000 | Max tokens from Ollama response |
| `LLM_TEMPERATURE` | 0.1 | LLM temperature (low = deterministic) |
| `LLM_TOP_P` | 0.8 | LLM top-p nucleus sampling |
| `LLM_NUM_THREADS` | 8 | Ollama CPU threads (all Ryzen 7 cores) |
| `LLM_CONTEXT_SIZE` | 1024 | KV-cache context window |
| `LLM_TIMEOUT_SECONDS` | 300 | Per-request LLM timeout |
| `ENABLE_METRICS` | True | Enable psutil metrics snapshot |
| `ENABLE_GRAPH_ANALYSIS` | True | Enable NetworkX graph construction |
| `ENABLE_EVALUATION` | True | Enable quality scoring |
| `ENABLE_TILED_OCR` | false | Enable 2×2 tiled OCR pass (slow) |

---

## Docker Deployment

**Dockerfile** (Python 3.11-slim base):
- Installs system packages: `tesseract-ocr`, `tesseract-ocr-eng`, `tesseract-ocr-osd`, `libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender-dev`, `libgomp1`, `fonts-dejavu-core` (required by OpenCV and EasyOCR).
- Copies `requirements.txt` and installs all Python dependencies.
- Copies application code.
- Exposes port `8000`.
- Runs `uvicorn app.main:app --host 0.0.0.0 --port 8000`.

**docker-compose.yml** composes the service for production deployment.

**Note:** Ollama must run separately (on the host or as a sidecar) as it is not bundled in the Docker image. The API connects to `http://127.0.0.1:11434`.

---

## MCP Wikipedia Server (`mcp/wiki-server.js`)

A lightweight Node.js HTTP server that wraps the Wikipedia REST API and exposes it as an MCP-compatible tool.

- Listens on port `3333` (configurable via `WIKI_MCP_PORT`).
- `POST /wiki` — accepts `{"query": "Apache Kafka"}`, returns `{"title": "...", "extract": "...", "url": "..."}`.
- `GET /health` — returns `{"status": "ok", "service": "wiki-mcp-server"}`.
- Uses only Node.js built-in `http` and `https` modules (no npm dependencies).
- Normalises query terms with a `TITLE_MAP` (mirrors `_WIKI_TITLE_MAP` in `wiki_enrichment.py`).
- Rejects Wikipedia disambiguation pages.
- Can be registered as an MCP server in Claude Desktop's `claude_desktop_config.json`.

The Python `WikiEnrichment` module tries this server first (timeout 2s), then falls back to direct Wikipedia REST API calls, ensuring the pipeline works regardless of whether the MCP server is running.

---

## Key Design Decisions and Optimisations

**CPU-only performance on Ryzen 7 7730U:**
Every latency parameter (token count, context window, thread count, image resize bounds, OCR candidate count) has been tuned specifically for this CPU to achieve 60–120 second total end-to-end latency on a typical diagram.

**Multi-pass OCR with IoU deduplication:**
Running multiple preprocessing strategies and EasyOCR in both word and paragraph modes, then deduplicating by bounding box overlap, maximises text coverage without manual tuning per diagram style.

**Vision-grounded domain classification:**
The two-stage domain classification (OCR-only initial → OCR+LLM combined refined) ensures that even when OCR fails completely, the domain is correctly identified from the LLM's visual analysis, which sees the image directly.

**Smart Service→Database matching:**
The stem-based prefix matching algorithm prevents the naive "every service connects to every database" anti-pattern in the generated Mermaid diagram, producing architecturally accurate topology graphs.

**Visibility-verified security extraction:**
Security components are only extracted when the LLM explicitly confirms they are visible in the diagram, preventing false positives from negation prose ("No WAF is visible").

**LLM empty-response fallback:**
The OCR fallback path with title-case normalisation ensures the pipeline never silently returns empty results, even when Ollama is overloaded or the model times out.

**Wikipedia enrichment with architecture context:**
Rather than returning raw Wikipedia summaries, the enrichment module injects the actual diagram components into the definition, producing explanations like "Kafka enables asynchronous communication between Payment Service and Notification Service" instead of a generic textbook entry.

---

## Architecture Domains Supported

1. Microservices
2. Cloud Architecture (AWS, Azure, GCP)
3. Kubernetes
4. Data Engineering (Spark, Airflow, Kafka, Databricks, Snowflake)
5. Machine Learning / MLOps
6. Cybersecurity (SIEM, Zero Trust, WAF, mTLS)
7. DevOps / CI-CD (Jenkins, GitHub Actions, ArgoCD, Terraform)
8. IoT (MQTT, edge devices, telemetry)
9. Serverless (Lambda, Cloud Functions, Step Functions)
10. Enterprise Architecture (SAP, CRM, ERP, Salesforce, MuleSoft)
