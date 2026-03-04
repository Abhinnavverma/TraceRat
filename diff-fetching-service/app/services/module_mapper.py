"""Module mapper — maps changed file paths to modules/services.

Uses configurable path-based heuristics (regex patterns) to determine
which modules or services are affected by a set of file changes.
"""

import re
from collections import defaultdict
from pathlib import PurePosixPath

from app.models import ChangedFile, MappingRule, ModuleMapping

# --- Default Mapping Rules ---
# These cover common monorepo and project layout patterns.
# Users can extend or override via configuration.

DEFAULT_RULES: list[MappingRule] = [
    # Explicit service directories
    MappingRule(
        pattern=r"^(?:src/)?services/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="src/services/<name>/ or services/<name>/",
    ),
    # Microservice directories at root
    MappingRule(
        pattern=r"^(?P<module>[a-z][\w-]*-service)/",
        module_name=r"\g<module>",
        description="<name>-service/ at root",
    ),
    # Packages / libraries
    MappingRule(
        pattern=r"^(?:packages|libs|libraries)/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="packages/<name>/ or libs/<name>/",
    ),
    # apps directory (common in monorepos)
    MappingRule(
        pattern=r"^apps/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="apps/<name>/",
    ),
    # modules directory
    MappingRule(
        pattern=r"^modules/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="modules/<name>/",
    ),
    # components directory (e.g. frontend monorepos)
    MappingRule(
        pattern=r"^(?:src/)?components/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="components/<name>/",
    ),
    # Top-level src/<name> pattern
    MappingRule(
        pattern=r"^src/(?P<module>[^/]+)/",
        module_name=r"\g<module>",
        description="src/<name>/",
    ),
    # Infra / deployment files
    MappingRule(
        pattern=r"^(?:infra|infrastructure|deploy|k8s|terraform|helm)/",
        module_name="infrastructure",
        description="Infrastructure and deployment files",
    ),
    # CI/CD configuration
    MappingRule(
        pattern=r"^\.(?:github|gitlab|circleci)/",
        module_name="ci-cd",
        description="CI/CD configuration files",
    ),
    # Documentation
    MappingRule(
        pattern=r"^(?:docs|documentation)/",
        module_name="documentation",
        description="Documentation files",
    ),
    # Config files at root
    MappingRule(
        pattern=r"^(?:docker-compose|Makefile|Dockerfile|\.env)",
        module_name="build-config",
        description="Root build/deployment configuration",
    ),
]


class ModuleMapper:
    """Maps changed file paths to modules/services using regex heuristics.

    Attributes:
        rules: Ordered list of mapping rules. First match wins per file.
    """

    def __init__(self, rules: list[MappingRule] | None = None):
        """Initialize with optional custom rules.

        Args:
            rules: Custom mapping rules. If None, uses DEFAULT_RULES.
        """
        self.rules = rules if rules is not None else DEFAULT_RULES
        # Pre-compile patterns for efficiency
        self._compiled: list[tuple[MappingRule, re.Pattern]] = [
            (rule, re.compile(rule.pattern)) for rule in self.rules
        ]

    def map_file(self, filepath: str) -> tuple[str, str] | None:
        """Map a single file path to a module name.

        Args:
            filepath: Relative file path (e.g., "src/services/auth/handler.py").

        Returns:
            Tuple of (module_name, matched_pattern) or None if no match.
        """
        # Normalize to forward slashes
        normalized = filepath.replace("\\", "/")

        for rule, pattern in self._compiled:
            match = pattern.search(normalized)
            if match:
                # Support named group substitution in module_name
                try:
                    module_name = match.expand(rule.module_name)
                except (IndexError, re.error):
                    module_name = rule.module_name
                return module_name, rule.pattern

        return None

    def map_files(self, files: list[ChangedFile]) -> list[ModuleMapping]:
        """Map a list of changed files to module/service mappings.

        Groups files by their detected module and returns the aggregated result.

        Args:
            files: List of changed files from a PR.

        Returns:
            List of ModuleMapping objects, one per detected module.
        """
        # module_name -> {files: [...], rules: set(...)}
        module_groups: dict[str, dict] = defaultdict(
            lambda: {"files": [], "rules": set()}
        )
        unmapped_files: list[str] = []

        for file in files:
            result = self.map_file(file.filename)
            if result:
                module_name, matched_rule = result
                module_groups[module_name]["files"].append(file.filename)
                module_groups[module_name]["rules"].add(matched_rule)
            else:
                unmapped_files.append(file.filename)

        mappings: list[ModuleMapping] = []

        for module_name, data in sorted(module_groups.items()):
            mappings.append(
                ModuleMapping(
                    module_name=module_name,
                    matched_files=data["files"],
                    confidence=1.0,  # Regex match = high confidence
                    matching_rule=", ".join(sorted(data["rules"])),
                )
            )

        # Group unmapped files under a generic module based on top-level dir
        if unmapped_files:
            dir_groups: dict[str, list[str]] = defaultdict(list)
            for fp in unmapped_files:
                parts = PurePosixPath(fp.replace("\\", "/")).parts
                top_dir = parts[0] if len(parts) > 1 else "root"
                dir_groups[top_dir].append(fp)

            for dir_name, dir_files in sorted(dir_groups.items()):
                mappings.append(
                    ModuleMapping(
                        module_name=dir_name,
                        matched_files=dir_files,
                        confidence=0.5,  # Inferred from directory, lower confidence
                        matching_rule="top-level-directory-fallback",
                    )
                )

        return mappings
