"""
graph_engine.py
===============
Topology-aware architecture graph generation.

Features
--------
- Gateway -> Service routing
- Service -> matching Database routing (smart prefix-match with stemming
  fallback, or single-DB fallback)
- Async Service -> Queue routing
- Queue -> Consumer routing
- Database -> Storage routing
- Observability / cross-cutting concerns tracked separately (not as
  deployable infra nodes) to avoid overcounting them as components
- Container nodes rendered as infrastructure
- Mermaid subgraph rendering with node-type styling
- Isolated node rendering
- Graph metrics
- Shortest-path support

Bug Fixes (v4.0)
----------------
1. Mermaid always generated when components exist.

2. Observability separated from deployable components.

3. Smart Service → Database matching (v4.0):
   - Exact prefix match first  ("User Service" → "User DB")
   - Stem match second: both names share a common stem after stripping
     common suffixes (Service, DB, Database, ing, er, tion, etc.)
     so "Reporting Service" matches "Report DB",
        "Notification Service" matches "Notification DB",
        "Inventory Service" matches "Inventory DB".
   - Single-DB fallback only when no stem match found.
   - This replaces the old rule-based "Gateway → All Services →
     All DBs" topology with accurate per-service DB wiring.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

import networkx as nx


# ---------------------------------------------------------------------------
# Async-service keyword set
# ---------------------------------------------------------------------------

_ASYNC_SERVICE_KEYWORDS: frozenset[str] = frozenset({
    "notification",
    "email",
    "sms",
    "push",
    "reporting",
    "report",
    "analytics",
    "audit",
    "log",
    "logging",
    "event",
    "worker",
    "consumer",
    "publisher",
    "subscriber",
    "listener",
    "shipping",
    "payment",
})


def _prefix_of(name: str) -> str:
    """
    Return the first token of *name* in lower-case.

    Examples
    --------
    >>> _prefix_of("User Service")
    'user'
    >>> _prefix_of("User DB")
    'user'
    """
    return name.split()[0].lower() if name else ""


# ---------------------------------------------------------------------------
# Stem helpers for smart Service → Database matching
# ---------------------------------------------------------------------------

# Suffixes to strip when computing a canonical stem.
# Order matters: longer suffixes must come before shorter ones.
_STEM_SUFFIXES = [
    "service",
    "database",
    " db",
    "ing",      # reporting → report
    "tion",     # notification → notifica  (handled specially below)
    "ation",    # notification → notific   → normalised via regex
    "er",       # order → ord  (only strip when stem is still meaningful)
    "s",        # orders → order
]


def _stem(name: str) -> str:
    """
    Compute a normalised stem from a component name for fuzzy matching.

    Strategy
    --------
    1. Lower-case the entire name.
    2. Drop known trailing category words (service, db, database).
    3. Drop common English suffixes so that
       "reporting" ↔ "report",
       "notification" ↔ "notification" (same),
       "inventory" ↔ "inventory" (same).
    4. Return the stripped, stripped string.

    This is intentionally simple — we want to avoid false positives
    (matching "Payment Service" to "User DB") while catching the most
    common microservice naming conventions.
    """
    s = name.lower().strip()

    # Drop category suffix words first.
    for suffix in ("service", " database", " db"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
            break

    # Now strip trailing noise from the leftover stem.
    # "reporting" → "report"  (strip "ing" only if ≥ 5 chars remain)
    if s.endswith("ing") and len(s) > 5:
        s = s[:-3]

    # "notification" → "notif"  — too aggressive; leave as-is.
    # "notifications" → "notification"
    if s.endswith("tion"):
        pass  # keep; common microservice suffix

    if s.endswith("ations"):
        s = s[:-1]  # strip trailing 's' only

    if s.endswith("s") and len(s) > 4:
        s = s[:-1]

    return s.strip()


def _match_service_to_db(service: str, databases: List[str]) -> Optional[str]:
    """
    Return the best-matching database for *service*, or None.

    Matching priority
    -----------------
    1. Exact prefix match:        "User Service" → prefix "user"
                                  "User DB"      → prefix "user"  ✓

    2. Stem match:                "Reporting Service" → stem "report"
                                  "Report DB"         → stem "report"  ✓
                                  "Notification Service" → stem "notification"
                                  "Notification DB"      → stem "notification" ✓

    3. No match → returns None (caller applies single-DB fallback).
    """
    svc_prefix = _prefix_of(service)
    svc_stem   = _stem(service)

    # Pass 1: exact prefix match.
    for db in databases:
        if _prefix_of(db) == svc_prefix:
            return db

    # Pass 2: stem match.
    for db in databases:
        db_stem = _stem(db)
        if svc_stem and db_stem and (
            svc_stem == db_stem
            or svc_stem.startswith(db_stem)
            or db_stem.startswith(svc_stem)
        ):
            return db

    return None


def _is_async_service(service_name: str) -> bool:
    """Return True when *service_name* looks like an async producer/consumer."""
    lower = service_name.lower()
    return any(keyword in lower for keyword in _ASYNC_SERVICE_KEYWORDS)


# ---------------------------------------------------------------------------
# Node-type constants stored as graph attributes
# ---------------------------------------------------------------------------

_TYPE_GATEWAY       = "gateway"
_TYPE_SERVICE       = "service"
_TYPE_DATABASE      = "database"
_TYPE_QUEUE         = "queue"
_TYPE_STORAGE       = "storage"
_TYPE_CONTAINER     = "container"
_TYPE_OBSERVABILITY = "observability"


class GraphEngine:
    """
    Builds a directed NetworkX graph from extracted architecture components
    and renders it as a Mermaid ``graph TD`` diagram.
    """

    # Bare generic words that should never become graph nodes.
    INVALID_NODES: frozenset[str] = frozenset({
        "service",
        "services",
        "api",
        "gateway",
        "database",
        "queue",
        "storage",
        "microservice",
        "backend",
        "frontend",
        "worker",
    })

    # ---------------------------------------------------------------------- #
    # Node validation / cleaning                                              #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def is_valid_node(value: str) -> bool:
        """
        Return True when *value* is a meaningful node label.

        Rules
        -----
        - Not empty or whitespace-only.
        - At least 3 characters long.
        - Not a bare generic word (service, gateway, …).
        - At most 5 tokens (multi-word labels are fine; sentences are not).
        """
        if not value:
            return False

        value = value.strip()

        if len(value) < 3:
            return False

        if value.lower() in GraphEngine.INVALID_NODES:
            return False

        if len(value.split()) > 5:
            return False

        return True

    @staticmethod
    def clean_nodes(nodes: Optional[List[str]]) -> List[str]:
        """
        Deduplicate and validate a list of node labels.

        Returns a sorted, deduplicated list of valid node labels.
        """
        if not nodes:
            return []

        cleaned: List[str] = [
            node for node in nodes
            if GraphEngine.is_valid_node(node)
        ]

        return sorted(set(cleaned))

    # ---------------------------------------------------------------------- #
    # Graph construction                                                      #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def build_architecture_graph(
        services:      Optional[List[str]] = None,
        gateways:      Optional[List[str]] = None,
        databases:     Optional[List[str]] = None,
        queues:        Optional[List[str]] = None,
        storage:       Optional[List[str]] = None,
        containers:    Optional[List[str]] = None,
        observability: Optional[List[str]] = None,
    ) -> nx.DiGraph:
        """
        Build a typed directed graph from architecture component lists.

        Edge wiring rules
        -----------------
        Gateway  → Service     (all gateways fan out to all services)
        Service  → Database    (smart prefix+stem match; single-DB fallback
                                only when no per-service match is found)
        Service  → Queue       (async services only; single-queue fallback)
        Queue    → Service     (queue fans back to async consumers that have
                                not yet been wired as producers to that queue)
        Database → Storage     (all databases link to all storage nodes)
        """

        graph = nx.DiGraph()

        # Validate and clean all inputs.
        services      = GraphEngine.clean_nodes(services)
        gateways      = GraphEngine.clean_nodes(gateways)
        databases     = GraphEngine.clean_nodes(databases)
        queues        = GraphEngine.clean_nodes(queues)
        storage       = GraphEngine.clean_nodes(storage)
        containers    = GraphEngine.clean_nodes(containers)
        observability = GraphEngine.clean_nodes(observability)

        # ------------------------------------------------------------------ #
        # Add nodes with type attributes                                      #
        # ------------------------------------------------------------------ #

        for node in gateways:
            graph.add_node(node, node_type=_TYPE_GATEWAY)

        for node in services:
            graph.add_node(node, node_type=_TYPE_SERVICE)

        for node in databases:
            graph.add_node(node, node_type=_TYPE_DATABASE)

        for node in queues:
            graph.add_node(node, node_type=_TYPE_QUEUE)

        for node in storage:
            graph.add_node(node, node_type=_TYPE_STORAGE)

        for node in containers:
            graph.add_node(node, node_type=_TYPE_CONTAINER)

        for node in observability:
            graph.add_node(node, node_type=_TYPE_OBSERVABILITY)

        # ------------------------------------------------------------------ #
        # Gateway → Service                                                   #
        # ------------------------------------------------------------------ #

        for gateway in gateways:
            for service in services:
                graph.add_edge(gateway, service)

        # ------------------------------------------------------------------ #
        # Service → Database  (smart match; single-DB fallback only when     #
        # no service has a matched DB)                                        #
        # ------------------------------------------------------------------ #

        if databases:
            # First pass: try smart matching for every service.
            matched_services: List[str] = []
            unmatched_services: List[str] = []

            for service in services:
                matched_db = _match_service_to_db(service, databases)
                if matched_db:
                    graph.add_edge(service, matched_db)
                    matched_services.append(service)
                else:
                    unmatched_services.append(service)

            # Second pass: single-DB fallback only for services that
            # got no match AND there is exactly one database overall.
            if len(databases) == 1:
                for service in unmatched_services:
                    graph.add_edge(service, databases[0])

        # ------------------------------------------------------------------ #
        # Service → Queue  (async services publish; single-queue fallback)   #
        # ------------------------------------------------------------------ #

        for service in services:
            if _is_async_service(service):
                for queue in queues:
                    graph.add_edge(service, queue)
            elif len(queues) == 1:
                graph.add_edge(service, queues[0])

        # ------------------------------------------------------------------ #
        # Queue → Async consumers                                             #
        # Async services that are not already publishers become consumers.   #
        # ------------------------------------------------------------------ #

        for queue in queues:
            for service in services:
                if (
                    _is_async_service(service)
                    and not graph.has_edge(service, queue)
                ):
                    graph.add_edge(queue, service)

        # ------------------------------------------------------------------ #
        # Database → Storage                                                  #
        # ------------------------------------------------------------------ #

        for database in databases:
            for item in storage:
                graph.add_edge(database, item)

        return graph

    # ---------------------------------------------------------------------- #
    # Graph metrics                                                           #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def get_graph_metrics(graph: nx.DiGraph) -> dict:
        """
        Return a dictionary of graph topology metrics.

        Keys
        ----
        nodes                  Total node count.
        edges                  Total edge count.
        density                NetworkX density (float 0-1).
        critical_components    Top-5 nodes by degree centrality.
        single_points_of_failure
                               Nodes whose combined in+out degree ≥ 3.
        """

        if graph.number_of_nodes() == 0:
            return {
                "nodes":                    0,
                "edges":                    0,
                "density":                  0.0,
                "critical_components":      [],
                "single_points_of_failure": [],
            }

        centrality = nx.degree_centrality(graph)

        critical: List[str] = sorted(
            centrality,
            key=centrality.get,
            reverse=True,
        )[:5]

        spof: List[str] = [
            node for node in graph.nodes()
            if (graph.in_degree(node) + graph.out_degree(node)) >= 3
        ]

        return {
            "nodes":                    graph.number_of_nodes(),
            "edges":                    graph.number_of_edges(),
            "density":                  round(nx.density(graph), 4),
            "critical_components":      critical,
            "single_points_of_failure": spof,
        }

    # ---------------------------------------------------------------------- #
    # Utility: shortest path                                                  #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def shortest_path(
        graph:  nx.DiGraph,
        source: str,
        target: str,
    ) -> List[str]:
        """
        Return the shortest directed path from *source* to *target*.
        Returns an empty list when no path exists.
        """
        try:
            return nx.shortest_path(graph, source=source, target=target)
        except Exception:
            return []

    # ---------------------------------------------------------------------- #
    # Utility: isolated nodes                                                 #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def isolated_nodes(graph: nx.DiGraph) -> List[str]:
        """Return nodes that have neither incoming nor outgoing edges."""
        return [
            node for node in graph.nodes()
            if graph.in_degree(node) == 0 and graph.out_degree(node) == 0
        ]

    # ---------------------------------------------------------------------- #
    # Mermaid rendering                                                       #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def to_mermaid(graph: nx.DiGraph) -> str:
        """
        Render the graph as a Mermaid ``graph TD`` diagram.

        Design
        ------
        - Nodes are grouped into typed subgraphs so the diagram is
          self-documenting (Gateways / Services / Databases / Queues /
          Storage / Containers / Observability).
        - Cross-cutting observability nodes are placed in their own subgraph.
        - Edges between nodes use the ``node_id`` of the node label so
          Mermaid can correctly reference them across subgraph boundaries.
        - When the graph is empty, an empty string is returned so that
          ``MermaidGenerator`` can trigger its own fallback path cleanly.

        Node shape legend
        -----------------
        Gateways    – stadium shape  ``([label])``
        Services    – rounded box    ``(label)``
        Databases   – cylinder       ``[(label)]``
        Queues      – trapezoid      ``[/label/]``
        Storage     – asymmetric     ``{label}``
        Containers  – rectangle      ``[label]``
        Observability – hexagon      ``{{label}}``
        """

        if graph.number_of_nodes() == 0:
            return ""

        def node_id(name: str) -> str:
            """Convert an arbitrary label into a valid Mermaid node identifier."""
            return re.sub(r"[^A-Za-z0-9_]", "_", name)

        def node_shape(name: str, ntype: str) -> str:
            """Return the Mermaid node declaration with shape based on type."""
            nid   = node_id(name)
            label = name.replace('"', "'")

            shapes: Dict[str, str] = {
                _TYPE_GATEWAY:       f'{nid}(["{label}"])',
                _TYPE_SERVICE:       f'{nid}("{label}")',
                _TYPE_DATABASE:      f'{nid}[("{label}")]',
                _TYPE_QUEUE:         f'{nid}[/"{label}"/]',
                _TYPE_STORAGE:       f'{nid}{{{{"{label}"}}}}',
                _TYPE_CONTAINER:     f'{nid}["{label}"]',
                _TYPE_OBSERVABILITY: f'{nid}{{{{"{label}"}}}}',
            }

            return shapes.get(ntype, f'{nid}["{label}"]')

        # ------------------------------------------------------------------ #
        # Bucket nodes by type                                                #
        # ------------------------------------------------------------------ #

        _TYPE_ORDER: List[str] = [
            _TYPE_GATEWAY,
            _TYPE_SERVICE,
            _TYPE_DATABASE,
            _TYPE_QUEUE,
            _TYPE_STORAGE,
            _TYPE_CONTAINER,
            _TYPE_OBSERVABILITY,
        ]

        _SUBGRAPH_LABELS: Dict[str, str] = {
            _TYPE_GATEWAY:       "Gateways",
            _TYPE_SERVICE:       "Services",
            _TYPE_DATABASE:      "Databases",
            _TYPE_QUEUE:         "Queues",
            _TYPE_STORAGE:       "Storage",
            _TYPE_CONTAINER:     "Containers",
            _TYPE_OBSERVABILITY: "Observability",
        }

        buckets: Dict[str, List[str]] = {t: [] for t in _TYPE_ORDER}

        for node, attrs in graph.nodes(data=True):
            ntype = attrs.get("node_type", _TYPE_SERVICE)
            if ntype in buckets:
                buckets[ntype].append(node)
            else:
                buckets[_TYPE_SERVICE].append(node)

        # ------------------------------------------------------------------ #
        # Build Mermaid output                                                #
        # ------------------------------------------------------------------ #

        lines: List[str] = ["graph TD"]

        # Subgraphs (only emit a subgraph block when that bucket is non-empty)
        for ntype in _TYPE_ORDER:
            nodes_in_bucket = buckets[ntype]
            if not nodes_in_bucket:
                continue

            label = _SUBGRAPH_LABELS[ntype]
            lines.append("")
            lines.append(f"    subgraph {label}")

            for node in sorted(nodes_in_bucket):
                shape_decl = node_shape(node, ntype)
                lines.append(f"        {shape_decl}")

            lines.append("    end")

        # Edges (written outside subgraph blocks so cross-subgraph arrows work)
        lines.append("")

        for source, target in sorted(graph.edges()):
            sid = node_id(source)
            tid = node_id(target)
            lines.append(f"    {sid} --> {tid}")

        # ------------------------------------------------------------------ #
        # Safety guard                                                        #
        # ------------------------------------------------------------------ #

        mermaid_output = "\n".join(lines).strip()

        # Reject the bare stub "graph TD" as unusable.
        if mermaid_output == "graph TD":
            return ""

        return mermaid_output

    # ---------------------------------------------------------------------- #
    # Legacy shim: build from a plain list (no type info)                    #
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _build_legacy_mermaid(
        services:   List[str],
        gateways:   List[str],
        databases:  List[str],
        queues:     List[str],
        storage:    List[str],
        containers: List[str],
    ) -> str:
        """
        Convenience wrapper retained for unit-test / migration compatibility.
        Builds the graph without observability nodes and returns Mermaid text.
        """
        graph = GraphEngine.build_architecture_graph(
            services=services,
            gateways=gateways,
            databases=databases,
            queues=queues,
            storage=storage,
            containers=containers,
        )
        return GraphEngine.to_mermaid(graph)
