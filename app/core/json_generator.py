"""
json_generator.py
=================
Extracts named architecture entities from the LLM's analysis text and
produces the structured JSON used by the API response, graph engine, and
Mermaid generator.

Fixes in this version
---------------------
1. CamelCase → spaced normalisation BEFORE deduplication.
   "AccountService"  →  "Account Service"
   "InventoryService" →  "Inventory Service"
   Applied to EVERY entity category, not just services.

2. Noise / false-positive filter.
   Phrases like "per service", "the service", "a service",
   "a database", "the storage" are suppressed by a block-list of
   leading articles / pronouns and a minimum word-quality check.

3. Deduplication after normalisation.
   Because we normalise first, both "Account Service" and
   "AccountService" collapse to the same canonical form before the
   set() call, so only one entry survives.

4. Security / observability fields are sourced ONLY from the LLM
   analysis text, filtered by a "not visible" / "not clearly visible"
   guard, so hallucinated security components that the LLM itself
   flagged as absent are not reported.

5. Generic bare keywords ("storage", "container") are blocked unless
   they appear as PART OF a real named component in the diagram.
"""

import re

from app.core.component_extractor import ComponentExtractor


class JSONGenerator:

    # ------------------------------------------------------------------ #
    # Noise block-list                                                     #
    # Words / phrases that look like components but are not.              #
    # Compared against the LOWER-CASED entity string.                     #
    # ------------------------------------------------------------------ #

    _NOISE_PREFIXES = {
        "the", "a", "an", "per", "each", "every", "this",
        "that", "their", "its", "our", "your",
    }

    _NOISE_EXACT = {
        "service", "services", "microservice", "microservices",
        "gateway", "gateways", "database", "databases",
        "storage", "storages", "queue", "queues",
        "container", "containers", "bucket", "buckets",
        "api", "rest", "grpc",
    }

    # ------------------------------------------------------------------ #
    # Regex patterns for named entity extraction                          #
    # These match REAL named components (capitalised proper nouns).       #
    # ------------------------------------------------------------------ #

    ENTITY_PATTERNS = {

        "services": [
            # "Account Service", "Payment Service" etc.
            r"\b([A-Z][A-Za-z0-9]+ Service)\b",
            # "AccountService", "InventoryService" etc. (CamelCase)
            r"\b([A-Z][a-z]+(?:[A-Z][a-z]+)+Service)\b",
            # "User-Service", "Order-Service"
            r"\b([A-Z][A-Za-z0-9]+-Service)\b",
        ],

        "gateways": [
            r"\b(API Gateway)\b",
            r"\b([A-Z][A-Za-z0-9]+ Gateway)\b",
            r"\b([A-Z][A-Za-z0-9]+Gateway)\b",
        ],

        "databases": [
            # Named service databases: "User DB", "Order DB", "Inventory DB" etc.
            # Matches [Title] DB — the most common pattern in microservice diagrams.
            r"\b([A-Z][A-Za-z0-9]+ DB)\b",
            # Named service databases with full word: "User Database", "Order Database"
            r"\b([A-Z][A-Za-z0-9]+ Database)\b",
            # Well-known database technologies
            r"\b(PostgreSQL|MySQL|MariaDB|Oracle|SQLite|MSSQL|SQL Server)\b",
            r"\b(MongoDB|CouchDB|DynamoDB|Cassandra|ScyllaDB|Firestore)\b",
            r"\b(Redis|Memcached|ElastiCache)\b",
            r"\b(Elasticsearch|OpenSearch|Solr)\b",
            r"\b(ClickHouse|Redshift|BigQuery|Snowflake)\b",
            r"\b(Database)\b",
        ],

        "queues": [
            r"\b(Apache Kafka|Kafka)\b",
            r"\b(RabbitMQ|ActiveMQ|ZeroMQ)\b",
            r"\b(Amazon SQS|SQS|SNS|EventBridge)\b",
            r"\b(Google Pub/Sub|Pub/Sub)\b",
            r"\b(Azure Service Bus|Service Bus)\b",
            r"\b(NATS|Pulsar|Celery)\b",
            r"\b(Queue|Message Queue|Event Bus|Message Broker)\b",
        ],

        "storage": [
            r"\b(Amazon S3|S3)\b",
            r"\b(Azure Blob Storage|Blob Storage|Azure Files)\b",
            r"\b(Google Cloud Storage|GCS)\b",
            r"\b(HDFS|EFS|NFS|EBS)\b",
            r"\b(MinIO|Ceph)\b",
        ],
    }

    # ------------------------------------------------------------------ #
    # Security keyword → section header mapping                           #
    # Used to check whether the LLM reported the component as visible.   #
    # ------------------------------------------------------------------ #

    _SECURITY_KEYWORDS = {
        "oauth":    "oauth",
        "jwt":      "jwt",
        "waf":      "waf",
        "firewall": "firewall",
        "vpn":      "vpn",
        "siem":     "siem",
        "soc":      "soc",
        "iam":      "iam",
        "mtls":     "mtls",
        "ssl":      "ssl",
        "tls":      "tls",
        "https":    "https",
    }

    _OBSERVABILITY_KEYWORDS = {
        # Named deployable observability tools
        "prometheus": "prometheus",
        "grafana":    "grafana",
        "elk":        "elk",
        "jaeger":     "jaeger",
        "zipkin":     "zipkin",
        "datadog":    "datadog",
        "newrelic":   "new relic",
        # Cross-cutting capabilities — visibility-verified but treated
        # as cross_cutting_concerns by the graph engine.
        "logging":    "logging",
        "monitoring": "monitoring",
        "metrics":    "metrics",
        "tracing":    "tracing",
        "alerting":   "alerting",
    }

    # Cross-cutting concern labels — capabilities, not deployable nodes.
    # The graph engine places these in a dedicated Observability subgraph.
    _CROSS_CUTTING_LABELS: frozenset = frozenset({
        "logging", "monitoring", "metrics", "tracing", "alerting",
        "audit", "rate limiting", "circuit breaker", "service mesh",
    })

    # ------------------------------------------------------------------ #
    # CamelCase → spaced name                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _camel_to_spaced(name: str) -> str:
        """
        Convert CamelCase component names to space-separated form.
        'AccountService'  → 'Account Service'
        'APIGateway'      → 'API Gateway'
        'MyHTTPService'   → 'My HTTP Service'
        """
        # Insert space before an uppercase letter that follows a lowercase letter
        # or before a sequence of uppercase letters followed by a lowercase letter.
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
        spaced = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
        return spaced.strip()

    # ------------------------------------------------------------------ #
    # Noise filtering                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_noise(entity: str) -> bool:
        """Return True if the entity is a noise / false-positive."""
        lower = entity.lower().strip()

        # Exact noise match.
        if lower in JSONGenerator._NOISE_EXACT:
            return True

        # Starts with a noise article/pronoun.
        first_word = lower.split()[0] if lower.split() else ""
        if first_word in JSONGenerator._NOISE_PREFIXES:
            return True

        # Too short or only one non-trivial word.
        words = [w for w in lower.split() if len(w) > 2]
        if len(words) == 0:
            return True

        return False

    # ------------------------------------------------------------------ #
    # Core entity cleaner                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _clean_and_normalise(raw: str) -> str:
        """
        1. Strip surrounding whitespace.
        2. Collapse internal whitespace.
        3. Convert CamelCase to space-separated.
        """
        value = raw.strip()
        value = re.sub(r"\s+", " ", value)
        value = JSONGenerator._camel_to_spaced(value)
        return value

    # ------------------------------------------------------------------ #
    # Visibility guard for security / observability                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _is_visible_in_analysis(keyword: str, analysis_lower: str) -> bool:
        """
        Return True only if the LLM analysis mentions the keyword AND does
        NOT immediately pair it with "not visible" / "not clearly visible".

        Strategy: find every line containing the keyword; at least one must
        not contain a "not … visible" phrase.
        """
        NOT_VISIBLE_PATTERNS = [
            r"not\s+(clearly\s+)?visible",
            r"not\s+present",
            r"not\s+detected",
            r"no\s+\w+\s+visible",
            r"none\s+visible",
        ]

        lines = analysis_lower.splitlines()
        relevant_lines = [l for l in lines if keyword in l]

        if not relevant_lines:
            return False

        for line in relevant_lines:
            line_lower = line.lower()
            is_negated = any(
                re.search(p, line_lower)
                for p in NOT_VISIBLE_PATTERNS
            )
            if not is_negated:
                return True   # at least one un-negated mention

        return False   # every mention was "not visible"

    # ------------------------------------------------------------------ #
    # Category extractors                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_named_entities(text: str) -> dict:
        """
        Extract named architecture entities using regex patterns.
        Applies normalisation + deduplication after extraction.
        """
        extracted: dict = {cat: [] for cat in JSONGenerator.ENTITY_PATTERNS}

        for category, patterns in JSONGenerator.ENTITY_PATTERNS.items():
            raw_values: list[str] = []

            for pattern in patterns:
                matches = re.findall(pattern, text, flags=re.IGNORECASE)
                # re.findall returns strings when there is one group.
                for m in matches:
                    raw_values.append(m if isinstance(m, str) else m[0])

            # Normalise → filter noise → deduplicate (case-insensitive).
            seen_lower: set = set()
            clean: list[str] = []

            for raw in raw_values:
                normalised = JSONGenerator._clean_and_normalise(raw)
                if JSONGenerator._is_noise(normalised):
                    continue
                if len(normalised) < 3:
                    continue
                key = normalised.lower()
                if key not in seen_lower:
                    seen_lower.add(key)
                    clean.append(normalised)

            extracted[category] = sorted(clean)

        return extracted

    @staticmethod
    def _extract_security(
        analysis: str,
        categories: dict,
    ) -> list[str]:
        """
        Extract security components that are CONFIRMED VISIBLE by the LLM.
        Suppresses anything the LLM said is "not visible".
        """
        lower = analysis.lower()
        found: list[str] = []

        for display_name, keyword in JSONGenerator._SECURITY_KEYWORDS.items():
            if JSONGenerator._is_visible_in_analysis(keyword, lower):
                found.append(display_name.upper() if len(display_name) <= 4 else display_name.title())

        return sorted(set(found))

    @staticmethod
    def _extract_observability(
        analysis: str,
        categories: dict,
    ) -> list[str]:
        """
        Extract observability tools that are CONFIRMED VISIBLE by the LLM.
        """
        lower = analysis.lower()
        found: list[str] = []

        for display_name, keyword in JSONGenerator._OBSERVABILITY_KEYWORDS.items():
            if JSONGenerator._is_visible_in_analysis(keyword, lower):
                found.append(display_name.title())

        return sorted(set(found))

    @staticmethod
    def _extract_cloud(analysis: str) -> list[str]:
        """Extract named cloud provider/service references."""
        cloud_patterns = [
            (r"\b(AWS|Amazon Web Services)\b",          "AWS"),
            (r"\b(Azure|Microsoft Azure)\b",            "Azure"),
            (r"\b(GCP|Google Cloud Platform|Google Cloud)\b", "GCP"),
            (r"\b(EC2)\b",                              "EC2"),
            (r"\b(EKS)\b",                              "EKS"),
            (r"\b(Lambda)\b",                           "Lambda"),
            (r"\b(AKS)\b",                              "AKS"),
            (r"\b(GKE)\b",                              "GKE"),
            (r"\b(Cloud Run)\b",                        "Cloud Run"),
        ]
        lower = analysis.lower()
        found: list[str] = []
        for pattern, label in cloud_patterns:
            if re.search(pattern, analysis, re.IGNORECASE):
                if JSONGenerator._is_visible_in_analysis(label.lower(), lower):
                    found.append(label)
        return sorted(set(found))

    @staticmethod
    def _extract_containers(analysis: str) -> list[str]:
        """Extract container/orchestration references that are visible."""
        container_patterns = [
            (r"\b(Docker)\b",      "Docker"),
            (r"\b(Kubernetes|K8s)\b", "Kubernetes"),
            (r"\b(Helm)\b",        "Helm"),
            (r"\b(Pod)\b",         "Pod"),
            (r"\b(ECS)\b",         "ECS"),
        ]
        lower = analysis.lower()
        found: list[str] = []
        for pattern, label in container_patterns:
            if re.search(pattern, analysis, re.IGNORECASE):
                if JSONGenerator._is_visible_in_analysis(label.lower(), lower):
                    found.append(label)
        return sorted(set(found))

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def generate(content: str) -> dict:
        """
        Parse LLM analysis text and return a structured component dictionary.

        All entity lists are:
          - CamelCase-normalised to spaced names
          - Deduplicated (case-insensitive)
          - Noise-filtered (articles, bare generic words)
          - Visibility-verified for security / observability
        """
        # Broad keyword categories from ComponentExtractor (kept for
        # backward compat but only used for cloud/container/observability
        # as a fallback signal).
        categories = ComponentExtractor.extract_all(content)

        # Named entity extraction (the primary source).
        entities = JSONGenerator._extract_named_entities(content)

        # Security and observability: visibility-verified only.
        security     = JSONGenerator._extract_security(content, categories)
        observability = JSONGenerator._extract_observability(content, categories)
        cloud        = JSONGenerator._extract_cloud(content)
        containers   = JSONGenerator._extract_containers(content)

        # Build detected_components from concrete named entities only.
        detected_components: list[str] = []
        for category in ["services", "gateways", "databases", "queues", "storage"]:
            detected_components.extend(entities[category])

        detected_components = sorted(set(detected_components))

        return {
            "detected_components": detected_components,
            "services":            entities["services"],
            "gateways":            entities["gateways"],
            "databases":           entities["databases"],
            "queues":              entities["queues"],
            "storage":             entities["storage"],
            "security":            security,
            "cloud":               cloud,
            "containers":          containers,
            "observability":       observability,
            "component_count":     len(detected_components),
            "analysis":            content,
        }
    # ------------------------------------------------------------------ #
    # OCR fallback: title-case normalisation + standard extraction        #
    # ------------------------------------------------------------------ #

    # Known acronyms that must stay all-caps even in title-case context.
    _ACRONYMS = {
        "API", "AWS", "GCP", "GKE", "EKS", "AKS", "ECS", "EC2", "S3",
        "UI", "DB", "MQ", "SQL", "HTTP", "REST", "URL", "RPC", "VPN",
        "JWT", "WAF", "CI", "CD", "SNS", "SQS", "IAM", "ACL", "SSL",
        "TLS", "DNS", "CDN", "TCP", "UDP", "K8S",
    }

    @staticmethod
    def _rejoin_split_ocr_tokens(text: str) -> str:
        """
        OCR sometimes splits a single logical label across two lines when the
        bounding box detection separates a multi-word phrase.  The most common
        case in architecture diagrams is "API" on one line and "GATEWAY" on the
        next, which the service/gateway regex cannot match as a unit.

        This method scans consecutive line pairs and merges them when they
        match a known two-word compound pattern.

        Known compounds (case-insensitive):
          API  + GATEWAY  → "API GATEWAY"
          LOAD + BALANCER → "LOAD BALANCER"
          MESSAGE + BROKER → "MESSAGE BROKER"
          SERVICE + MESH  → "SERVICE MESH"
          EVENT + BUS     → "EVENT BUS"
        """
        _COMPOUNDS = [
            (r"^API$",     r"^GATEWAY$",  "API GATEWAY"),
            (r"^LOAD$",    r"^BALANCER$", "LOAD BALANCER"),
            (r"^MESSAGE$", r"^BROKER$",   "MESSAGE BROKER"),
            (r"^SERVICE$", r"^MESH$",     "SERVICE MESH"),
            (r"^EVENT$",   r"^BUS$",      "EVENT BUS"),
        ]
        lines = text.splitlines()
        result = []
        i = 0
        while i < len(lines):
            merged = False
            if i + 1 < len(lines):
                a = lines[i].strip()
                b = lines[i + 1].strip()
                for pat1, pat2, compound in _COMPOUNDS:
                    if (re.match(pat1, a, re.IGNORECASE) and
                            re.match(pat2, b, re.IGNORECASE)):
                        result.append(compound)
                        i += 2
                        merged = True
                        break
            if not merged:
                result.append(lines[i])
                i += 1
        return "\n".join(result)

    @staticmethod
    def _normalize_ocr_text(ocr_text: str) -> str:
        """
        Convert all-caps OCR output to title-case so existing regex patterns
        can match correctly.

        Rules:
          - If a word is already mixed-case (RabbitMQ, Kafka) → preserve it.
          - If a word is a known acronym (API, AWS, SQL, DB) → keep all-caps.
          - If a word is all-caps (USER, SERVICE, GATEWAY) → title-case it.
          - Lowercase words → leave as-is (articles, prepositions).

        Examples:
          "USER SERVICE"         → "User Service"
          "API GATEWAY"          → "API Gateway"
          "USER DB"              → "User DB"
          "RabbitMQ"             → "RabbitMQ"          (mixed-case preserved)
          "NOTIFICATION SERVICE" → "Notification Service"
        """
        result = []
        for word in ocr_text.split():
            stripped = word.strip(".,;:()")
            if not stripped:
                result.append(word)
                continue

            # Already mixed-case (RabbitMQ, Kafka, Redis) — preserve exactly.
            has_lower = any(c.islower() for c in stripped)
            has_upper = any(c.isupper() for c in stripped)
            if has_lower and has_upper:
                result.append(word)
                continue

            # Known acronym — force all-caps.
            if stripped.upper() in JSONGenerator._ACRONYMS:
                result.append(word.replace(stripped, stripped.upper()))
                continue

            # All-caps word — title-case it.
            if stripped.isupper():
                result.append(word.replace(stripped, stripped.title()))
                continue

            # Already lowercase / other — leave as-is.
            result.append(word)

        return " ".join(result)

    @staticmethod
    def generate_from_ocr(ocr_text: str) -> dict:
        """
        Extract components directly from raw OCR text when the LLM response
        is empty or unavailable.

        The OCR engine produces all-caps tokens like "USER SERVICE",
        "API GATEWAY", "USER DB" that the standard regex patterns (which
        expect Title Case) would miss.  This method:

          1. Calls _rejoin_split_ocr_tokens() to merge split two-word labels
             ("API" / "GATEWAY" on separate lines → "API GATEWAY").
          2. Applies _normalize_ocr_text() line-by-line to convert
             "USER SERVICE" → "User Service", "USER DB" → "User DB",
             while preserving mixed-case names like "RabbitMQ".
          3. Calls the standard generate() on the normalised text so all
             existing extraction logic (dedup, noise filter, etc.) applies.

        Returns the same dict shape as generate().
        """
        # Step 1: merge split two-word compound labels (e.g. API / GATEWAY).
        rejoined = JSONGenerator._rejoin_split_ocr_tokens(ocr_text)

        # Step 2: normalise each line independently (all-caps → Title Case).
        normalized_lines = [
            JSONGenerator._normalize_ocr_text(line)
            for line in rejoined.splitlines()
        ]
        normalized_text = "\n".join(normalized_lines)

        # Step 3: re-use the standard extraction pipeline unchanged.
        result = JSONGenerator.generate(normalized_text)

        # Tag the result so callers can distinguish OCR-fallback output.
        result["ocr_fallback"] = True
        return result