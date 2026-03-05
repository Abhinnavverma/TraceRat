"""Delta dependency graph calculator.

Computes the downstream blast radius of a PR change by traversing
the weighted dependency graph in Neo4j using BFS with edge-weight
multiplication at each hop.

Core algorithm:
1. Map changed files → graph nodes
2. BFS outward from changed nodes
3. At each hop: propagated_score = parent_score × edge_composite_score
4. Prune branches below min_score_threshold
5. Return sorted list of AffectedComponent objects
"""

from collections import deque
from typing import Any

from app.models import AffectedComponent, EdgeWeight, NodeType
from app.services.neo4j_client import Neo4jClient
from app.services.observability_fallback import ObservabilityFallback
from shared.logging import get_logger

logger = get_logger("delta_calculator")

# Default configuration
DEFAULT_MAX_DEPTH = 3
DEFAULT_MIN_SCORE_THRESHOLD = 0.01


class DeltaCalculator:
    """Computes the delta dependency graph for a PR change.

    Uses BFS traversal with edge-weight multiplication to propagate
    risk scores through downstream dependencies. High-traffic edges
    propagate more influence than low-traffic edges.
    """

    def __init__(
        self,
        neo4j_client: Neo4jClient,
        observability_fallback: ObservabilityFallback | None = None,
        max_depth: int = DEFAULT_MAX_DEPTH,
        min_score_threshold: float = DEFAULT_MIN_SCORE_THRESHOLD,
    ):
        self._neo4j = neo4j_client
        self._fallback = observability_fallback or ObservabilityFallback()
        self._max_depth = max_depth
        self._min_score_threshold = min_score_threshold

    async def compute_delta(
        self,
        changed_files: list[dict[str, Any]],
        affected_modules: list[dict[str, Any]],
        repo_full_name: str,
    ) -> list[AffectedComponent]:
        """Compute downstream affected components for a set of changes.

        Args:
            changed_files: List of changed file metadata dicts
                (from DiffMetadata.changed_files).
            affected_modules: List of module mapping dicts
                (from DiffMetadata.affected_modules).
            repo_full_name: Repository full name for logging context.

        Returns:
            Sorted list of AffectedComponent (highest risk first).
        """
        # Step 1: Identify changed node names
        changed_node_names = self._extract_changed_nodes(
            changed_files, affected_modules
        )

        if not changed_node_names:
            logger.warning(
                "No changed nodes identified",
                repo=repo_full_name,
            )
            return []

        logger.info(
            "Computing delta graph",
            repo=repo_full_name,
            changed_nodes=changed_node_names,
            max_depth=self._max_depth,
        )

        # Step 2: Map changed names to actual graph nodes
        graph_nodes = await self._neo4j.find_nodes_by_filenames(
            list(changed_node_names)
        )

        if not graph_nodes:
            logger.warning(
                "No graph nodes found for changed files",
                repo=repo_full_name,
                changed_count=len(changed_node_names),
            )
            return []

        start_node_names = {n["name"] for n in graph_nodes}

        logger.info(
            "Matched changed files to graph nodes",
            matched=len(start_node_names),
            total_changed=len(changed_node_names),
        )

        # Step 3: BFS traversal from each start node
        affected = await self._bfs_propagate(start_node_names)

        # Step 4: Sort by risk score descending
        affected.sort(key=lambda c: c.risk_score, reverse=True)

        logger.info(
            "Delta computation complete",
            repo=repo_full_name,
            affected_count=len(affected),
            max_score=affected[0].risk_score if affected else 0.0,
        )

        return affected

    def _extract_changed_nodes(
        self,
        changed_files: list[dict[str, Any]],
        affected_modules: list[dict[str, Any]],
    ) -> set[str]:
        """Extract unique node names from changed files and module mappings.

        Prioritizes module-level names (from affected_modules) as they're
        more likely to match graph nodes. Falls back to individual filenames.
        """
        nodes: set[str] = set()

        # Add module-level names (higher likelihood of graph match)
        for module in affected_modules:
            module_name = module.get("module_name", "")
            if module_name:
                nodes.add(module_name)

        # Add individual filenames as fallbacks
        for f in changed_files:
            filename = f.get("filename", "")
            if filename:
                nodes.add(filename)

        return nodes

    async def _bfs_propagate(
        self, start_nodes: set[str]
    ) -> list[AffectedComponent]:
        """BFS traversal with edge-weight multiplication.

        Starting from each changed node with score 1.0, propagates
        risk through downstream edges. At each hop:
            child_score = parent_score × edge_composite_score

        Branches are pruned when score drops below min_score_threshold.
        """
        # Track visited nodes to avoid cycles and duplicates
        # Maps node_name -> best AffectedComponent found so far
        visited: dict[str, AffectedComponent] = {}

        # BFS queue: (node_name, current_score, depth, path)
        queue: deque[tuple[str, float, int, list[str]]] = deque()

        # Seed with start nodes at depth 0, score 1.0
        for node_name in start_nodes:
            queue.append((node_name, 1.0, 0, [node_name]))

        while queue:
            current_name, current_score, depth, path = queue.popleft()

            # Skip if we've exceeded max depth
            if depth > self._max_depth:
                continue

            # Get downstream neighbors for this node
            neighbors = await self._neo4j.get_downstream_neighbors(
                current_name, max_depth=1
            )

            for neighbor in neighbors:
                target_name: str = neighbor["target"]

                # Skip self-loops and back-to-start
                if target_name in start_nodes:
                    continue

                # Compute edge weight composite score
                edge_weight = EdgeWeight(
                    call_frequency=neighbor.get("edge_call_frequency", 0.0),
                    traffic_volume=neighbor.get("edge_traffic_volume", 0.0),
                    failure_propagation_rate=neighbor.get(
                        "edge_failure_propagation_rate", 0.0
                    ),
                )

                propagated_score = current_score * edge_weight.composite_score

                # Prune if score is too low
                if propagated_score < self._min_score_threshold:
                    continue

                # Cap at 1.0
                propagated_score = min(propagated_score, 1.0)

                new_path = [*path, target_name]
                new_depth = depth + 1

                # Determine node type
                node_type_str = neighbor.get("target_type", "module")
                try:
                    node_type = NodeType(node_type_str)
                except ValueError:
                    node_type = NodeType.MODULE

                component = AffectedComponent(
                    node_id=target_name,
                    node_type=node_type,
                    name=target_name,
                    risk_score=propagated_score,
                    dependency_depth=new_depth,
                    traffic_weight=edge_weight.composite_score,
                    path_from_change=new_path,
                )

                # Only keep the highest-scoring path to each node
                if target_name in visited:
                    if visited[target_name].risk_score >= propagated_score:
                        continue

                visited[target_name] = component

                # Continue BFS if we haven't hit max depth
                if new_depth < self._max_depth:
                    queue.append(
                        (target_name, propagated_score, new_depth, new_path)
                    )

        return list(visited.values())
