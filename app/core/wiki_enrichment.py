"""
wiki_enrichment.py
==================
Wikipedia-based architecture enrichment with architecture-aware context.

How it works
------------
1. Identifies the key technologies / patterns detected in the diagram
   (domain, services, databases, queues, cloud providers, etc.).
2. For each term, queries the Wikipedia REST API (no API key required —
   it is a public read-only endpoint) to fetch a short summary.
3. **Enhances each definition with architecture-specific context** based on
   the diagram components:
      - Redis → "... serves as a distributed cache layer for User Service, 
                  Order Service, reducing database load..."
      - Kafka → "... enables asynchronous event-driven communication between 
                 Payment Service, Notification Service..."
      - API Gateway → "... routes incoming requests across User Service, 
                       Order Service, managing load balancing..."
4. Assembles the architecture-aware summaries into a single, human-readable 
   paragraph that explains what the diagram represents and how each major 
   technology is specifically used.

Key improvements over generic definitions:
  - Contextual roles: Cache layer, message broker, load balancer, etc.
  - Connected components: Named services and systems that use each technology
  - Architecture-specific benefits: Scalability, decoupling, fault tolerance
  - Diagram-aware explanations instead of textbook definitions

Wikipedia REST API used
-----------------------
  GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}

  - No authentication required.
  - Returns JSON with `extract` (plain-text summary) and `title`.
  - Rate limit: generous for read-only access (~200 req/s globally shared).
  - We add a 0.15 s sleep between requests to be a polite citizen.

MCP server integration
-----------------------
When the MCP wiki server (mcp/wiki-server.js) is running it exposes a
`wiki_search` tool that this module can call instead of direct HTTP.
The module tries the MCP server first (localhost:3333) and falls back
to direct Wikipedia REST API calls on any error, so the pipeline always
works even without the MCP server running.

Usage
-----
    from app.core.wiki_enrichment import WikiEnrichment

    paragraph = WikiEnrichment.enrich(
        domain        = "Microservices",
        services      = ["User Service", "Order Service"],
        databases     = ["PostgreSQL", "Redis"],
        queues        = ["Kafka"],
        cloud         = ["AWS"],
        gateways      = ["API Gateway"],
        observability = ["Prometheus", "Grafana"],
        containers    = ["Kubernetes", "Docker"],
    )
    # Returns: "This diagram depicts a **Microservices** architecture...
    #           **Redis**: ... serves as a distributed cache layer for 
    #                         User Service, Order Service, reducing database load..."
"""

from __future__ import annotations

