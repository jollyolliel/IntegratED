"""Static rules for `preview.yml` and the preview image. The real boundary is Google Cloud IAM
(ADR 0013); these catch an edit that would quietly weaken the workflow or change what ships."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/preview.yml").read_text(encoding="utf-8")
JOBS = yaml.safe_load(WORKFLOW)["jobs"]


def _scripts(job):
    return "\n".join(step.get("run", "") for step in JOBS[job]["steps"])


def test_the_workflow_never_runs_with_the_base_branchs_secrets():
    # PyYAML reads the bare `on:` key as True.
    assert "pull_request_target" not in yaml.safe_load(WORKFLOW)[True]


def test_the_job_that_runs_pr_code_holds_no_credential():
    build = JOBS["build"]
    assert "id-token" not in build["permissions"]
    assert not any("google-github-actions" in step.get("uses", "") for step in build["steps"])
    assert "--target preview" in _scripts("build")


@pytest.mark.parametrize("job", ["build", "deploy", "teardown", "sweep"])
def test_every_job_waits_for_the_one_time_setup(job):
    assert "vars.PREVIEW_PROJECT_ID != ''" in JOBS[job]["if"]


@pytest.mark.parametrize("job", ["build", "deploy", "teardown"])
def test_forks_and_dependabot_get_no_preview(job):
    assert "github.event.pull_request.head.repo.full_name == github.repository" in JOBS[job]["if"]
    assert "dependabot[bot]" in JOBS[job]["if"]


@pytest.mark.parametrize(
    "flag",
    [
        "--no-allow-unauthenticated", "--iap", "--max-instances=1", "--min-instances=0",
        "--service-account=", "APP_ENV=preview",
    ],
)
def test_a_preview_deploys_with_the_fixed_flags(flag):
    assert flag in _scripts("deploy")


def test_a_preview_is_given_no_secret():
    assert "--set-secrets" not in WORKFLOW and "--update-secrets" not in WORKFLOW
    assert "--allow-unauthenticated" not in WORKFLOW


def test_the_prod_deploy_account_is_never_used():
    assert "vars.DEPLOY_SERVICE_ACCOUNT" not in WORKFLOW
    assert "vars.GCP_PROJECT_ID" not in WORKFLOW


def test_no_text_from_the_pr_is_pasted_into_a_script():
    for job in JOBS:
        for expression in re.findall(r"\$\{\{(.*?)\}\}", _scripts(job)):
            assert "github.event" not in expression and "head_ref" not in expression, expression


def test_actions_are_pinned_to_a_commit():
    for uses in re.findall(r"uses:\s*(\S+)", WORKFLOW):
        assert re.search(r"@[0-9a-f]{40}$", uses), uses


def test_a_plain_docker_build_still_makes_the_production_image():
    dockerfile = (ROOT / "DOCKERFILE").read_text(encoding="utf-8")
    stages = re.findall(r"^FROM \S+(?: AS (\S+))?$", dockerfile, re.MULTILINE)
    assert stages[-1] == "production"
    after_preview = dockerfile.split("AS preview\n", 1)[1]
    assert re.search(r"^FROM app AS production$", after_preview, re.MULTILINE)


def test_the_production_stage_never_sees_the_sample_data():
    dockerfile = (ROOT / "DOCKERFILE").read_text(encoding="utf-8")
    instructions = re.sub(r"^#.*$", "", dockerfile, flags=re.MULTILINE)
    before, rest = instructions.split("FROM app AS preview", 1)
    assert "previewdata" not in before
    assert "previewdata" not in rest.split("FROM app AS production", 1)[1]


def test_the_preview_boot_script_refuses_any_other_environment():
    """It migrates and seeds, so it must never run against production's settings."""
    script = (ROOT / "entrypoint-preview.sh").read_text(encoding="utf-8")
    guard, rest = script.split("flask db upgrade", 1)
    assert 'if [ "$APP_ENV" != "preview" ]' in guard and "exit 1" in guard
    assert "flask seed-preview" in rest and "entrypoint.sh" in rest
    assert b"\r\n" not in (ROOT / "entrypoint-preview.sh").read_bytes()
