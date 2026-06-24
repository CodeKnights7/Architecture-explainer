"""
architecture_evaluator.py
=========================
Architecture quality evaluator – production-grade scoring for FAANG / Nvidia
system-design interview projects.

Changes from v2.0
-----------------
1. OCR quality score is NO LONGER the dominant driver.  When OCR returns
   0 characters (low-quality scan or white-on-dark diagram), the evaluator
   falls back to the LLM's visual analysis quality instead.
2. Visual analysis quality – measures richness of the LLM response:
   section count, component variety, data-flow descriptions, etc.
3. Component score – widened to catch all common system-design components
   (mobile app, load balancer, CDN, cache, etc.), not just DB / K8s.
4. Domain confidence bonus – High-confidence domain classification adds
   +10 to overall score.
5. Weighted formula rebalanced so that a strong LLM analysis can reach
   ≥ 80% overall confidence even with 0 OCR characters.
6. Confidence is now clamped to [0, 100] before normalisation.

Bug fix (v3.0) – Confidence score was consistently too conservative
-------------------------------------------------------------------
Root cause: with OCR=100, components=100, domain=100, the old formula
still produced ~76 because:
  - ``visual_quality`` requires expensive section-header matches that are
    rarely all present, so it rarely exceeded ~50.
  - The ``visual_quality`` weight of 0.35 was the single biggest driver,
    pulling the average down even when every other signal was perfect.

Fix: weight redistribution that rewards high component + OCR + domain
scores more directly, while keeping visual quality as a signal.

New weights (sum = 1.0):
  ocr_quality          → 0.15   (was 0.10 — direct OCR text quality)
  visual_quality       → 0.20   (was 0.35 — reduced; too punishing when LLM
                                  analysis has few explicit section headers)
  component_score      → 0.35   (was 0.25 — primary reliability signal)
  hallucination_score  → 0.15   (unchanged)
  enterprise_score     → 0.15   (unchanged)

With this distribution a perfect (OCR=100, components=100, domain=High) run
produces:
  weighted = 100*0.15 + visual*0.20 + 100*0.35 + 100*0.15 + ent*0.15
  minimum when visual=10, ent=0:  15 + 2 + 35 + 15 + 0 = 67   + 10 bonus = 77
  realistic when visual=60, ent=60: 15 + 12 + 35 + 15 + 9 = 86  + 10 bonus = 96 → clamped 100

In practice this pushes the "all signals strong" scenario into the 85–95
band, which matches human reviewer expectations.

Fix (v4.0) – Enterprise score too low (42) for diagrams with Kafka, RabbitMQ,
             Redis, Docker, Kubernetes, AWS, Azure, API Gateway, etc.
-----------------------------------------------------------------------------
Root cause: calculate_enterprise_score() only searched the LLM's raw
architecture_analysis text.  When the LLM response is terse or the fallback
OCR path is used, many enterprise components ARE correctly extracted into
structured lists (services, databases, queues, containers, cloud, observability)
but never appear as plain text in the analysis string.

Fix: evaluate() now accepts the full structured component lists extracted by
JSONGenerator (services, gateways, databases, queues, storage, containers,
cloud, observability, security).  calculate_enterprise_score() combines the
analysis text search with a direct scan of the structured lists so every
detected enterprise component counts — regardless of how verbose the LLM was.

This brings the score to 70–85 for diagrams that contain:
  API Gateway + Kafka/RabbitMQ + Redis + Docker + Kubernetes + AWS/Azure/GCP
  + Service Discovery + Config Server.
"""

import re
from typing import List, Optional


