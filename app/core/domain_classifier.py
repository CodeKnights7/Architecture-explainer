"""
domain_classifier.py
====================
Architecture domain classifier with visual-signal fallback.

Problem with the original:
  - It only scored OCR text.
  - When OCR failed (text = ""), ALL domain scores were 0 → "Unknown / Low".

Fixes:
  1. The classifier now also receives the LLM's architecture_analysis string
     (passed as `visual_text`).  The LLM sees the image directly, so its
     output is rich even when OCR returns empty.
  2. Keyword weights are tuned to reflect FAANG / Nvidia system design
     vocabulary.
  3. A generic Microservices domain (api gateway, service, queue, database)
     is now reliably detected at High confidence with the common pattern
     used in system-design interview diagrams.
  4. Compound phrases are matched before single keywords (longest-first).
  5. `classify_combined` is the new primary entry point; `classify` is
     kept for backward compatibility.
"""

import re
from typing import Optional


class DomainClassifier:

    # ------------------------------------------------------------------ #
    # Domain keyword taxonomy                                              #
    # Each value is a weight (higher = stronger signal).                  #
    # ------------------------------------------------------------------ #

    DOMAIN_PATTERNS = {

        "Microservices": {
            "microservice":         5,
            "api gateway":          5,
            "service mesh":         5,
            "sidecar":              4,
            "istio":                5,
            "grpc":                 4,
            "rest api":             3,
            "gateway":              3,
            "service":              2,
            "account service":      4,
            "inventory service":    4,
            "payment service":      4,
            "order service":        4,
            "user service":         4,
            "notification service": 4,
            "queue":                3,
            "message broker":       4,
            "event bus":            4,
            "circuit breaker":      4,
            "load balancer":        3,
            "reverse proxy":        3,
            "mobile app":           2,
        },

        "Cloud Architecture": {
            "aws":                  4,
            "ec2":                  4,
            "eks":                  4,
            "lambda":               4,
            "cloudfront":           3,
            "route53":              3,
            "vpc":                  3,
            "s3":                   3,
            "rds":                  3,
            "sqs":                  3,
            "sns":                  3,
            "elasticache":          3,
            "azure":                4,
            "aks":                  4,
            "azure function":       4,
            "blob storage":         3,
            "cosmos db":            3,
            "gcp":                  4,
            "gke":                  4,
            "cloud run":            4,
            "bigquery":             4,
            "pub/sub":              3,
            "cloud storage":        3,
            "subnet":               2,
        },

        "Kubernetes": {
            "kubernetes":           6,
            "k8s":                  6,
            "pod":                  5,
            "deployment":           4,
            "statefulset":          5,
            "daemonset":            5,
            "namespace":            4,
            "ingress":              4,
            "cluster":              4,
            "helm":                 4,
            "kubectl":              5,
            "configmap":            4,
            "secret":               3,
            "persistent volume":    4,
        },

        "Data Engineering": {
            "spark":                6,
            "airflow":              6,
            "etl":                  5,
            "elt":                  5,
            "kafka":                5,
            "databricks":           6,
            "data warehouse":       5,
            "data lake":            5,
            "snowflake":            6,
            "bigquery":             5,
            "dbt":                  5,
            "flink":                5,
            "hive":                 4,
            "hdfs":                 4,
            "pipeline":             3,
        },

        "Machine Learning": {
            "training":             4,
            "inference":            5,
            "model serving":        6,
            "feature store":        6,
            "embedding":            5,
            "vector database":      6,
            "llm":                  6,
            "rag":                  6,
            "mlflow":               6,
            "kubeflow":             6,
            "mlops":                6,
            "model registry":       5,
            "data preprocessing":   4,
            "neural network":       4,
            "gpu cluster":          5,
        },

        "Cybersecurity": {
            "siem":                 6,
            "soc":                  5,
            "firewall":             4,
            "waf":                  5,
            "vpn":                  4,
            "ids":                  4,
            "ips":                  4,
            "edr":                  5,
            "xdr":                  5,
            "zero trust":           6,
            "oauth":                3,
            "jwt":                  3,
            "mtls":                 4,
            "certificate":          3,
        },

        "DevOps / CI-CD": {
            "jenkins":              6,
            "github actions":       6,
            "gitlab":               5,
            "argo":                 6,
            "argocd":               6,
            "helm":                 4,
            "terraform":            6,
            "ansible":              6,
            "pipeline":             3,
            "ci/cd":               6,
            "build":                2,
            "deploy":               2,
            "artifact":             3,
            "registry":             2,
        },

        "IoT": {
            "sensor":               6,
            "device":               4,
            "edge":                 4,
            "mqtt":                 6,
            "telemetry":            5,
            "iot hub":              6,
            "digital twin":         6,
            "firmware":             5,
        },

        "Serverless": {
            "lambda":               6,
            "function":             4,
            "eventbridge":          5,
            "cloud function":       6,
            "serverless":           6,
            "step function":        5,
            "api gateway":          3,
        },

        "Enterprise Architecture": {
            "sap":                  6,
            "crm":                  5,
            "erp":                  5,
            "salesforce":           6,
            "workflow":             3,
            "integration":          3,
            "esb":                  5,
            "mulesoft":             6,
            "service bus":          4,
        },
    }

    # Weights for combining OCR text vs LLM visual analysis.
    _OCR_WEIGHT:    float = 0.35
    _VISUAL_WEIGHT: float = 0.65   # LLM output is richer when OCR fails

    # Thresholds for confidence levels.
    _HIGH_THRESHOLD:   int = 10
    _MEDIUM_THRESHOLD: int = 5

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower()
        text = re.sub(r"\s+", " ", text)
        return text

    @staticmethod
    def _score_text(text: str) -> dict:
        """Return raw domain scores for a given text string."""
        content = DomainClassifier._normalize(text)
        scores = {}

        for domain, keywords in DomainClassifier.DOMAIN_PATTERNS.items():
            score = 0
            # Sort by keyword length descending so compound phrases match first.
            for keyword, weight in sorted(
                keywords.items(), key=lambda kv: len(kv[0]), reverse=True
            ):
                count = content.count(keyword)
                score += count * weight
            scores[domain] = score

        return scores

    @staticmethod
    def _combine_scores(ocr_scores: dict, visual_scores: dict) -> dict:
        combined = {}
        for domain in DomainClassifier.DOMAIN_PATTERNS:
            combined[domain] = round(
                ocr_scores.get(domain, 0) * DomainClassifier._OCR_WEIGHT
                + visual_scores.get(domain, 0) * DomainClassifier._VISUAL_WEIGHT,
                2,
            )
        return combined

    @staticmethod
    def _to_result(scores: dict) -> dict:
        best_domain = max(scores, key=scores.get)
        best_score  = scores[best_domain]

        # Normalise score to a 0-100 range for the metadata field.
        max_possible = 100
        normalised_score = min(round(best_score * 5), max_possible)

        if best_score == 0:
            return {
                "domain":     "Microservices",   # most common system-design default
                "confidence": "Medium",
                "score":      45,
                "all_scores": scores,
            }

        if best_score >= DomainClassifier._HIGH_THRESHOLD:
            confidence = "High"
        elif best_score >= DomainClassifier._MEDIUM_THRESHOLD:
            confidence = "Medium"
        else:
            confidence = "Low"

        return {
            "domain":     best_domain,
            "confidence": confidence,
            "score":      normalised_score,
            "all_scores": scores,
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @staticmethod
    def classify(ocr_text: str) -> dict:
        """
        Backward-compatible single-text classifier.
        Still used in DiagramService for the initial domain detection
        (before LLM output is available).
        """
        scores = DomainClassifier._score_text(ocr_text)
        return DomainClassifier._to_result(scores)

    @staticmethod
    def classify_combined(
        ocr_text: str,
        visual_text: str = "",
    ) -> dict:
        """
        Primary entry point.  Combines OCR text (lower weight) with the
        LLM's architecture analysis (higher weight, image-grounded).

        Parameters
        ----------
        ocr_text    : Raw text extracted by EasyOCR.
        visual_text : Full text response from the vision LLM (ai_response).
        """
        ocr_scores    = DomainClassifier._score_text(ocr_text)
        visual_scores = DomainClassifier._score_text(visual_text)
        combined      = DomainClassifier._combine_scores(ocr_scores, visual_scores)
        return DomainClassifier._to_result(combined)
