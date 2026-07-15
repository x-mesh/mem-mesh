"""Kiro behavioral hooks must not freeze an install-time project id."""

from app.cli.prompts.renderers import (
    render_kiro_auto_create_pin,
    render_kiro_auto_save,
    render_kiro_load_context,
)


def test_kiro_prompts_resolve_project_identity_at_execution_time() -> None:
    for renderer in (
        render_kiro_auto_save,
        render_kiro_auto_create_pin,
        render_kiro_load_context,
    ):
        prompt = renderer("legacy-project")["then"]["prompt"]

        assert "<resolved-current-project-id>" in prompt
        assert "git config --local --get mem-mesh.project-id" in prompt
        assert 'project_id="legacy-project"' not in prompt
        assert "`legacy-project`를 fallback" in prompt
