"""Seed Neo4j dependency graph from a public GitHub repository.

Clones the repo file tree via the GitHub API, parses Python import
statements to build a module-level dependency graph, and populates
Neo4j with Component nodes and DEPENDS_ON relationships.

Usage::

    python tools/seed_repo.py --repo tiangolo/fastapi
    python tools/seed_repo.py --repo pallets/flask --max-depth 2
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import math
import os
import sys
from collections import defaultdict
from pathlib import PurePosixPath

import httpx
from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    """Return GitHub API headers, including auth token if available."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_repo_tree(repo: str, branch: str = "main") -> list[dict]:
    """Fetch the full file tree from GitHub (recursive).

    Falls back to ``master`` if ``main`` is not found.
    """
    headers = _github_headers()
    for ref in (branch, "master"):
        url = f"{GITHUB_API}/repos/{repo}/git/trees/{ref}?recursive=1"
        resp = httpx.get(url, headers=headers, timeout=30, follow_redirects=True)
        if resp.status_code == 200:
            return resp.json().get("tree", [])
        if resp.status_code == 403:
            print("  GitHub API rate-limited (403). Set GITHUB_TOKEN env var for 5000 req/hr.")
    raise SystemExit(f"Could not fetch tree for {repo} (tried main, master)")


def fetch_file_content(repo: str, path: str, ref: str = "main") -> str | None:
    """Fetch raw file content from GitHub."""
    headers = _github_headers()
    for branch in (ref, "master"):
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        if resp.status_code == 200:
            return resp.text
    return None


# ---------------------------------------------------------------------------
# Python import parsing
# ---------------------------------------------------------------------------


def extract_imports(source: str) -> set[str]:
    """Parse Python source and return top-level imported module names."""
    imports: set[str] = set()
    try:
        tree = ast.parse(source, type_comments=False)
    except SyntaxError:
        return imports

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # absolute imports only
                imports.add(node.module.split(".")[0])
    return imports


def path_to_module(path: str) -> str:
    """Convert a file path to a module identifier.

    ``src/fastapi/routing.py`` → ``fastapi/routing``
    ``fastapi/__init__.py``    → ``fastapi``
    """
    p = PurePosixPath(path)
    parts = list(p.parts)

    # Strip common prefixes
    if parts and parts[0] in ("src", "lib"):
        parts = parts[1:]

    # Drop __init__.py — the package itself is the module
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        # Strip .py extension
        if parts and parts[-1].endswith(".py"):
            parts[-1] = parts[-1][:-3]

    return "/".join(parts) if parts else ""


def module_to_package(mod: str) -> str:
    """Extract the top-level package from a module path.

    ``fastapi/routing`` → ``fastapi``
    """
    return mod.split("/")[0] if "/" in mod else mod


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_dependency_graph(
    repo: str, tree: list[dict], *, sample_limit: int = 500
) -> tuple[dict[str, dict], list[tuple[str, str]]]:
    """Build a module-level dependency graph from the repo tree.

    Returns
    -------
    nodes : dict[module_name → {type, fan_in}]
    edges : list[(source_module, target_module)]
    """
    py_files = [
        e["path"]
        for e in tree
        if e["type"] == "blob" and e["path"].endswith(".py")
    ]

    # Limit to avoid hitting rate limits on very large repos
    if len(py_files) > sample_limit:
        print(f"  Sampling {sample_limit}/{len(py_files)} Python files")
        py_files = py_files[:sample_limit]

    # Map import names → package directories that exist in the repo
    repo_packages: set[str] = set()
    for f in py_files:
        mod = path_to_module(f)
        pkg = module_to_package(mod)
        if pkg:
            repo_packages.add(pkg)

    nodes: dict[str, dict] = {}
    edges: list[tuple[str, str]] = []
    fan_in: dict[str, int] = defaultdict(int)

    for i, fpath in enumerate(py_files):
        mod = path_to_module(fpath)
        if not mod:
            continue

        # Register the module as a node
        if mod not in nodes:
            nodes[mod] = {"type": "module"}

        # Fetch & parse imports
        if (i + 1) % 50 == 0 or i == 0:
            print(f"  Parsing {i + 1}/{len(py_files)} …")
        source = fetch_file_content(repo, fpath)
        if source is None:
            continue

        imports = extract_imports(source)

        for imp in imports:
            # Only keep edges to modules that exist in the repo
            if imp in repo_packages and imp != module_to_package(mod):
                target = imp
                if target not in nodes:
                    nodes[target] = {"type": "package"}
                edges.append((mod, target))
                fan_in[target] += 1

    # Annotate fan-in for weight synthesis
    for name, data in nodes.items():
        data["fan_in"] = fan_in.get(name, 0)

    return nodes, edges


