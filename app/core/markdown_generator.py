"""
markdown_generator.py
=====================
Generates the architecture analysis markdown report.

Improvements:
  1. Shows all new evaluation fields (visual_quality, domain_bonus).
  2. Domain confidence and score are surfaced prominently.
  3. Quality tier label (Excellent / Good / Fair / Needs Improvement)
     is added to the executive summary.
  4. Report footer lists the updated toolchain.

Bug fix (v4.0) — Mermaid section always said "No Mermaid diagram was generated."
----------------------------------------------------------------------------------
Root cause: generate() was calling extract_mermaid(architecture_analysis) which
searches for a ```mermaid code block inside the LLM's raw text output.  The LLM
rarely wraps its response in a mermaid fence, so this always returned "".

The actual Mermaid diagram is built by GraphEngine / MermaidGenerator and lives
in a completely separate field (mermaid_diagram) that DiagramService returns.
That field was never passed into generate(), so the Mermaid section was always
the fallback string.

Fix: add mermaid_diagram as an explicit parameter to generate().
     DiagramService already holds the value; it just needs to pass it here.
     extract_mermaid() is kept as a fallback for callers that embed the diagram
     inside the LLM analysis text (legacy / future use).
"""

from datetime import datetime


class MarkdownGenerator:

    @staticmethod
    def extract_mermaid(content: str) -> str:
        """
        Extract a ```mermaid ... ``` block from arbitrary text.

        Used as a fallback when no explicit mermaid_diagram is supplied.
        Returns the full fenced block including the backtick delimiters,
        or an empty string when no block is found.
        """
        start = content.find("```mermaid")
        if start == -1:
            return ""
        end = content.find("```", start + 10)
        if end == -1:
            return ""
        return content[start : end + 3]

    @staticmethod
    def _quality_tier(overall_confidence: float) -> str:
        if overall_confidence >= 85:
            return "🟢 Excellent"
        if overall_confidence >= 70:
            return "🟡 Good"
        if overall_confidence >= 50:
            return "🟠 Fair"
        return "🔴 Needs Improvement"

    @staticmethod
    def generate(
        architecture_analysis: str,
        metadata: dict = None,
        mermaid_diagram: str = "",
        wiki_paragraph: str = "",
    ) -> str:
        """
        Generate the full markdown architecture report.

        Parameters
        ----------
        architecture_analysis : str
            Raw LLM analysis text (may or may not contain a ```mermaid block).
        metadata : dict
            Pipeline metadata dict produced by DiagramService.
        mermaid_diagram : str
            The canonical Mermaid diagram string produced by MermaidGenerator /
            GraphEngine.  When non-empty this takes priority over any ```mermaid
            block embedded inside architecture_analysis.
        """

        metadata  = metadata or {}
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        domain           = metadata.get("domain", "Unknown")
        domain_conf      = metadata.get("domain_confidence", "Low")
        domain_score     = metadata.get("domain_score", 0)
        confidence       = metadata.get("confidence", 0.0)
        ocr_chars        = metadata.get("ocr_characters", 0)
        ocr_latency      = metadata.get("ocr_latency_ms", "N/A")
        llm_latency      = metadata.get("llm_latency_ms", "N/A")
        total_latency    = metadata.get("total_latency_ms", "N/A")

        evaluation       = metadata.get("evaluation", {})
        overall_conf     = evaluation.get("overall_confidence", 0.0)
        ocr_quality      = evaluation.get("ocr_quality", 0.0)
        visual_quality   = evaluation.get("visual_quality", 0.0)
        component_score  = evaluation.get("component_score", 0.0)
        h_risk           = evaluation.get("hallucination_risk", "Unknown")
        h_score          = evaluation.get("hallucination_score", 0.0)
        enterprise_score = evaluation.get("enterprise_score", 0.0)
        domain_bonus     = evaluation.get("domain_bonus", 0.0)

        tier = MarkdownGenerator._quality_tier(overall_conf)

        # ------------------------------------------------------------------
        # Mermaid resolution — priority order:
        #   1. Explicit mermaid_diagram parameter (built by GraphEngine).
        #   2. ```mermaid block embedded inside architecture_analysis (legacy).
        #   3. Fallback message.
        # ------------------------------------------------------------------

        mermaid_section: str

        if mermaid_diagram and mermaid_diagram.strip():
            # Wrap the raw "graph TD ..." string in a fenced code block so
            # it renders correctly in every Markdown viewer.
            cleaned = mermaid_diagram.strip()
            if cleaned.startswith("```"):
                # Already fenced — use as-is.
                mermaid_section = cleaned
            else:
                mermaid_section = f"```mermaid\n{cleaned}\n```"

        else:
            # Fallback: try to extract a mermaid fence from the LLM text.
            embedded = MarkdownGenerator.extract_mermaid(architecture_analysis)
            if embedded:
                mermaid_section = embedded
            else:
                mermaid_section = "_No Mermaid diagram was generated._"

        # Prepare optional Wikipedia section when enrichment is available.
        wiki_section = ""
        if wiki_paragraph and wiki_paragraph.strip():
            wiki_section = (
                "---\n\n"
                "## Wikipedia Definitions\n\n"
                f"{wiki_paragraph}\n\n"
                "---\n\n"
            )

        report = f"""# Architecture Analysis Report

---

> **Generated:** {timestamp}
>
> **Domain:** {domain} ({domain_conf} confidence, score: {domain_score})
>
> **Analysis Confidence:** {confidence:.0%}  —  {tier}
>
> **OCR Characters Extracted:** {ocr_chars}
>
> **OCR Latency:** {ocr_latency} ms
>
> **LLM Latency:** {llm_latency} ms
>
> **Total Latency:** {total_latency} ms

---

## Executive Summary

This report was generated automatically by the **AI Architecture Intelligence Engine** using:

- **Multi-pass EasyOCR** with 5 preprocessing strategies (upscaling, CLAHE, Otsu, adaptive threshold, background normalisation)
- **OpenCV** computer vision pipeline
- **Qwen2.5-VL** vision language model (via Ollama)
- **Combined domain classification** (OCR + visual analysis)
- **Graph-based architecture analysis** (NetworkX)

**Overall Quality Score: {overall_conf:.1f} / 100 — {tier}**

---

## Detailed Architecture Analysis

{architecture_analysis}

---

## Architecture Quality Metrics

| Metric                    | Value                   |
|---------------------------|-------------------------|
| Domain                    | {domain}                |
| Domain Confidence         | {domain_conf}           |
| Domain Score              | {domain_score}          |
| Overall Confidence        | {overall_conf:.1f} / 100 |
| Analysis Confidence (0–1) | {confidence:.2f}        |
| OCR Characters            | {ocr_chars}             |
| OCR Quality Score         | {ocr_quality:.1f} / 100 |
| Visual Analysis Quality   | {visual_quality:.1f} / 100 |
| Component Detection Score | {component_score:.1f} / 100 |
| Enterprise Readiness      | {enterprise_score:.1f} / 100 |
| Hallucination Risk        | {h_risk}                |
| Hallucination Score       | {h_score:.1f} / 100     |
| Domain Confidence Bonus   | +{domain_bonus:.1f}     |
| OCR Latency (ms)          | {ocr_latency}           |
| LLM Latency (ms)          | {llm_latency}           |
| Total Latency (ms)        | {total_latency}         |

---

## Architecture Diagram (Mermaid)

{mermaid_section}

---

{wiki_section}

## Report Notes

- Generated automatically — findings should be validated by a senior architect.
- A low OCR character count does NOT indicate a poor diagram; vector-graphics
  diagrams are analysed directly by the vision LLM.
- Domain confidence improves when the diagram contains labelled, named components.

---

## AI Architecture Intelligence Metadata

Generated using:

- **FastAPI** — REST API layer
- **EasyOCR 1.7+** — multi-pass text extraction
- **OpenCV 4.12** — image preprocessing (5 strategies)
- **Ollama** — local LLM inference server
- **Qwen2.5-VL:7B** — vision language model
- **NetworkX** — graph analysis engine
- **Architecture Intelligence Pipeline v4.0**
"""

        return report.strip()