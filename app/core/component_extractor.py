"""
component_extractor.py
======================
Broad keyword-based component category detector.

Role in the pipeline
--------------------
ComponentExtractor is a SUPPORTING module used by JSONGenerator as a
broad signal source for cloud, container, and observability categories.
The primary entity extraction (services, gateways, databases, queues,
storage) is handled by JSONGenerator's regex patterns, which are more
precise.

Fixes in this version
---------------------
1. The "security" keyword list no longer includes bare words like
   "firewall" and "waf" that were matching prose like "No WAF visible".
   Security extraction is now handled exclusively by JSONGenerator's
   visibility-verified `_extract_security()` method.

2. The "services" keyword list has been removed from this class entirely
   to prevent bare words like "service", "backend", "api" from producing
   garbage entries like "per service", "the service".

3. CamelCase normalisation is applied consistently via
   JSONGenerator._camel_to_spaced when this class's output is consumed.

4. `clean_component_name` now handles more common abbreviations.
"""

import re


class ComponentExtractor:

    # ------------------------------------------------------------------ #
    # Keyword catalog                                                      #
    # NOTE: "services" removed — handled precisely by JSONGenerator.      #
    # NOTE: "security" removed — handled with visibility check in         #
    #       JSONGenerator._extract_security().                            #
    # ------------------------------------------------------------------ #

    COMPONENT_CATALOG = {

        "gateways": [
            "api gateway",
            "ingress",
            "reverse proxy",
            "load balancer",
            "nginx",
            "traefik",
            "kong",
            "envoy",
        ],

        "databases": [
            "postgresql",
            "mysql",
            "mariadb",
            "mongodb",
            "redis",
            "oracle",
            "dynamodb",
            "cassandra",
            "elasticsearch",
            "clickhouse",
            "database",
        ],

        "queues": [
            "kafka",
            "rabbitmq",
            "activemq",
            "sqs",
            "pubsub",
            "eventbridge",
            "nats",
            "pulsar",
            "queue",
            "stream",
            "message broker",
            "event bus",
        ],

        "storage": [
            "s3",
            "efs",
            "bucket",
            "blob",
            "minio",
            "ceph",
            "hdfs",
        ],

        "cloud": [
            "aws",
            "ec2",
            "eks",
            "lambda",
            "azure",
            "aks",
            "azure function",
            "gcp",
            "gke",
            "cloud run",
            "cloudfront",
            "route53",
            "rds",
        ],

        "containers": [
            "docker",
            "kubernetes",
            "k8s",
            "pod",
            "helm",
            "ecs",
            "fargate",
        ],

        # Named observability tools — actual deployable components.
        "observability": [
            "prometheus",
            "grafana",
            "elk",
            "jaeger",
            "zipkin",
            "datadog",
            "new relic",
        ],

        # Cross-cutting concerns — behaviours / capabilities, NOT deployable
        # nodes.  Kept separate so the graph engine can place them in a
        # dedicated subgraph and the component count is not inflated by
        # generic words like "Logging" or "Tracing".
        "cross_cutting_concerns": [
            "logging",
            "monitoring",
            "metrics",
            "tracing",
            "alerting",
            "audit",
            "rate limiting",
            "circuit breaker",
            "service mesh",
        ],
    }

    # ------------------------------------------------------------------ #
    # Canonical display-name overrides                                     #
    # ------------------------------------------------------------------ #

    _DISPLAY_NAMES = {
        "api gateway":    "API Gateway",
        "aws":            "AWS",
        "ec2":            "EC2",
        "eks":            "EKS",
        "gcp":            "GCP",
        "gke":            "GKE",
        "aks":            "AKS",
        "k8s":            "Kubernetes",
        "sqs":            "SQS",
        "efs":            "EFS",
        "s3":             "S3",
        "elk":            "ELK",
        "grpc":           "gRPC",
        "oauth":          "OAuth",
        "jwt":            "JWT",
        "iam":            "IAM",
        "waf":            "WAF",
        "vpn":            "VPN",
        "siem":           "SIEM",
        "soc":            "SOC",
        "rds":            "RDS",
        "ecs":            "ECS",
    }

    @staticmethod
    def _display_name(keyword: str) -> str:
        lower = keyword.lower()
        if lower in ComponentExtractor._DISPLAY_NAMES:
            return ComponentExtractor._DISPLAY_NAMES[lower]
        return keyword.title()

    @staticmethod
    def normalize(text: str) -> str:
        text = text.lower()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def extract_category(
        content: str,
        category_keywords: list,
    ) -> list:
        """
        Find keywords present in content (longest-first to avoid substring
        matches on shorter keywords consuming the text first).
        Returns a deduplicated, sorted list of display names.
        """
        detected: list[str] = []
        content_lower = content.lower()

        for keyword in sorted(category_keywords, key=len, reverse=True):
            if keyword in content_lower:
                detected.append(ComponentExtractor._display_name(keyword))
                # Remove matched keyword so shorter substrings don't re-match.
                content_lower = content_lower.replace(keyword, "", 1)

        return sorted(set(detected))

    @staticmethod
    def extract_all(architecture_analysis: str) -> dict:
        """
        Extract all component categories from the LLM analysis string.
        Returns a dict keyed by category name.
        """
        content = ComponentExtractor.normalize(architecture_analysis)

        extracted: dict = {}
        all_components: list[str] = []

        for category, keywords in ComponentExtractor.COMPONENT_CATALOG.items():
            detected = ComponentExtractor.extract_category(content, keywords)
            extracted[category] = detected
            all_components.extend(detected)

        extracted["all_components"] = sorted(set(all_components))
        extracted["component_count"] = len(extracted["all_components"])

        return extracted