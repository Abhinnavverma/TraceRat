"""Tests for the module mapper."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.module_mapper import MappingRule, ModuleMapper

from tests.conftest import make_changed_file


class TestModuleMapperDefaultRules:
    """Test module mapper with default heuristic rules."""

    def setup_method(self):
        self.mapper = ModuleMapper()

    def test_services_directory(self):
        """Files under services/<name>/ map to that service."""
        files = [
            make_changed_file("src/services/auth/handler.py"),
            make_changed_file("src/services/auth/models.py"),
            make_changed_file("src/services/payment/checkout.py"),
        ]
        mappings = self.mapper.map_files(files)
        module_names = {m.module_name for m in mappings}
        assert "auth" in module_names
        assert "payment" in module_names

    def test_services_without_src_prefix(self):
        """services/<name>/ without src/ prefix also works."""
        files = [make_changed_file("services/notifications/sender.py")]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "notifications" for m in mappings)

    def test_microservice_directories(self):
        """Directories named *-service at root map correctly."""
        files = [
            make_changed_file("auth-service/src/main.py"),
            make_changed_file("payment-service/handler.go"),
        ]
        mappings = self.mapper.map_files(files)
        module_names = {m.module_name for m in mappings}
        assert "auth-service" in module_names
        assert "payment-service" in module_names

    def test_packages_directory(self):
        """Files under packages/<name>/ map correctly."""
        files = [
            make_changed_file("packages/shared-utils/index.ts"),
            make_changed_file("libs/crypto/encrypt.py"),
        ]
        mappings = self.mapper.map_files(files)
        module_names = {m.module_name for m in mappings}
        assert "shared-utils" in module_names
        assert "crypto" in module_names

    def test_apps_directory(self):
        """Files under apps/<name>/ map correctly."""
        files = [make_changed_file("apps/web-dashboard/components/Chart.tsx")]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "web-dashboard" for m in mappings)

    def test_infrastructure_files(self):
        """Infra files map to 'infrastructure'."""
        files = [
            make_changed_file("terraform/main.tf"),
            make_changed_file("k8s/deployment.yaml"),
        ]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "infrastructure" for m in mappings)

    def test_cicd_files(self):
        """CI/CD files map to 'ci-cd'."""
        files = [make_changed_file(".github/workflows/ci.yml")]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "ci-cd" for m in mappings)

    def test_documentation_files(self):
        """Documentation files map to 'documentation'."""
        files = [make_changed_file("docs/architecture.md")]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "documentation" for m in mappings)

    def test_build_config_files(self):
        """Root config files map to 'build-config'."""
        files = [
            make_changed_file("docker-compose.yml"),
            make_changed_file("Makefile"),
        ]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "build-config" for m in mappings)

    def test_src_subdirectories(self):
        """Files under src/<name>/ map to that directory name."""
        files = [
            make_changed_file("src/utils/helpers.py"),
            make_changed_file("src/models/user.py"),
        ]
        mappings = self.mapper.map_files(files)
        module_names = {m.module_name for m in mappings}
        assert "utils" in module_names
        assert "models" in module_names

    def test_unmapped_files_fallback_to_directory(self):
        """Files that don't match any rule use top-level directory fallback."""
        files = [make_changed_file("random_dir/some_file.txt")]
        mappings = self.mapper.map_files(files)
        assert len(mappings) >= 1
        # Should have lower confidence
        fallback = [m for m in mappings if m.confidence < 1.0]
        assert len(fallback) >= 1

    def test_root_files_fallback(self):
        """Root-level files with no match get 'root' fallback."""
        files = [make_changed_file("README.md")]
        mappings = self.mapper.map_files(files)
        assert len(mappings) >= 1

    def test_multiple_files_same_module_grouped(self):
        """Multiple files in the same module are grouped together."""
        files = [
            make_changed_file("src/services/auth/handler.py"),
            make_changed_file("src/services/auth/models.py"),
            make_changed_file("src/services/auth/tests/test_handler.py"),
        ]
        mappings = self.mapper.map_files(files)
        auth_mappings = [m for m in mappings if m.module_name == "auth"]
        assert len(auth_mappings) == 1
        assert len(auth_mappings[0].matched_files) == 3

    def test_empty_file_list(self):
        """Empty file list returns empty mappings."""
        mappings = self.mapper.map_files([])
        assert mappings == []

    def test_windows_paths_normalized(self):
        """Windows-style backslash paths are normalized."""
        files = [make_changed_file("src\\services\\auth\\handler.py")]
        mappings = self.mapper.map_files(files)
        assert any(m.module_name == "auth" for m in mappings)


class TestModuleMapperCustomRules:
    """Test module mapper with custom rules."""

    def test_custom_rules_override_defaults(self):
        """Custom rules are used instead of defaults."""
        custom_rules = [
            MappingRule(
                pattern=r"^backend/",
                module_name="backend",
                description="All backend code",
            ),
        ]
        mapper = ModuleMapper(rules=custom_rules)
        files = [make_changed_file("backend/api/views.py")]
        mappings = mapper.map_files(files)
        assert any(m.module_name == "backend" for m in mappings)

    def test_first_matching_rule_wins(self):
        """When multiple rules could match, the first one wins."""
        custom_rules = [
            MappingRule(pattern=r"^src/", module_name="source"),
            MappingRule(pattern=r"^src/services/", module_name="services"),
        ]
        mapper = ModuleMapper(rules=custom_rules)
        files = [make_changed_file("src/services/auth/handler.py")]
        mappings = mapper.map_files(files)
        assert mappings[0].module_name == "source"


class TestModuleMapperMapFile:
    """Test the single-file map_file method."""

    def setup_method(self):
        self.mapper = ModuleMapper()

    def test_returns_tuple_on_match(self):
        """map_file returns (module_name, pattern) tuple on match."""
        result = self.mapper.map_file("src/services/auth/handler.py")
        assert result is not None
        module_name, pattern = result
        assert module_name == "auth"
        assert len(pattern) > 0

    def test_returns_none_on_no_match(self):
        """map_file returns None when no rule matches."""
        # Use a very unusual path that won't match defaults
        mapper = ModuleMapper(rules=[])
        result = mapper.map_file("some/random/path.txt")
        assert result is None