import time
import re
import logging
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_WIKI_API_BASE  = "https://en.wikipedia.org/api/rest_v1/page/summary"
_MCP_SERVER_URL = "http://localhost:3333/wiki"   # local MCP server (optional)
_REQUEST_TIMEOUT = 5          # seconds per Wikipedia call
_INTER_REQUEST_SLEEP = 0.15   # polite delay between calls (seconds)
_MAX_TERMS = 8                # cap total Wikipedia lookups per diagram
_MAX_EXTRACT_SENTENCES = 2    # sentences to keep from each Wikipedia extract


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Map common diagram labels → canonical Wikipedia article titles.
_WIKI_TITLE_MAP: dict[str, str] = {
    # Architecture patterns
    "microservices":          "Microservices",
    "microservice":           "Microservices",
    "api gateway":            "API gateway",
    "event-driven":           "Event-driven architecture",
    "event driven":           "Event-driven architecture",
    "cqrs":                   "Command–query separation",
    "saga":                   "Choreography (computer science)",
    "service mesh":           "Service mesh",
    "serverless":             "Serverless computing",
    "load balancer":          "Load balancing (computing)",
    "reverse proxy":          "Reverse proxy",
    "cdn":                    "Content delivery network",
    # Databases
    "postgresql":             "PostgreSQL",
    "postgres":               "PostgreSQL",
    "mysql":                  "MySQL",
    "mongodb":                "MongoDB",
    "redis":                  "Redis",
    "cassandra":              "Apache Cassandra",
    "elasticsearch":          "Elasticsearch",
    "dynamodb":               "Amazon DynamoDB",
    "clickhouse":             "ClickHouse",
    "snowflake":              "Snowflake Inc.",
    # Messaging
    "kafka":                  "Apache Kafka",
    "apache kafka":           "Apache Kafka",
    "rabbitmq":               "RabbitMQ",
    "sqs":                    "Amazon Simple Queue Service",
    "amazon sqs":             "Amazon Simple Queue Service",
    # Cloud
    "aws":                    "Amazon Web Services",
    "amazon web services":    "Amazon Web Services",
    "azure":                  "Microsoft Azure",
    "gcp":                    "Google Cloud Platform",
    "google cloud":           "Google Cloud Platform",
    # Containers / orchestration
    "kubernetes":             "Kubernetes",
    "k8s":                    "Kubernetes",
    "docker":                 "Docker (software)",
    "helm":                   "Helm (package manager)",
    # Observability
    "prometheus":             "Prometheus (software)",
    "grafana":                "Grafana",
    "jaeger":                 "Jaeger (software)",
    "datadog":                "Datadog",
    "elk":                    "Elasticsearch",
    # CI/CD
    "jenkins":                "Jenkins (software)",
    "github actions":         "GitHub Actions",
    "argocd":                 "Argo CD",
    "terraform":              "Terraform (software)",
    # ML
    "mlflow":                 "MLflow",
    "kubeflow":               "Kubeflow",
    "feature store":          "Feature store",
    "vector database":        "Vector database",
    # Security
    "waf":                    "Web application firewall",
    "oauth":                  "OAuth",
    "jwt":                    "JSON Web Token",
    "zero trust":             "Zero trust security model",
    # Data engineering
    "apache spark":           "Apache Spark",
    "spark":                  "Apache Spark",
    "airflow":                "Apache Airflow",
    "dbt":                    "dbt (data build tool)",
    "databricks":             "Databricks",
}


def _canonical_wiki_title(term: str) -> str:
    """Return the best Wikipedia article title for *term*."""
    lower = term.lower().strip()
    if lower in _WIKI_TITLE_MAP:
        return _WIKI_TITLE_MAP[lower]
    # Strip generic suffixes before looking up.
    for suffix in (" service", " db", " database", " queue", " storage"):
        if lower.endswith(suffix):
            lower = lower[: -len(suffix)].strip()
            if lower in _WIKI_TITLE_MAP:
                return _WIKI_TITLE_MAP[lower]
    # Default: title-case the raw term.
    return term.title()


