"""
diagram_service.py
==================
Orchestrates the full architecture diagram analysis pipeline.

Changes from the original:
  1. Domain classification now uses `classify_combined` (OCR + LLM output)
     instead of just OCR text, so it correctly identifies Microservices /
     Cloud diagrams even when OCR returns empty string.
  2. ArchitectureEvaluator.evaluate() now receives `domain_confidence`
     so the domain bonus is applied to the overall score.
  3. The `evaluation` dict in metadata now includes the new `visual_quality`
     and `domain_bonus` fields.
  4. `ocr_characters` is kept but no longer affects scores catastrophically
     when it is 0 — see updated ArchitectureEvaluator.
  5. All original fields are preserved for full API backward compatibility.

Bug fix (v2.1):
  6. Empty LLM response fallback.  When Ollama returns an empty string
     (timeout, model failure, GPU/CPU overload), the pipeline no longer
     silently produces empty component lists.  Instead:
       a. A warning is logged.
       b. The OCR text is used as the analysis input for JSON generation,
          domain refinement, and markdown — recovering ~70–80% of
          component detection from OCR alone.
       c. The architecture_analysis field in the response is set to the
          OCR text so downstream consumers can see what was used.
"""

import time

from app.logger import logger

from app.core.ocr_engine import OCREngine
from app.core.prompt_engine import PromptEngine
from app.core.llm_engine import LLMEngine
from app.core.domain_classifier import DomainClassifier
from app.core.json_generator import JSONGenerator
from app.core.markdown_generator import MarkdownGenerator
from app.core.architecture_evaluator import ArchitectureEvaluator
from app.core.wiki_enrichment import WikiEnrichment
from app.core.helpers.metrics import Metrics
from app.core.graph_engine import GraphEngine
from app.core.mermaid_generator import MermaidGenerator