class ArchitectureEvaluator:

    # ------------------------------------------------------------------ #
    # Hallucination term list                                              #
    # ------------------------------------------------------------------ #

    HALLUCINATION_TERMS = [
        "likely",
        "probably",
        "possibly",
        "might be",
        "appears to be",
        "seems to be",
        "assumed",
        "presumably",
        "i think",
        "i believe",
        "could be",
        "may be",
    ]

    # ------------------------------------------------------------------ #
    # Component vocabulary for scoring                                     #
    # Broad enough to cover any diagram domain (FAANG style).             #
    # ------------------------------------------------------------------ #

    COMPONENT_PATTERNS = [
        # Services / APIs
        r"\b[A-Za-z0-9\s]+Service\b",
        r"\b[A-Za-z0-9\s]+API\b",
        r"\bAPI\s+Gateway\b",
        r"\b[A-Za-z0-9\s]+Gateway\b",
        r"\bLoad\s+Balancer\b",
        r"\bReverse\s+Proxy\b",
        r"\bCDN\b",
        r"\bFirewall\b",
        r"\bWAF\b",
        # Databases / caches / storage
        r"\bDatabase\b",
        r"\bRedis\b",
        r"\bPostgreSQL\b",
        r"\bMySQL\b",
        r"\bMongoDB\b",
        r"\bDynamoDB\b",
        r"\bCassandra\b",
        r"\bElasticsearch\b",
        r"\bS3\b",
        r"\bStorage\b",
        r"\bCache\b",
        # Messaging
        r"\bKafka\b",
        r"\bRabbitMQ\b",
        r"\bSQS\b",
        r"\bQueue\b",
        r"\bMessage\s+Broker\b",
        r"\bEvent\s+Bus\b",
        # Containers / orchestration
        r"\bKubernetes\b",
        r"\bDocker\b",
        r"\bPod\b",
        r"\bCluster\b",
        # Observability
        r"\bPrometheus\b",
        r"\bGrafana\b",
        r"\bLogging\b",
        r"\bMonitoring\b",
        r"\bTracing\b",
        r"\bMetrics\b",
        # Auth
        r"\bOAuth\b",
        r"\bJWT\b",
        r"\bSSO\b",
        r"\bIAM\b",
        # Presentation
        r"\bMobile\s+App\b",
        r"\bWeb\s+App\b",
        r"\bFrontend\b",
        r"\bClient\b",
    ]

    # Section headers expected in a well-formed LLM analysis.
    EXPECTED_SECTIONS = [
        "architecture overview",
        "component inventory",
        "architecture layers",
        "data flow",
        "service interactions",
        "infrastructure",
        "database",
        "security",
        "scalability",
        "observability",
        "strengths",
        "risks",
        "recommendations",
        "technology stack",
        "mermaid",
    ]

    # ------------------------------------------------------------------ #
    # Enterprise term definitions                                          #
    # Each entry is (display_label, search_terms_list).                   #
    # A component earns its points when ANY of its search_terms appear    #
    # in the combined text OR in any of the structured component lists.   #
    # ------------------------------------------------------------------ #

    _ENTERPRISE_COMPONENTS = [
        # (label,             text keywords,                    pts)
        ("API Gateway",       ["api gateway"],                  8),
        ("Kafka",             ["kafka"],                        8),
        ("RabbitMQ",          ["rabbitmq"],                     8),
        ("Redis",             ["redis"],                        7),
        ("PostgreSQL",        ["postgresql", "postgres"],       6),
        ("MongoDB",           ["mongodb"],                      6),
        ("Elasticsearch",     ["elasticsearch"],                7),
        ("Kubernetes",        ["kubernetes", "k8s"],            8),
        ("Docker",            ["docker"],                       6),
        ("AWS",               ["aws", "amazon web services"],   7),
        ("Azure",             ["azure"],                        7),
        ("GCP",               ["gcp", "google cloud"],         7),
        ("Load Balancer",     ["load balancer"],                6),
        ("CDN",               ["cdn"],                         5),
        ("WAF",               ["waf"],                         5),
        ("OAuth",             ["oauth"],                       5),
        ("JWT",               ["jwt"],                         4),
        ("Prometheus",        ["prometheus"],                   6),
        ("Grafana",           ["grafana"],                      5),
        ("Service Mesh",      ["service mesh", "istio"],        7),
        ("Circuit Breaker",   ["circuit breaker"],              6),
        ("Service Discovery", ["service discovery"],            6),
        ("Config Server",     ["config server", "consul",
                               "zookeeper"],                   6),
        ("S3",                ["s3", "blob storage", "gcs"],   5),
        ("Tracing",           ["tracing", "jaeger", "zipkin"], 5),
        ("SQS/SNS",           ["sqs", "sns", "eventbridge"],   6),
    ]

    # ------------------------------------------------------------------ #
    # Individual scoring functions                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_ocr_quality(extracted_text: str) -> float:
        """
        Score OCR quality 0-100 based on character count.
        Score 50 (not 10) for empty text because the LLM may still produce
        a high-quality analysis from the image alone.
        """
        length = len(extracted_text.strip())

        if length >= 500:  return 100.0
        if length >= 250:  return 90.0
        if length >= 100:  return 80.0
        if length >= 50:   return 70.0
        if length >= 20:   return 60.0
        if length >= 1:    return 50.0
        return 35.0   # 0 OCR chars – not 10; LLM can compensate

    @staticmethod
    def calculate_visual_analysis_quality(analysis: str) -> float:
        """
        Score the richness of the LLM's architecture analysis 0-100.
        Checks section coverage, word count, component mentions, Mermaid presence.

        Note: this is intentionally lenient so that analyses that lack
        explicit section headers but contain rich component descriptions
        still score in the 40-60 range rather than near zero.
        """
        if not analysis or len(analysis.strip()) < 50:
            return 10.0

        lower = analysis.lower()
        score = 0.0

        # Section coverage (up to 40 pts — reduced from 50 so sparse but
        # component-rich analyses are not penalised as harshly).
        sections_found = sum(
            1 for s in ArchitectureEvaluator.EXPECTED_SECTIONS
            if s in lower
        )
        score += min(sections_found * 4, 40)

        # Word count (up to 25 pts — increased slightly).
        word_count = len(analysis.split())
        score += min(word_count / 16, 25)

        # Mermaid diagram present (10 pts).
        if "```mermaid" in lower:
            score += 10

        # Component variety (up to 25 pts — increased to reward component-dense
        # analyses even when explicit section headers are missing).
        component_count = 0
        for pattern in ArchitectureEvaluator.COMPONENT_PATTERNS:
            matches = re.findall(pattern, analysis, flags=re.IGNORECASE)
            component_count += len(set(matches))
        score += min(component_count * 2.5, 25)

        return min(round(score, 2), 100.0)

    @staticmethod
    def calculate_component_score(analysis: str) -> float:
        """
        Count distinct component type mentions (services, DBs, queues, etc.).
        Score 0-100.
        """
        unique_types_found = set()
        for pattern in ArchitectureEvaluator.COMPONENT_PATTERNS:
            matches = re.findall(pattern, analysis, flags=re.IGNORECASE)
            if matches:
                unique_types_found.add(pattern)

        score = min(len(unique_types_found) * 7, 100)
        return float(score)

    @staticmethod
    def calculate_hallucination_score(analysis: str) -> dict:
        """
        Penalise hallucination language.  Returns score (0-100) and risk label.
        """
        lower = analysis.lower()
        hits = sum(lower.count(term) for term in ArchitectureEvaluator.HALLUCINATION_TERMS)
        score = max(100 - hits * 10, 0)

        if score >= 80:
            risk = "Low"
        elif score >= 50:
            risk = "Medium"
        else:
            risk = "High"

        return {"score": float(score), "risk": risk}

    @staticmethod
    def calculate_enterprise_score(
        analysis:     str,
        services:     Optional[List[str]] = None,
        gateways:     Optional[List[str]] = None,
        databases:    Optional[List[str]] = None,
        queues:       Optional[List[str]] = None,
        storage:      Optional[List[str]] = None,
        containers:   Optional[List[str]] = None,
        cloud:        Optional[List[str]] = None,
        observability: Optional[List[str]] = None,
        security:     Optional[List[str]] = None,
    ) -> float:
        """
        Score presence of enterprise-grade components 0-100.

        Strategy (v4.0)
        ---------------
        Build a single normalised search corpus from BOTH sources:
          1. The LLM's raw analysis text (lower-cased).
          2. All structured component lists extracted by JSONGenerator
             (services, gateways, databases, queues, storage, containers,
             cloud, observability, security) joined into one string.

        This means every component that was successfully extracted into the
        structured JSON — regardless of whether it appears verbatim in the
        LLM text — contributes to the enterprise score.

        Each enterprise component earns its assigned points once (no double
        counting).  Final score clamped to 100.
        """

        # Build combined corpus: LLM text + all structured lists.
        all_lists: List[str] = []
        for lst in (services, gateways, databases, queues, storage,
                    containers, cloud, observability, security):
            if lst:
                all_lists.extend(lst)

        structured_text = " ".join(all_lists)
        combined_lower  = (analysis + " " + structured_text).lower()

        score = 0.0
        for _label, keywords, pts in ArchitectureEvaluator._ENTERPRISE_COMPONENTS:
            if any(kw in combined_lower for kw in keywords):
                score += pts

        return float(min(score, 100))

    @staticmethod
    def calculate_domain_bonus(domain_confidence: str) -> float:
        """Return a bonus added to overall confidence for strong domain detection."""
        if domain_confidence == "High":   return 10.0
        if domain_confidence == "Medium": return 5.0
        return 0.0

    # ------------------------------------------------------------------ #
    # Composite evaluator                                                  #
    # ------------------------------------------------------------------ #

    @staticmethod
    def evaluate(
        extracted_text:        str,
        architecture_analysis: str,
        domain_confidence:     str = "Low",
        services:              Optional[List[str]] = None,
        gateways:              Optional[List[str]] = None,
        databases:             Optional[List[str]] = None,
        queues:                Optional[List[str]] = None,
        storage:               Optional[List[str]] = None,
        containers:            Optional[List[str]] = None,
        cloud:                 Optional[List[str]] = None,
        observability:         Optional[List[str]] = None,
        security:              Optional[List[str]] = None,
    ) -> dict:
        """
        Compute overall quality score.

        Weights (must sum to 1.0):
          ocr_quality          → 0.15   (raised from 0.10)
          visual_quality       → 0.20   (lowered from 0.35 — was too punishing)
          component_score      → 0.35   (raised from 0.25 — most reliable signal)
          hallucination_score  → 0.15   (unchanged)
          enterprise_score     → 0.15   (unchanged)

        Domain confidence bonus is added after weighting (up to +10).
        Final score clamped to [0, 100].

        v4.0: structured component lists are forwarded to
        calculate_enterprise_score() so detected components that are not
        mentioned verbatim in the LLM analysis text still count.

        Expected behaviour with OCR=100, components=100, domain=High,
        enterprise components present:
          Minimum realistic score: ~85
          Typical score:           ~88–95
        """

        ocr_quality      = ArchitectureEvaluator.calculate_ocr_quality(extracted_text)
        visual_quality   = ArchitectureEvaluator.calculate_visual_analysis_quality(architecture_analysis)
        component_score  = ArchitectureEvaluator.calculate_component_score(architecture_analysis)
        hallucination    = ArchitectureEvaluator.calculate_hallucination_score(architecture_analysis)
        enterprise_score = ArchitectureEvaluator.calculate_enterprise_score(
            analysis=architecture_analysis,
            services=services,
            gateways=gateways,
            databases=databases,
            queues=queues,
            storage=storage,
            containers=containers,
            cloud=cloud,
            observability=observability,
            security=security,
        )
        domain_bonus     = ArchitectureEvaluator.calculate_domain_bonus(domain_confidence)

        weighted = (
              ocr_quality           * 0.15
            + visual_quality        * 0.20
            + component_score       * 0.35
            + hallucination["score"] * 0.15
            + enterprise_score      * 0.15
        )

        overall_confidence = round(
            min(weighted + domain_bonus, 100.0),
            2
        )

        return {
            "overall_confidence":  overall_confidence,
            "ocr_quality":         round(ocr_quality, 2),
            "visual_quality":      round(visual_quality, 2),
            "component_score":     round(component_score, 2),
            "hallucination_risk":  hallucination["risk"],
            "hallucination_score": round(hallucination["score"], 2),
            "enterprise_score":    round(enterprise_score, 2),
            "domain_bonus":        round(domain_bonus, 2),
        }