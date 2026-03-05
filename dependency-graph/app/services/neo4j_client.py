"""Async Neo4j client for querying and updating the dependency graph.

Wraps the official neo4j async driver to provide:
- Node and edge weight upserts (telemetry enrichment)
- Downstream neighbor queries (delta graph computation)
- File-to-node mapping for changed files
- Health check for readiness probe
"""

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.models import EdgeWeight, NodeWeight
from shared.config import Neo4jSettings, get_settings
from shared.logging import get_logger

logger = get_logger("neo4j_client")


class Neo4jClient:
    """Async client for the dependency graph stored in Neo4j.

    The graph schema:
    - Nodes labeled :Component with properties: name, type, request_volume,
      error_rate, latency_sensitivity, production_criticality
    - Relationships typed :DEPENDS_ON with properties: call_frequency,
      traffic_volume, failure_propagation_rate
    """

    def __init__(self, settings: Neo4jSettings | None = None):
        self._settings = settings or get_settings().neo4j
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Establish connection to Neo4j."""
        self._driver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.user, self._settings.password),
        )
        # Verify connectivity
        await self._driver.verify_connectivity()
        logger.info("Connected to Neo4j", uri=self._settings.uri)

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    @property
    def is_connected(self) -> bool:
        """Check if the driver is initialized."""
        return self._driver is not None

    async def health_check(self) -> bool:
        """Verify Neo4j connectivity for readiness probes."""
        if not self._driver:
            return False
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            logger.exception("Neo4j health check failed")
            return False

    # ----- Node Operations -----

    async def get_node(self, name: str) -> dict[str, Any] | None:
        """Fetch a single node by name.

        Returns:
            Node properties dict, or None if not found.
        """
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")

        query = """
        MATCH (n:Component {name: $name})
        RETURN n {.*} AS node
        """
        async with self._driver.session() as session:
            result = await session.run(query, name=name)
            record = await result.single()
            return dict(record["node"]) if record else None

    async def find_nodes_by_filenames(
        self, filenames: list[str]
    ) -> list[dict[str, Any]]:
        """Map changed filenames to graph nodes.

        Tries exact filename match first, then falls back to matching
        against the module/directory prefix of the filename.

        Args:
            filenames: List of changed file paths (repo-relative).

        Returns:
            List of matching node properties dicts.
        """
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")

        # Build list of candidate names: full paths + directory prefixes
        candidates: set[str] = set()
        for f in filenames:
            candidates.add(f)
            # Add parent directories as potential module-level matches
            parts = f.replace("\\", "/").split("/")
            for i in range(1, len(parts)):
                candidates.add("/".join(parts[:i]))

        query = """
        MATCH (n:Component)
        WHERE n.name IN $candidates
        RETURN n {.*} AS node
        """
        async with self._driver.session() as session:
            result = await session.run(query, candidates=list(candidates))
            records = await result.data()
            return [dict(r["node"]) for r in records]

    # ----- Edge / Neighbor Queries -----

    async def get_downstream_neighbors(
        self, node_name: str, max_depth: int = 3
    ) -> list[dict[str, Any]]:
        """Get downstream dependencies of a node up to max_depth hops.

        Returns nodes reachable via :DEPENDS_ON relationships along with
        the edge weights and depth at each step.

        Args:
            node_name: Name of the starting node.
            max_depth: Maximum traversal depth.

        Returns:
            List of dicts with keys: source, target, depth,
            edge_call_frequency, edge_traffic_volume, edge_failure_propagation_rate,
            target_type, target_request_volume, target_error_rate,
            target_latency_sensitivity, target_production_criticality.
        """
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")

        query = """
        MATCH path = (start:Component {name: $node_name})
              -[:DEPENDS_ON*1..$max_depth]->(downstream:Component)
        WITH downstream, relationships(path) AS rels,
             nodes(path) AS ns, length(path) AS depth
        UNWIND range(0, size(rels) - 1) AS idx
        WITH downstream, depth,
             ns[idx].name AS source_name,
             ns[idx + 1].name AS target_name,
             rels[idx] AS rel
        RETURN DISTINCT
            source_name AS source,
            target_name AS target,
            depth,
            coalesce(rel.call_frequency, 0.0) AS edge_call_frequency,
            coalesce(rel.traffic_volume, 0.0) AS edge_traffic_volume,
            coalesce(rel.failure_propagation_rate, 0.0) AS edge_failure_propagation_rate,
            coalesce(downstream.type, 'module') AS target_type,
            coalesce(downstream.request_volume, 0.0) AS target_request_volume,
            coalesce(downstream.error_rate, 0.0) AS target_error_rate,
            coalesce(downstream.latency_sensitivity, 0.0) AS target_latency_sensitivity,
            coalesce(downstream.production_criticality, 0.0) AS target_production_criticality
        ORDER BY depth ASC
        """
        # Neo4j parameterized variable-length paths require string interpolation
        # for the depth, so we construct the query with the value directly.
        safe_query = query.replace("$max_depth", str(int(max_depth)))

        async with self._driver.session() as session:
            result = await session.run(safe_query, node_name=node_name)
            return await result.data()

    # ----- Weight Upsert Operations -----

    async def upsert_node_weight(
        self, node_name: str, node_type: str, weight: NodeWeight
    ) -> None:
        """Create or update a node with weight properties.

        MERGE ensures idempotency — creates node if absent, updates if present.

        Args:
            node_name: Unique node name.
            node_type: Node type (service, module, package, file).
            weight: Weight properties to set.
        """
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")

        query = """
        MERGE (n:Component {name: $name})
        SET n.type = $type,
            n.request_volume = $request_volume,
            n.error_rate = $error_rate,
            n.latency_sensitivity = $latency_sensitivity,
            n.production_criticality = $production_criticality,
            n.updated_at = datetime()
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                name=node_name,
                type=node_type,
                request_volume=weight.request_volume,
                error_rate=weight.error_rate,
                latency_sensitivity=weight.latency_sensitivity,
                production_criticality=weight.production_criticality,
            )

        logger.debug(
            "Upserted node weight",
            node=node_name,
            type=node_type,
            composite=weight.composite_score,
        )

    async def upsert_edge_weight(
        self, source: str, target: str, weight: EdgeWeight
    ) -> None:
        """Create or update an edge between two nodes with weight properties.

        MERGE ensures idempotency. Creates endpoint nodes if they don't exist.

        Args:
            source: Source node name.
            target: Target node name.
            weight: Edge weight properties to set.
        """
        if not self._driver:
            raise RuntimeError("Neo4j client not connected")

        query = """
        MERGE (s:Component {name: $source})
        MERGE (t:Component {name: $target})
        MERGE (s)-[r:DEPENDS_ON]->(t)
        SET r.call_frequency = $call_frequency,
            r.traffic_volume = $traffic_volume,
            r.failure_propagation_rate = $failure_propagation_rate,
            r.updated_at = datetime()
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                source=source,
                target=target,
                call_frequency=weight.call_frequency,
                traffic_volume=weight.traffic_volume,
                failure_propagation_rate=weight.failure_propagation_rate,
            )

        logger.debug(
            "Upserted edge weight",
            source=source,
            target=target,
            composite=weight.composite_score,
        )