# ---------------------------------------------------------------------------
# Neo4j population
# ---------------------------------------------------------------------------


def _synthetic_weight(fan_in: int, total_nodes: int) -> dict:
    """Generate realistic-looking node weights from fan-in count.

    Higher fan-in → more critical (more things depend on it).
    """
    if total_nodes == 0:
        total_nodes = 1
    normalized = min(1.0, fan_in / max(total_nodes * 0.1, 1))
    # Add some deterministic variance using a hash
    jitter = lambda v, seed: min(1.0, max(0.0, v + 0.1 * (hash(seed) % 10 - 5) / 10))

    return {
        "request_volume": round(jitter(normalized * 0.8, f"rv-{fan_in}"), 3),
        "error_rate": round(jitter(0.02 + normalized * 0.05, f"er-{fan_in}"), 3),
        "latency_sensitivity": round(jitter(normalized * 0.6, f"ls-{fan_in}"), 3),
        "production_criticality": round(jitter(normalized * 0.7, f"pc-{fan_in}"), 3),
    }


def _synthetic_edge_weight(source_fan_in: int, target_fan_in: int) -> dict:
    """Generate edge weights — heavier edges for high-fan-in targets."""
    combined = source_fan_in + target_fan_in
    normalized = min(1.0, combined / 20)
    return {
        "call_frequency": round(normalized * 0.7 + 0.1, 3),
        "traffic_volume": round(normalized * 0.6 + 0.05, 3),
        "failure_propagation_rate": round(min(0.8, normalized * 0.4 + 0.05), 3),
    }


def populate_neo4j(
    uri: str,
    user: str,
    password: str,
    nodes: dict[str, dict],
    edges: list[tuple[str, str]],
) -> None:
    """Write nodes and edges into Neo4j."""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    total = len(nodes)

    with driver.session() as session:
        # Create nodes
        print(f"  Creating {total} nodes …")
        for name, data in nodes.items():
            w = _synthetic_weight(data["fan_in"], total)
            session.run(
                """
                MERGE (n:Component {name: $name})
                SET n.type = $type,
                    n.request_volume = $rv,
                    n.error_rate = $er,
                    n.latency_sensitivity = $ls,
                    n.production_criticality = $pc,
                    n.updated_at = datetime()
                """,
                name=name,
                type=data["type"],
                rv=w["request_volume"],
                er=w["error_rate"],
                ls=w["latency_sensitivity"],
                pc=w["production_criticality"],
            )

        # Create edges
        print(f"  Creating {len(edges)} edges …")
        for source, target in edges:
            ew = _synthetic_edge_weight(
                nodes.get(source, {}).get("fan_in", 0),
                nodes.get(target, {}).get("fan_in", 0),
            )
            session.run(
                """
                MERGE (s:Component {name: $source})
                MERGE (t:Component {name: $target})
                MERGE (s)-[r:DEPENDS_ON]->(t)
                SET r.call_frequency = $cf,
                    r.traffic_volume = $tv,
                    r.failure_propagation_rate = $fpr,
                    r.updated_at = datetime()
                """,
                source=source,
                target=target,
                cf=ew["call_frequency"],
                tv=ew["traffic_volume"],
                fpr=ew["failure_propagation_rate"],
            )

    driver.close()
    print(f"  ✓ Neo4j seeded: {total} nodes, {len(edges)} edges")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Seed Neo4j dependency graph from a public GitHub repo."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo in owner/name format (e.g. tiangolo/fastapi)",
    )
    parser.add_argument(
        "--neo4j-uri",
        default="bolt://localhost:7687",
        help="Neo4j Bolt URI (default: bolt://localhost:7687)",
    )
    parser.add_argument(
        "--neo4j-user", default="neo4j", help="Neo4j user"
    )
    parser.add_argument(
        "--neo4j-password", default="tracerat_dev", help="Neo4j password"
    )
    parser.add_argument(
        "--sample-limit",
        type=int,
        default=500,
        help="Max number of Python files to parse (default: 500)",
    )
    args = parser.parse_args()

    print(f"[1/3] Fetching file tree for {args.repo} …")
    tree = fetch_repo_tree(args.repo)
    print(f"  Found {len(tree)} entries")

    print(f"[2/3] Building dependency graph …")
    nodes, edges = build_dependency_graph(
        args.repo, tree, sample_limit=args.sample_limit
    )
    print(f"  {len(nodes)} modules, {len(edges)} dependencies")

    print(f"[3/3] Populating Neo4j …")
    populate_neo4j(args.neo4j_uri, args.neo4j_user, args.neo4j_password, nodes, edges)
    print("Done!")


if __name__ == "__main__":
    main()
