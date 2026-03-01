"""
프로젝트 자동 감지 서비스
Automatic project detection from context
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ProjectDetector:
    """프로젝트 자동 감지"""

    def __init__(self):
        # 프로젝트 매핑 규칙 (특별한 경우만)
        self.project_mappings = {
            # 디렉토리명 → 프로젝트 ID
            # 대부분 디렉토리명을 그대로 사용하도록 변경
            "kiro": None,  # kiro는 제외
            "test": None,  # test 디렉토리 제외
            "tmp": None,  # tmp 디렉토리 제외
            "temp": None,  # temp 디렉토리 제외
        }

        # 프로젝트 패턴 (정규식) - 특별한 경우만
        self.project_patterns = [
            # 대부분의 경우 디렉토리명을 그대로 사용
            # 특별한 패턴이 필요한 경우만 추가
        ]

    def detect_from_path(self, path: Optional[str] = None) -> Optional[str]:
        """
        경로에서 프로젝트 감지

        Args:
            path: 경로 (없으면 현재 디렉토리)

        Returns:
            프로젝트 ID 또는 None
        """
        if path is None:
            path = os.getcwd()

        path_obj = Path(path)

        # 1. 현재 디렉토리명 확인
        dir_name = path_obj.name.lower()

        # 2. 직접 매핑 확인
        if dir_name in self.project_mappings:
            mapped = self.project_mappings[dir_name]
            if mapped:
                logger.info(f"Project detected from mapping: {dir_name} → {mapped}")
                return mapped
            else:
                logger.info(f"Directory {dir_name} is excluded")
                return None

        # 3. 패턴 매칭
        for pattern, template in self.project_patterns:
            match = re.match(pattern, dir_name)
            if match:
                project_id = template.format(*match.groups())
                logger.info(f"Project detected from pattern: {dir_name} → {project_id}")
                return project_id

        # 4. Git 리포지토리 확인
        git_project = self._detect_from_git(path_obj)
        if git_project:
            return git_project

        # 5. 디렉토리명을 그대로 프로젝트로 사용
        # (노이즈 방지를 위해 특정 조건 확인)
        if self._is_valid_project_name(dir_name):
            logger.info(f"Using directory name as project: {dir_name}")
            return dir_name

        return None

    def _detect_from_git(self, path: Path) -> Optional[str]:
        """Git 리포지토리에서 프로젝트 감지"""
        try:
            # .git 디렉토리 찾기
            git_dir = None
            current = path

            while current.parent != current:
                if (current / ".git").exists():
                    git_dir = current
                    break
                current = current.parent

            if git_dir:
                # Git remote origin 확인
                config_file = git_dir / ".git" / "config"
                if config_file.exists():
                    with open(config_file, "r") as f:
                        content = f.read()
                        # GitHub/GitLab URL에서 리포지토리명 추출
                        match = re.search(
                            r"url = .*/([^/]+?)(?:\.git)?$", content, re.MULTILINE
                        )
                        if match:
                            repo_name = match.group(1)
                            logger.info(f"Project detected from git: {repo_name}")
                            return repo_name

                # Git 디렉토리명 사용
                return git_dir.name

        except Exception as e:
            logger.debug(f"Git detection failed: {e}")

        return None

    def _is_valid_project_name(self, name: str) -> bool:
        """유효한 프로젝트명인지 확인"""
        # 제외할 디렉토리명
        excluded = {
            "desktop",
            "downloads",
            "documents",
            "home",
            "users",
            "root",
            "var",
            "tmp",
            "temp",
            "test",
            "tests",
            "node_modules",
            "venv",
            ".",
            "..",
            "",
        }

        if name.lower() in excluded:
            return False

        # 너무 짧거나 긴 이름 제외
        if len(name) < 2 or len(name) > 50:
            return False

        # 특수문자만 있는 경우 제외
        if not re.search(r"[a-zA-Z0-9]", name):
            return False

        return True

    def get_context(
        self, additional_info: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        전체 컨텍스트 가져오기

        Args:
            additional_info: 추가 정보

        Returns:
            컨텍스트 딕셔너리
        """
        context = {
            "project": self.detect_from_path(),
            "directory": os.path.basename(os.getcwd()),
            "full_path": os.getcwd(),
            "user": os.environ.get("USER", "unknown"),
        }

        # 환경 변수에서 추가 정보
        if "MEM_MESH_PROJECT" in os.environ:
            context["project"] = os.environ["MEM_MESH_PROJECT"]

        if additional_info:
            context.update(additional_info)

        return context


# 싱글톤 인스턴스
_detector = None


def get_project_detector() -> ProjectDetector:
    """싱글톤 ProjectDetector 가져오기"""
    global _detector
    if _detector is None:
        _detector = ProjectDetector()
    return _detector


def detect_current_project() -> Optional[str]:
    """현재 프로젝트 감지 (간편 함수)"""
    detector = get_project_detector()
    return detector.detect_from_path()


def get_search_context() -> Dict[str, Any]:
    """검색용 컨텍스트 가져오기"""
    detector = get_project_detector()
    context = detector.get_context()

    # 검색 최적화 설정 추가
    context["search_settings"] = {
        "limit": 5,
        "min_score": 0.3,
        "aggressive_filter": True,
        "exclude_projects": ["kiro-*", "test-*", "tmp-*"],
    }

    return context