def _truncate_to_sentences(text: str, n: int) -> str:
    """Keep only the first *n* sentences of *text*."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:n])


# ---------------------------------------------------------------------------
# Wikipedia REST API caller
# ---------------------------------------------------------------------------

def _fetch_wiki_summary_direct(title: str) -> Optional[str]:
    """
    Fetch a plain-text extract from Wikipedia REST API.
    Returns None on any error (network, 404, etc.).
    """
    url = f"{_WIKI_API_BASE}/{requests.utils.quote(title)}"
    try:
        resp = requests.get(
            url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "ArchitectureAI/4.0 (diagram analysis tool)"},
        )
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "").strip()
            if extract and data.get("type") != "disambiguation":
                return _truncate_to_sentences(extract, _MAX_EXTRACT_SENTENCES)
    except Exception as exc:
        logger.debug(f"Wikipedia direct fetch failed for '{title}': {exc}")
    return None


def _fetch_wiki_summary_mcp(term: str) -> Optional[str]:
    """
    Try the local MCP wiki server (mcp/wiki-server.js).
    Returns None if the server is not running or returns an error.
    """
    try:
        resp = requests.post(
            _MCP_SERVER_URL,
            json={"query": term},
            timeout=2,
        )
        if resp.status_code == 200:
            data = resp.json()
            extract = data.get("extract", "").strip()
            if extract:
                return _truncate_to_sentences(extract, _MAX_EXTRACT_SENTENCES)
    except Exception:
        pass
    return None


def _fetch_wiki_summary(term: str) -> Optional[str]:
    """
    Fetch a Wikipedia summary for *term*.
    Tries MCP server first, then direct REST API.
    """
    # 1. Try MCP server (fast, local, preferred when running).
    summary = _fetch_wiki_summary_mcp(term)
    if summary:
        logger.debug(f"Wiki summary via MCP server for '{term}'")
        return summary

    # 2. Fall back to direct Wikipedia REST API.
    title   = _canonical_wiki_title(term)
    summary = _fetch_wiki_summary_direct(title)
    if summary:
        logger.debug(f"Wiki summary via direct API for '{term}' → '{title}'")
    return summary


# ---------------------------------------------------------------------------
# Term prioritisation
# ---------------------------------------------------------------------------

def _select_terms(
    domain:        str,
    services:      List[str],
    databases:     List[str],
    queues:        List[str],
    cloud:         List[str],
    gateways:      List[str],
    observability: List[str],
    containers:    List[str],
    storage:       List[str],
    security:      List[str],
) -> List[str]:
    """
    Pick the most informative terms to look up, capped at _MAX_TERMS.

    Priority order (most generic / foundational first so the paragraph
    reads naturally from "what is this" to "what technologies are used"):
      1. Domain (e.g. "Microservices")
      2. Gateways (e.g. "API Gateway")
      3. Queues (high-value, often unfamiliar to readers)
      4. Databases (concrete technology names only)
      5. Cloud (provider context)
      6. Containers / orchestration
      7. Observability tools (named tools only)
      8. Security (named tools only)
    """
    candidates: List[str] = []

    # Domain always first if it maps to a known article.
    if domain and domain.lower() in _WIKI_TITLE_MAP:
        candidates.append(domain)

    # Gateways
    for g in gateways:
        if g.lower() in _WIKI_TITLE_MAP:
            candidates.append(g)

    # Queues — high value
    for q in queues:
        if q.lower() in _WIKI_TITLE_MAP or "kafka" in q.lower() or "rabbit" in q.lower():
            candidates.append(q)

    # Databases — named technologies only (skip "User DB" etc.)
    _known_dbs = {
        "postgresql", "postgres", "mysql", "mongodb", "redis", "cassandra",
        "elasticsearch", "dynamodb", "clickhouse", "snowflake",
    }
    for db in databases:
        if db.lower().split()[0] in _known_dbs:
            candidates.append(db)

    # Cloud
    for c in cloud:
        if c.lower() in _WIKI_TITLE_MAP:
            candidates.append(c)

    # Containers
    for ct in containers:
        if ct.lower() in _WIKI_TITLE_MAP:
            candidates.append(ct)

    # Observability named tools
    _known_obs = {"prometheus", "grafana", "jaeger", "datadog", "elk"}
    for o in observability:
        if o.lower() in _known_obs:
            candidates.append(o)

    # Security named tools
    _known_sec = {"waf", "oauth", "jwt", "zero trust"}
    for s in security:
        if s.lower() in _known_sec:
            candidates.append(s)

    # Deduplicate while preserving order, cap at _MAX_TERMS.
    seen: set[str] = set()
    result: List[str] = []
    for term in candidates:
        key = term.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(term)
        if len(result) >= _MAX_TERMS:
            break

    return result


# ---------------------------------------------------------------------------
# Paragraph assembly
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Topology visualization helpers
# ---------------------------------------------------------------------------

def _build_gateway_topology(gateways: List[str], services: List[str]) -> str:
    """
    Build an ASCII topology diagram for API Gateway / load balancer.
    
    Example output:
    ```
    Web Browser / Mobile App
      ↓
    [API Gateway]
      ├→ User Service
      ├→ Order Service
      └→ Payment Service
    ```
    """
    if not gateways or not services:
        return ""
    
    gateway = gateways[0]
    lines = [
        "```",
        "Web Browser / Mobile App",
        "  ↓",
        f"[{gateway}]",
    ]
    
    for i, svc in enumerate(services[:5]):
        if i == len(services[:5]) - 1:
            lines.append(f"  └→ {svc}")
        else:
            lines.append(f"  ├→ {svc}")
    
    if len(services) > 5:
        lines.append(f"  ... and {len(services) - 5} more services")
    
    lines.append("```")
    return "\n".join(lines)


def _build_cache_topology(databases: List[str], services: List[str]) -> str:
    """
    Build an ASCII topology for cache layer.
    
    Example output:
    ```
    User Service  ┐
    Order Service ├→ [Redis Cache] ↔ PostgreSQL DB
    Payment Svc   ┘
    ```
    """
    if not services or len(services) < 2:
        return ""
    
    redis_db = None
    for db in databases:
        if "redis" in db.lower():
            redis_db = db
            break
    
    if not redis_db:
        return ""
    
    lines = ["```"]
    
    for i, svc in enumerate(services[:3]):
        if i == 0:
            lines.append(f"{svc:18} ┐")
        elif i == len(services[:3]) - 1:
            other_db = next((d for d in databases if "redis" not in d.lower()), "Database")
            lines.append(f"{svc:18} └→ [{redis_db}] ↔ [{other_db}]")
        else:
            lines.append(f"{svc:18} ├")
    
    if len(services) > 3:
        lines.append(f"... and {len(services) - 3} more services")
    
    lines.append("```")
    return "\n".join(lines)
    return "\n".join(lines) if len(services) > 1 else ""


def _build_queue_topology(queues: List[str], services: List[str]) -> str:
    """
    Build an ASCII topology for message queues.
    
    Example output:
    ```
    Order Service
    Payment Service   ────→  [Kafka/RabbitMQ]  ────→  Notification Service
    Shipping Service                                   Analytics Service
    ```
    """
    if not queues or len(services) < 2:
        return ""
    
    queue = queues[0]
    producers = services[:2]
    consumers = services[1:3] if len(services) > 1 else []
    
    lines = [
        "```",
        "Producers:",
    ]
    
    for prod in producers:
        lines.append(f"  {prod}")
    
    lines.extend([
        f"         ───→  [{queue}]  ───→  ",
        "Consumers:",
    ])
    
    for cons in consumers:
        lines.append(f"  {cons}")
    
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Architecture description builder
# ---------------------------------------------------------------------------

def _build_architecture_description(
    term: str,
    wiki_def: str,
    services: List[str],
    databases: List[str],
    queues: List[str],
    gateways: List[str],
) -> str:
    """
    Build an architecture-aware description for a component.
    
    Takes the generic Wikipedia definition and wraps it with context about
    how this component is actually used in the detected architecture.
    
    Examples:
      - Redis: "Redis serves as a distributed cache layer across..."
      - Kafka: "Kafka enables asynchronous event-driven communication..."
      - API Gateway: "The API Gateway routes incoming requests to..."
    """
    term_lower = term.lower().strip()
    
    # Databases: describe their role as storage / cache with topology
    if term_lower in ["redis", "memcached", "cache", "elasticache"]:
        connected_svcs = services[:3] if services else []
        topology = _build_cache_topology(databases, services)
        if connected_svcs:
            svc_list = ", ".join(connected_svcs)
            desc = (
                f"{wiki_def}\n\n**Topology:**\n{topology}\n\n"
                f"In this architecture, {term} serves as a distributed cache layer for "
                f"{svc_list}, reducing database load and improving response times."
            )
            return desc
        else:
            return f"{wiki_def} Here it functions as a caching layer to accelerate data access."
    
    if term_lower in ["postgresql", "postgres", "mysql", "mongodb", "cassandra", 
                      "dynamodb", "elasticsearch", "clickhouse", "oracle", "mariadb"]:
        return (
            f"{wiki_def} In this architecture, {term} stores and manages "
            f"persistent data for the microservices, ensuring data consistency and recovery."
        )
    
    # Message Queues/Brokers: describe async communication with topology
    if term_lower in ["kafka", "apache kafka", "rabbitmq", "activemq", "sqs", "amazon sqs"]:
        topology = _build_queue_topology(queues, services)
        if len(services) >= 2:
            svc_list = ", ".join(services[:4])
            extra = f", and {len(services) - 4} more" if len(services) > 4 else ""
            desc = (
                f"{wiki_def}\n\n**Topology:**\n{topology}\n\n"
                f"In this architecture, {term} enables asynchronous, decoupled communication "
                f"between {svc_list}{extra}, allowing services to scale independently and handle "
                f"traffic spikes gracefully."
            )
            return desc
        else:
            return (
                f"{wiki_def} Here it facilitates event-driven communication, "
                f"decoupling services for better scalability and resilience."
            )
    
    # Gateways: describe routing role with topology
    if term_lower in ["api gateway", "load balancer", "nginx", "haproxy", "kong", "traefik"]:
        topology = _build_gateway_topology(gateways, services)
        if services:
            svc_list = ", ".join(services[:4])
            extra = f", and {len(services) - 4} more" if len(services) > 4 else ""
            desc = (
                f"{wiki_def}\n\n**Topology:**\n{topology}\n\n"
                f"In this architecture, the {term} routes and distributes "
                f"incoming client requests across {svc_list}{extra}, managing load balancing, "
                f"rate limiting, and request authentication."
            )
            return desc
        else:
            return (
                f"{wiki_def} Here it serves as the entry point for all client requests "
                f"and manages request routing across backend services."
            )
    
    # Container Orchestration: describe deployment role
    if term_lower in ["kubernetes", "k8s", "docker", "docker swarm", "openshift"]:
        if services or gateways:
            services_or_gateways = (gateways + services)[:4]
            comp_list = ", ".join(services_or_gateways)
            return (
                f"{wiki_def} In this architecture, {term} orchestrates the deployment, "
                f"scaling, and management of containerized services like {comp_list}, "
                f"ensuring high availability and automated failover."
            )
        else:
            return (
                f"{wiki_def} Here it manages containerized microservices deployment "
                f"and scaling across a cluster infrastructure."
            )
    
    # Observability: describe monitoring role
    if term_lower in ["prometheus", "grafana", "jaeger", "datadog", "elk", "elasticsearch",
                      "kibana", "splunk", "newrelic", "dynatrace"]:
        if services:
            svc_list = ", ".join(services[:3])
            return (
                f"{wiki_def} In this architecture, {term} collects and visualizes metrics "
                f"and logs from {svc_list}, providing real-time observability into system "
                f"performance, latency, and resource utilization."
            )
        else:
            return (
                f"{wiki_def} Here it provides comprehensive monitoring and alerting "
                f"for system health, performance, and troubleshooting."
            )
    
    # Cloud Providers: describe infrastructure role
    if term_lower in ["aws", "amazon web services", "azure", "microsoft azure", 
                      "gcp", "google cloud", "google cloud platform"]:
        if services or gateways or databases:
            comp_list = ", ".join((gateways + services + databases)[:3])
            return (
                f"{wiki_def} In this architecture, {term} provides the cloud infrastructure "
                f"where {comp_list} and other components are deployed, offering managed services "
                f"for compute, storage, networking, and databases."
            )
        else:
            return (
                f"{wiki_def} Here it provides the underlying cloud infrastructure and managed "
                f"services for running the entire distributed system."
            )
    
    # Default: wrap Wikipedia definition with generic context
    return wiki_def


def _build_paragraph(
    domain:   str,
    term_summaries: List[tuple[str, str]],
    services: List[str],
    gateways: List[str],
    databases: List[str] = None,
    queues: List[str] = None,
) -> str:
    """
    Assemble term summaries into a single readable paragraph.

    Structure
    ---------
    1. Opening sentence: what kind of architecture this is.
    2. One sentence per technology with architecture context.
    3. Closing sentence: names the visible services (if any).
    """
    databases = databases or []
    queues = queues or []
    lines: List[str] = []

    # --- Opening ---
    if services or gateways:
        component_list = ", ".join((gateways + services)[:5])
        opening = (
            f"This diagram depicts a **{domain}** architecture "
            f"comprising components such as {component_list}."
        )
    else:
        opening = f"This diagram depicts a **{domain}** architecture."
    lines.append(opening)

    # --- Per-technology sentences (now with architecture context) ---
    for term, wiki_summary in term_summaries:
        if wiki_summary:
            arch_desc = _build_architecture_description(
                term=term,
                wiki_def=wiki_summary,
                services=services,
                databases=databases,
                queues=queues,
                gateways=gateways,
            )
            lines.append(f"**{term}**: {arch_desc}")

    # --- Closing ---
    if services:
        svc_str = ", ".join(services[:6])
        suffix  = f" and {len(services) - 6} more" if len(services) > 6 else ""
        lines.append(
            f"The visible microservices include: {svc_str}{suffix}."
        )

    return "  \n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class WikiEnrichment:
    """
    Enrich an architecture analysis with Wikipedia-sourced technology summaries.

    All HTTP calls are made with a short sleep between them to respect
    Wikipedia's rate-limit guidelines.  The entire enrichment is wrapped in
    a broad try/except so a network failure never crashes the main pipeline.
    """

    @staticmethod
    def enrich(
        domain:        str       = "Unknown",
        services:      List[str] = None,
        databases:     List[str] = None,
        queues:        List[str] = None,
        cloud:         List[str] = None,
        gateways:      List[str] = None,
        observability: List[str] = None,
        containers:    List[str] = None,
        storage:       List[str] = None,
        security:      List[str] = None,
    ) -> str:
        """
        Return a human-readable paragraph describing the architecture.

        Parameters
        ----------
        All parameters default to empty lists when not supplied.

        Returns
        -------
        str
            A Markdown-formatted paragraph.  Empty string on total failure.
        """
        services      = services      or []
        databases     = databases     or []
        queues        = queues        or []
        cloud         = cloud         or []
        gateways      = gateways      or []
        observability = observability or []
        containers    = containers    or []
        storage       = storage       or []
        security      = security      or []

        try:
            terms = _select_terms(
                domain=domain,
                services=services,
                databases=databases,
                queues=queues,
                cloud=cloud,
                gateways=gateways,
                observability=observability,
                containers=containers,
                storage=storage,
                security=security,
            )

            logger.info(
                f"WikiEnrichment: fetching {len(terms)} term(s): {terms}"
            )

            term_summaries: List[tuple[str, str]] = []
            for term in terms:
                summary = _fetch_wiki_summary(term)
                if summary:
                    term_summaries.append((term, summary))
                time.sleep(_INTER_REQUEST_SLEEP)

            paragraph = _build_paragraph(
                domain=domain,
                term_summaries=term_summaries,
                services=services,
                gateways=gateways,
                databases=databases,
                queues=queues,
            )

            logger.info(
                f"WikiEnrichment: assembled paragraph "
                f"({len(term_summaries)}/{len(terms)} terms found, "
                f"{len(paragraph)} chars)"
            )

            return paragraph

        except Exception as exc:
            logger.exception(f"WikiEnrichment failed: {exc}")
            return ""