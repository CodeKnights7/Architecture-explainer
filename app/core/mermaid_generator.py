"""
mermaid_generator.py
====================

Enterprise Mermaid generation layer.

Features
--------
1. Validates inputs.
2. Builds the graph via ``GraphEngine.build_architecture_graph()``,
   passing ``observability`` as a dedicated parameter so those nodes
   appear in their own subgraph and are *never* confused with deployable
   services.
3. Prevents empty Mermaid output — creates a fallback diagram when the
   graph produces no usable output.
4. Handles isolated nodes by ensuring every component appears in the
   rendered diagram even if it has no edges.
5. Adds structured logging at every decision point.
6. Compatible with DiagramService v2.1 and v3.0.

Bug fixes (v3.0)
----------------
- Observability param forwarded to GraphEngine so Logging / Monitoring /
  Tracing nodes are placed in a dedicated subgraph, not lost as isolated
  mystery nodes.
- Fallback path now uses GraphEngine node shapes so the fallback diagram
  looks consistent with the primary path output.
"""

from app.logger import logger
from app.core.graph_engine import GraphEngine


class MermaidGenerator:

    @staticmethod
    def generate(
        services:      list | None = None,
        gateways:      list | None = None,
        databases:     list | None = None,
        queues:        list | None = None,
        storage:       list | None = None,
        containers:    list | None = None,
        observability: list | None = None,
    ) -> str:
        """
        Generate a Mermaid ``graph TD`` diagram from architecture components.

        Parameters
        ----------
        services, gateways, databases, queues, storage, containers
            Deployable infrastructure components.
        observability
            Cross-cutting concern labels (Logging, Monitoring, Tracing, …).
            These are rendered in a dedicated ``Observability`` subgraph and
            are never wired into the main topology edges.

        Returns
        -------
        str
            A valid Mermaid diagram string, always non-empty when at least
            one component was detected.
        """

        services      = services      or []
        gateways      = gateways      or []
        databases     = databases     or []
        queues        = queues        or []
        storage       = storage       or []
        containers    = containers    or []
        observability = observability or []

        try:

            graph = GraphEngine.build_architecture_graph(
                services=services,
                gateways=gateways,
                databases=databases,
                queues=queues,
                storage=storage,
                containers=containers,
                observability=observability,
            )

            mermaid = GraphEngine.to_mermaid(graph)

            # ----------------------------------------------------------------
            # Valid Mermaid output produced by GraphEngine
            # ----------------------------------------------------------------

            if (
                mermaid
                and mermaid.strip()
                and mermaid.strip() != "graph TD"
            ):
                logger.info(
                    f"Mermaid generated successfully "
                    f"({graph.number_of_nodes()} nodes, "
                    f"{graph.number_of_edges()} edges)"
                )
                return mermaid

            # ----------------------------------------------------------------
            # Fallback: GraphEngine returned empty / bare stub.
            # Build a minimal diagram that lists every node by category.
            # ----------------------------------------------------------------

            logger.warning(
                "GraphEngine produced empty Mermaid output. "
                "Triggering fallback diagram."
            )

            all_components = (
                gateways
                + services
                + databases
                + queues
                + storage
                + containers
                + observability
            )

            if not all_components:
                logger.warning("No architecture components found — cannot generate diagram.")
                return (
                    "graph TD\n"
                    '    Empty["No Components Detected"]'
                )

            lines = ["graph TD"]

            def _safe_id(name: str) -> str:
                return name.replace(" ", "_").replace("-", "_").replace("/", "_")

            if gateways:
                lines.append("")
                lines.append("    subgraph Gateways")
                for n in sorted(set(gateways)):
                    lines.append(f'        {_safe_id(n)}(["{n}"])')
                lines.append("    end")

            if services:
                lines.append("")
                lines.append("    subgraph Services")
                for n in sorted(set(services)):
                    lines.append(f'        {_safe_id(n)}("{n}")')
                lines.append("    end")

            if databases:
                lines.append("")
                lines.append("    subgraph Databases")
                for n in sorted(set(databases)):
                    lines.append(f'        {_safe_id(n)}[("{n}")]')
                lines.append("    end")

            if queues:
                lines.append("")
                lines.append("    subgraph Queues")
                for n in sorted(set(queues)):
                    lines.append(f'        {_safe_id(n)}[/"{n}"/]')
                lines.append("    end")

            if storage:
                lines.append("")
                lines.append("    subgraph Storage")
                for n in sorted(set(storage)):
                    lines.append(f'        {_safe_id(n)}{{{{"{n}"}}}}')
                lines.append("    end")

            if containers:
                lines.append("")
                lines.append("    subgraph Containers")
                for n in sorted(set(containers)):
                    lines.append(f'        {_safe_id(n)}["{n}"]')
                lines.append("    end")

            if observability:
                lines.append("")
                lines.append("    subgraph Observability")
                for n in sorted(set(observability)):
                    lines.append(f'        {_safe_id(n)}{{{{"{n}"}}}}')
                lines.append("    end")

            result = "\n".join(lines)
            logger.info(
                f"Fallback Mermaid diagram built "
                f"({len(all_components)} components, no edges)"
            )
            return result

        except Exception as exc:

            logger.exception(f"Mermaid generation failed: {exc}")

            return (
                "graph TD\n"
                '    Error["Mermaid Generation Failed"]'
            )
