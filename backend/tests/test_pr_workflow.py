from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from pulse_specs.discovery import discover_phases, resolve_specs_root
from pulse_specs.pr_workflow import (
    build_pr_body,
    build_pr_title,
    extract_pr_title_hint,
    resolve_remote_owner_repo,
)


class PrWorkflowTests(unittest.TestCase):
    def test_extract_pr_title_hint(self) -> None:
        backend = Path(__file__).resolve().parents[1]
        specs_root = resolve_specs_root(backend)
        phase = discover_phases(specs_root, only=["01-agent-provider"])[0]
        hint = extract_pr_title_hint(phase.product_path)
        self.assertEqual(hint, "refactor: extrair contrato AgentProvider dos executores Cursor")

    def test_build_pr_title_adds_backend_scope(self) -> None:
        backend = Path(__file__).resolve().parents[1]
        specs_root = resolve_specs_root(backend)
        phase = discover_phases(specs_root, only=["01-agent-provider"])[0]
        title = build_pr_title(phase, phase.product_path, backend.parent)
        self.assertIn("backend/agent-provider", title)
        self.assertTrue(title.startswith("refactor("))

    def test_build_pr_body_contains_phase_slug(self) -> None:
        backend = Path(__file__).resolve().parents[1]
        specs_root = resolve_specs_root(backend)
        phase = discover_phases(specs_root, only=["01-agent-provider"])[0]
        body = build_pr_body(
            repo_root=backend.parent,
            phase=phase,
            base_branch="feat/pulse-backend",
            status_path=None,
        )
        self.assertIn("01-agent-provider", body)
        self.assertIn("## Resumo", body)

    def test_resolve_remote_owner_repo(self) -> None:
        backend = Path(__file__).resolve().parents[1]
        owner, repo = resolve_remote_owner_repo(backend.parent)
        self.assertEqual(owner, "jonathancmatos")
        self.assertEqual(repo, "pulse.ai")

    @patch("pulse_specs.pr_workflow.httpx.post")
    @patch("pulse_specs.pr_workflow.httpx.get")
    def test_create_phase_pull_request_via_api(self, mock_get, mock_post) -> None:
        backend = Path(__file__).resolve().parents[1]
        specs_root = resolve_specs_root(backend)
        phase = discover_phases(specs_root, only=["01-agent-provider"])[0]

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = []
        mock_post.return_value.status_code = 201
        mock_post.return_value.json.return_value = {
            "html_url": "https://github.com/jonathancmatos/pulse.ai/pull/99"
        }

        from pulse_specs.pr_workflow import create_phase_pull_request

        with patch.dict("os.environ", {"GITHUB_TOKEN": "test-token"}):
            result = create_phase_pull_request(
                repo_root=backend.parent,
                phase=phase,
                head_branch="feat/pulse-specs/01-agent-provider",
                base_branch="feat/pulse-backend",
            )

        self.assertTrue(result.created)
        self.assertEqual(result.url, "https://github.com/jonathancmatos/pulse.ai/pull/99")
