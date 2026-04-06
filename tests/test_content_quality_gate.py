"""
content_quality_gate 품질 게이트 단위 테스트
"""

import pytest

from app.core.errors import MemoryContentTooShortError, MemoryLowQualityError
from app.core.services.quality_gate import content_quality_gate


class TestContentQualityGate:
    """content_quality_gate 함수 테스트"""

    # ── 정상 통과 ────────────────────────────────────────────────────────────

    def test_valid_content_passes(self):
        """충분히 긴 정상 콘텐츠는 통과한다"""
        content = "SQLite WAL 모드로 변경 결정. 동시 읽기 성능이 크게 개선되었으며 write lock 경합이 줄었다. " * 2
        result = content_quality_gate(content)
        assert result == content.strip()

    def test_returns_stripped_content(self):
        """반환값은 앞뒤 공백이 제거된 콘텐츠다"""
        content = "  " + "A" * 110 + "  "
        result = content_quality_gate(content)
        assert result == content.strip()

    # ── 길이 부족 ────────────────────────────────────────────────────────────

    def test_rejects_content_shorter_than_100_chars(self):
        """100자 미만 콘텐츠는 MemoryContentTooShortError"""
        with pytest.raises(MemoryContentTooShortError) as exc_info:
            content_quality_gate("짧은 내용")
        assert exc_info.value.details["minimum"] == 100

    def test_rejects_exactly_99_chars(self):
        """99자 콘텐츠는 거부"""
        content = "가" * 99
        with pytest.raises(MemoryContentTooShortError):
            content_quality_gate(content)

    def test_accepts_exactly_100_chars(self):
        """100자 콘텐츠는 통과"""
        content = "가" * 100
        result = content_quality_gate(content)
        assert len(result) == 100

    # ── 저품질 접두사 ─────────────────────────────────────────────────────────

    @pytest.mark.parametrize("prefix", [
        "좋습니다",
        "네.",
        "네!",
        "네,",
        "알겠습니다",
        "안녕하세요",
    ])
    def test_rejects_low_quality_prefixes(self, prefix):
        """저품질 접두사로 시작하면 MemoryLowQualityError"""
        content = prefix + " " + "추가 내용입니다. " * 20
        with pytest.raises(MemoryLowQualityError) as exc_info:
            content_quality_gate(content)
        assert exc_info.value.details["prefix"] == prefix

    @pytest.mark.parametrize("prefix", [
        "OK",
        "Sure",
        "Got it",
        "I understand",
        "Yes,",
        "Yes.",
        "Alright",
        "Okay",
    ])
    def test_rejects_english_low_quality_prefixes(self, prefix):
        """영어 저품질 접두사로 시작하면 MemoryLowQualityError"""
        content = prefix + " " + "This is additional filler content for testing. " * 10
        with pytest.raises(MemoryLowQualityError) as exc_info:
            content_quality_gate(content)
        assert exc_info.value.details["prefix"] == prefix

    def test_allows_content_containing_prefix_not_at_start(self):
        """저품질 단어가 중간에 있는 경우는 통과"""
        content = "중요한 결정 사항입니다. 네. 이 방식으로 진행하겠습니다. " * 5
        result = content_quality_gate(content)
        assert result is not None

    # ── XML 스트리핑 ──────────────────────────────────────────────────────────

    def test_strips_environment_context_tag(self):
        """<EnvironmentContext> 태그 내용을 제거한다"""
        xml_block = "<EnvironmentContext>OS: macOS\nPython: 3.11\n</EnvironmentContext>"
        real_content = "SQLite WAL 모드 설정 완료. 동시 읽기 성능 향상 확인. " * 3
        content = xml_block + "\n" + real_content
        result = content_quality_gate(content)
        assert "<EnvironmentContext>" not in result
        assert real_content.strip() in result

    def test_strips_file_tree_tag(self):
        """<fileTree> 태그 내용을 제거한다"""
        xml_block = "<fileTree>\n  app/\n    core/\n      services/\n</fileTree>"
        real_content = "파일 구조 변경 결정. 서비스 레이어를 core 디렉토리로 이동. " * 3
        content = xml_block + "\n" + real_content
        result = content_quality_gate(content)
        assert "<fileTree>" not in result
        assert real_content.strip() in result

    def test_strips_spec_tag(self):
        """<SPEC> 태그 내용을 제거한다"""
        xml_block = "<SPEC>\n기술 명세서 내용\n</SPEC>"
        real_content = "API 설계 결정 사항. REST 방식으로 통일하기로 함. 이유는 클라이언트 호환성. " * 3
        content = xml_block + "\n" + real_content
        result = content_quality_gate(content)
        assert "<SPEC>" not in result

    def test_strips_multiple_xml_tags(self):
        """여러 XML 태그를 동시에 제거한다"""
        content = (
            "<EnvironmentContext>env data</EnvironmentContext>\n"
            "<fileTree>tree data</fileTree>\n"
            "실제 중요한 내용입니다. 아키텍처 결정 사항을 기록합니다. " * 3
        )
        result = content_quality_gate(content)
        assert "<EnvironmentContext>" not in result
        assert "<fileTree>" not in result

    def test_rejects_after_stripping_if_too_short(self):
        """XML 제거 후 100자 미만이면 MemoryContentTooShortError"""
        content = (
            "<EnvironmentContext>매우 긴 환경 데이터 " * 20 + "</EnvironmentContext>\n"
            "짧은 내용"
        )
        with pytest.raises(MemoryContentTooShortError):
            content_quality_gate(content)

    def test_strips_multiline_xml_tags(self):
        """멀티라인 XML 태그도 제거한다"""
        content = (
            "<EnvironmentContext>\n"
            "  OS: macOS 14.0\n"
            "  Python: 3.11.5\n"
            "  Shell: zsh\n"
            "</EnvironmentContext>\n"
            "데이터베이스 인덱스 최적화 결정. B-tree 인덱스를 복합 인덱스로 교체하여 쿼리 성능 3배 향상. " * 2
        )
        result = content_quality_gate(content)
        assert "OS: macOS" not in result
        assert "데이터베이스" in result
