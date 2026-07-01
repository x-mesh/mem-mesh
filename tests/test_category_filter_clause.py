"""category_filter_clause 단위 테스트

단일 문자열(category = ?) / 리스트·튜플·셋(category IN (?, ...)) 필터 절 생성 검증.
"""

from app.core.database.base import category_filter_clause


class TestCategoryFilterClause:
    """category_filter_clause 헬퍼 테스트"""

    def test_none_returns_empty(self):
        assert category_filter_clause(None) == ("", [])

    def test_empty_string_returns_empty(self):
        assert category_filter_clause("") == ("", [])

    def test_empty_list_returns_empty(self):
        assert category_filter_clause([]) == ("", [])

    def test_single_string(self):
        assert category_filter_clause("bug") == ("category = ?", ["bug"])

    def test_list_two_values(self):
        assert category_filter_clause(["a", "b"]) == (
            "category IN (?,?)",
            ["a", "b"],
        )

    def test_tuple(self):
        assert category_filter_clause(("a", "b")) == (
            "category IN (?,?)",
            ["a", "b"],
        )

    def test_set(self):
        # set 순회 순서는 비결정적이므로 특정 순서를 단정하지 않는다.
        # placeholders 개수 == params 개수, params == 내부 materialize 순서만 검증.
        cats = {"a", "b", "c"}
        cond, params = category_filter_clause(cats)
        expected_params = [c for c in cats if c]
        assert cond == "category IN (" + ",".join("?" * len(expected_params)) + ")"
        assert cond.count("?") == len(params)
        assert params == expected_params
        assert set(params) == cats

    def test_list_with_falsy_items(self):
        assert category_filter_clause(["a", "", None, "b"]) == (
            "category IN (?,?)",
            ["a", "b"],
        )

    def test_list_all_falsy_returns_empty(self):
        assert category_filter_clause(["", None]) == ("", [])

    def test_custom_column_single(self):
        assert category_filter_clause("bug", column="m.category") == (
            "m.category = ?",
            ["bug"],
        )

    def test_custom_column_list(self):
        assert category_filter_clause(["a", "b"], column="m.category") == (
            "m.category IN (?,?)",
            ["a", "b"],
        )