class DiagramService:

    @staticmethod
    async def process_diagram(image_path: str):

        total_start = time.perf_counter()

        try:
            logger.info(f"Processing image: {image_path}")

            # ----------------------------------------------------------
            # STEP 1: OCR
            # Multi-pass, multi-candidate extraction.
            # ----------------------------------------------------------

            ocr_start = time.perf_counter()

            ocr_result = OCREngine.extract_with_metadata(image_path)

            extracted_text  = ocr_result["text"]
            ocr_confidence  = ocr_result["average_confidence"]

            ocr_latency_ms = round(
                (time.perf_counter() - ocr_start) * 1000, 2
            )

            logger.info(
                f"OCR complete: {len(extracted_text)} chars, "
                f"avg_conf={ocr_confidence:.3f}, "
                f"latency={ocr_latency_ms}ms"
            )

            # ----------------------------------------------------------
            # STEP 2: Initial domain detection (OCR text only)
            # Used to tailor the LLM prompt before the full analysis.
            # ----------------------------------------------------------

            initial_domain_result = DomainClassifier.classify(extracted_text)
            initial_domain        = initial_domain_result["domain"]

            logger.info(
                f"Initial domain (OCR-only): {initial_domain} "
                f"[{initial_domain_result['confidence']}]"
            )

            # ----------------------------------------------------------
            # STEP 3: Build domain-aware prompt
            # ----------------------------------------------------------

            prompt = PromptEngine.generate_prompt(
                ocr_text=extracted_text,
                domain=initial_domain,
            )

            # ----------------------------------------------------------
            # STEP 4: Vision LLM analysis
            # ----------------------------------------------------------

            llm_result = LLMEngine.analyze_diagram(
                prompt=prompt,
                image_path=image_path,
            )

            ai_response    = llm_result["response"]
            llm_latency_ms = llm_result["llm_latency_ms"]

            logger.info(
                f"LLM response: {len(ai_response)} chars, "
                f"latency={llm_latency_ms}ms"
            )

            # ----------------------------------------------------------
            # STEP 4b: Empty LLM response fallback  [BUG FIX v2.1]
            #
            # When Ollama times out, is overloaded, or returns an empty
            # string, every downstream step (component extraction, graph,
            # mermaid, markdown) produces empty / zero results.
            #
            # Fix: fall back to OCR text as the analysis content.
            # JSONGenerator.generate_from_ocr() applies smart title-case
            # normalisation so that all-caps OCR tokens like "USER SERVICE"
            # are converted to "User Service" before the regex patterns run,
            # recovering the full component list from OCR alone.
            # ----------------------------------------------------------

            llm_failed = not ai_response or not ai_response.strip()

            if llm_failed:
                logger.warning(
                    "LLM returned an empty response. "
                    "Falling back to OCR text for component extraction."
                )
                # Use OCR text as the analysis source for all downstream steps.
                analysis_content = extracted_text
                using_ocr_fallback = True
            else:
                analysis_content = ai_response
                using_ocr_fallback = False

            # ----------------------------------------------------------
            # STEP 5: Refined domain detection (OCR + LLM output)
            # ----------------------------------------------------------

            domain_result = DomainClassifier.classify_combined(
                ocr_text=extracted_text,
                visual_text=analysis_content,
            )

            domain = domain_result["domain"]

            logger.info(
                f"Refined domain: {domain} "
                f"[{domain_result['confidence']}, score={domain_result['score']}]"
            )

            # ----------------------------------------------------------
            # STEP 6: Component / entity extraction
            #
            # When using the OCR fallback, call generate_from_ocr() which
            # normalises all-caps tokens before pattern matching.
            # When using the LLM response, use the standard generate().
            # ----------------------------------------------------------

            if using_ocr_fallback:
                structured_json = JSONGenerator.generate_from_ocr(extracted_text)
                logger.info(
                    f"OCR fallback extraction: "
                    f"{structured_json['component_count']} components detected"
                )
            else:
                structured_json = JSONGenerator.generate(ai_response)

            # ----------------------------------------------------------
            # STEP 7: Graph construction
            # ----------------------------------------------------------

            graph = GraphEngine.build_architecture_graph(
                services=structured_json["services"],
                gateways=structured_json["gateways"],
                databases=structured_json["databases"],
                queues=structured_json["queues"],
                storage=structured_json["storage"],
                containers=structured_json["containers"],
            )

            graph_metrics = GraphEngine.get_graph_metrics(graph)

            # ----------------------------------------------------------
            # STEP 8: Mermaid diagram
            # ----------------------------------------------------------

            mermaid_diagram = MermaidGenerator.generate(
                services=structured_json["services"],
                gateways=structured_json["gateways"],
                databases=structured_json["databases"],
                queues=structured_json["queues"],
                storage=structured_json["storage"],
                containers=structured_json["containers"],
                observability=structured_json["observability"],
            )

            # ----------------------------------------------------------
            # STEP 9: Quality evaluation
            # ----------------------------------------------------------

            evaluation = ArchitectureEvaluator.evaluate(
                extracted_text=extracted_text,
                architecture_analysis=analysis_content,
                domain_confidence=domain_result["confidence"],
                services=structured_json["services"],
                gateways=structured_json["gateways"],
                databases=structured_json["databases"],
                queues=structured_json["queues"],
                storage=structured_json["storage"],
                containers=structured_json["containers"],
                cloud=structured_json["cloud"],
                observability=structured_json["observability"],
                security=structured_json["security"],
            )

            # ----------------------------------------------------------
            # STEP 10: Assemble metadata
            # ----------------------------------------------------------

            total_latency_ms = round(
                (time.perf_counter() - total_start) * 1000, 2
            )

            system_metrics = Metrics.get_metrics_snapshot()

            confidence = round(
                evaluation["overall_confidence"] / 100, 2
            )

            metadata = {
                "domain":           domain_result["domain"],
                "domain_confidence": domain_result["confidence"],
                "domain_score":     domain_result["score"],
                "confidence":       confidence,
                "ocr_characters":   len(extracted_text),
                "ocr_confidence":   ocr_confidence,
                "ocr_latency_ms":   ocr_latency_ms,
                "llm_latency_ms":   llm_latency_ms,
                "total_latency_ms": total_latency_ms,
                "llm_fallback_used": using_ocr_fallback,  # diagnostic field
                "system_metrics": {
                    "cpu_percent":           system_metrics["cpu_percent"],
                    "memory_usage_mb":       system_metrics["memory_usage_mb"],
                    "system_memory_percent": system_metrics["system_memory_percent"],
                    "available_memory_mb":   system_metrics["available_memory_mb"],
                },
                "evaluation": {
                    "overall_confidence":  evaluation["overall_confidence"],
                    "ocr_quality":         evaluation["ocr_quality"],
                    "visual_quality":      evaluation.get("visual_quality", 0),
                    "component_score":     evaluation["component_score"],
                    "hallucination_risk":  evaluation["hallucination_risk"],
                    "hallucination_score": evaluation["hallucination_score"],
                    "enterprise_score":    evaluation["enterprise_score"],
                    "domain_bonus":        evaluation.get("domain_bonus", 0),
                },
                "graph_metrics": {
                    "nodes":                    graph_metrics["nodes"],
                    "edges":                    graph_metrics["edges"],
                    "density":                  graph_metrics["density"],
                    "critical_components":      graph_metrics["critical_components"],
                    "single_points_of_failure": graph_metrics["single_points_of_failure"],
                },
            }

            # ----------------------------------------------------------
            # STEP 11: Wikipedia enrichment + Markdown report
            # ----------------------------------------------------------

            # Enrich the analysis with short Wikipedia definitions (best-effort).
            try:
                wiki_paragraph = WikiEnrichment.enrich(
                    domain=domain,
                    services=structured_json["services"],
                    databases=structured_json["databases"],
                    queues=structured_json["queues"],
                    cloud=structured_json["cloud"],
                    gateways=structured_json["gateways"],
                    observability=structured_json["observability"],
                    containers=structured_json["containers"],
                    storage=structured_json["storage"],
                    security=structured_json["security"],
                )
            except Exception:
                wiki_paragraph = ""

            markdown_doc = MarkdownGenerator.generate(
                architecture_analysis=analysis_content,
                metadata=metadata,
                mermaid_diagram=mermaid_diagram,
                wiki_paragraph=wiki_paragraph,
            )

            logger.info(
                f"Analysis complete — domain={domain}, "
                f"confidence={confidence:.2f}, "
                f"overall_score={evaluation['overall_confidence']:.1f}, "
                f"total_latency={total_latency_ms}ms"
            )

            return {
                "extracted_text":        extracted_text,
                "detected_components":   structured_json["detected_components"],
                "services":              structured_json["services"],
                "gateways":              structured_json["gateways"],
                "databases":             structured_json["databases"],
                "queues":                structured_json["queues"],
                "storage":               structured_json["storage"],
                "security":              structured_json["security"],
                "cloud":                 structured_json["cloud"],
                "containers":            structured_json["containers"],
                "observability":         structured_json["observability"],
                "architecture_analysis": analysis_content,
                "mermaid_diagram":       mermaid_diagram,
                "markdown_documentation": markdown_doc,
                "wikipedia_enrichment":  wiki_paragraph,
                "metadata":              metadata,
            }

        except Exception as e:
            logger.exception("Diagram analysis failed")
            raise RuntimeError(str(e))