"""에러 클래스 중앙화 아키텍처 검증 테스트.

app/core/errors.py가 유일한 에러 정의 소스인지 확인합니다.
서비스 파일에 인라인 에러 클래스가 남아있으면 실패합니다.
"""

import ast
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ERRORS_MODULE = PROJECT_ROOT / "app" / "core" / "errors.py"

# 검사 대상 디렉토리 (에러를 정의하면 안 되는 곳)
SERVICE_DIRS = [
    PROJECT_ROOT / "app" / "core" / "services",
    PROJECT_ROOT / "app" / "mcp_common",
    PROJECT_ROOT / "app" / "web",
]

# 예외: 이 파일들은 도메인 전용 에러를 허용
ALLOWED_INLINE_ERRORS = {
    # OAuth는 별도 시그니처(error, description)를 가지므로 허용
    str(PROJECT_ROOT / "app" / "core" / "auth" / "service.py"),
}


def _find_error_classes(filepath: Path) -> list[tuple[int, str]]:
    """AST를 파싱하여 Exception/MemMeshError를 상속하는 클래스를 찾는다."""
    source = filepath.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    results = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if base_name in ("Exception", "ValueError", "RuntimeError"):
                if node.name.endswith("Error"):
                    results.append((node.lineno, node.name))
    return results


def _collect_service_files() -> list[Path]:
    """검사 대상 .py 파일 수집."""
    files = []
    for dir_path in SERVICE_DIRS:
        if not dir_path.exists():
            continue
        for root, _, filenames in os.walk(dir_path):
            for fname in filenames:
                if not fname.endswith(".py"):
                    continue
                full = os.path.join(root, fname)
                if full not in ALLOWED_INLINE_ERRORS:
                    files.append(Path(full))
    return files


class TestErrorCentralization:
    """에러 클래스가 app/core/errors.py에만 정의되어 있는지 검증."""

    def test_errors_module_exists(self):
        assert ERRORS_MODULE.exists(), "app/core/errors.py must exist"

    def test_no_inline_error_classes_in_services(self):
        """서비스 파일에 인라인 에러 클래스가 없어야 한다."""
        violations = []
        for filepath in _collect_service_files():
            for lineno, class_name in _find_error_classes(filepath):
                rel = filepath.relative_to(PROJECT_ROOT)
                violations.append(f"  {rel}:{lineno} — {class_name}")

        if violations:
            msg = (
                "Inline error classes found outside app/core/errors.py.\n"
                "Move them to app/core/errors.py (MemMeshError base):\n"
                + "\n".join(violations)
            )
            pytest.fail(msg)

    def test_errors_module_has_base_class(self):
        """errors.py에 MemMeshError 기본 클래스가 있어야 한다."""
        source = ERRORS_MODULE.read_text(encoding="utf-8")
        assert "class MemMeshError(Exception):" in source

    def test_all_errors_inherit_memmesh_error(self):
        """errors.py의 모든 에러가 MemMeshError를 상속해야 한다."""
        source = ERRORS_MODULE.read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Error"):
                continue
            if node.name == "MemMeshError":
                continue

            base_names = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    base_names.append(base.id)
            assert "MemMeshError" in base_names, (
                f"{node.name} (line {node.lineno}) must inherit from MemMeshError"
            )
