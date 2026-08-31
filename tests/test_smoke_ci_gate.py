from __future__ import annotations

import json
from pathlib import Path

import pytest

from vyro_growth.cli import build_parser, main
from vyro_growth.config import Settings
from vyro_growth.smoke_ci_gate import (
    SmokeCiGateError,
    format_smoke_ci_gate_summary,
    validate_smoke_ci_output,
)


def _valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "completed",
        "environment": "development",
        "local_only": True,
        "isolated_demo_database": True,
        "executed": 0,
        "live_action": False,
        "outbound_attempted": False,
        "live_call_attempted": False,
        "recommendation_applied": False,
        "spend_attempted": False,
        "campaign_launched": False,
        "pages_published": False,
        "ads_launched": False,
        "owner_approved": False,
        "dry_run_only": True,
        "no_execution": True,
        "operator_halt_before": "halted",
        "operator_halt_after": "halted",
        "outbound_enabled": False,
        "live_providers_enabled": False,
        "live_providers": {
            "personalization": False,
            "reply_classification": False,
            "campaign": False,
            "calendar": False,
            "voice": False,
        },
        "counts": {"executed": 0},
        "statuses": {"operator_halt": "halted"},
        "blocker_codes": ["execution_disabled_in_this_phase"],
        "readiness_statuses": {"blocked": 1},
        "action_readiness": {
            "candidate_count": 1,
            "live_action": False,
            "executed": 0,
            "owner_approved": False,
        },
        "steps": {
            "review_decisions": {"recorded": 1, "executed": 0},
        },
    }
    payload.update(overrides)
    return payload


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True)


def test_parser_accepts_check_smoke_output() -> None:
    parser = build_parser()
    args = parser.parse_args(["check-smoke-output", "--file", "smoke-output.json"])

    assert args.command == "check-smoke-output"
    assert args.file == "smoke-output.json"


def test_valid_payload_passes_ci_gate() -> None:
    payload = validate_smoke_ci_output(_json(_valid_payload()))

    assert payload["executed"] == 0
    assert payload["live_action"] is False
    assert payload["isolated_demo_database"] is True
    summary = format_smoke_ci_gate_summary(payload)
    assert "CI smoke gate: passed" in summary
    assert "executed=0" in summary


def test_gate_fails_when_executed_is_not_zero() -> None:
    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(_valid_payload(executed=1)))

    assert exc.value.code == "unsafe_side_effect"
    assert "executed" in exc.value.message
    assert "sk-testsecret" not in exc.value.message


def test_gate_fails_on_live_action_or_outbound() -> None:
    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(_valid_payload(live_action=True)))
    assert exc.value.code == "unsafe_side_effect"

    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(_valid_payload(outbound_attempted=True)))
    assert exc.value.code == "unsafe_side_effect"

    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(_valid_payload(owner_approved=True)))
    assert exc.value.code == "unsafe_side_effect"


def test_gate_fails_when_required_dry_run_flags_missing() -> None:
    payload = _valid_payload(dry_run_only=False)
    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(payload))
    assert exc.value.code == "missing_required_field"


def test_gate_fails_when_live_provider_flag_is_true() -> None:
    payload = _valid_payload()
    payload["live_providers"] = {"voice": True}
    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output(_json(payload))
    assert exc.value.code == "live_provider_enabled"


def test_gate_fails_on_email_phone_phi_and_secrets() -> None:
    cases = (
        {"statuses": {"note": "demo.operator@example.invalid"}},
        {"statuses": {"note": "5550100100"}},
        {"statuses": {"note": "patient diagnosis"}},
        {"statuses": {"note": "sk-testsecretvalue"}},
        {"statuses": {"note": "Bearer secret"}},
        {"steps": {"body": "hidden copy"}},
        {"email": "redacted"},
    )
    for override in cases:
        with pytest.raises(SmokeCiGateError) as exc:
            validate_smoke_ci_output(_json(_valid_payload(**override)))
        assert exc.value.code in {"forbidden_sensitive_value", "forbidden_content_key"}
        assert "demo.operator@example.invalid" not in exc.value.message
        assert "sk-testsecretvalue" not in exc.value.message


def test_gate_fails_on_invalid_json() -> None:
    with pytest.raises(SmokeCiGateError) as exc:
        validate_smoke_ci_output("not-json")
    assert exc.value.code == "invalid_json"


def test_cli_check_smoke_output_passes_real_local_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("vyro_growth.cli.get_settings", lambda: Settings(environment="development"))

    smoke_code = main(["smoke-dry-run", "--local-only", "--json"])
    smoke_out = capsys.readouterr()
    assert smoke_code == 0
    smoke_file = tmp_path / "smoke-output.json"
    smoke_file.write_text(smoke_out.out, encoding="utf-8")

    check_code = main(["check-smoke-output", "--file", str(smoke_file)])
    check_out = capsys.readouterr()
    assert check_code == 0
    assert "CI smoke gate: passed" in check_out.out
    assert "executed=0" in check_out.out
    assert "live_action=false" in check_out.out
    assert "isolated_demo_database=true" in check_out.out
    assert "demo.operator@example.invalid" not in check_out.out
    assert "demo.operator@example.invalid" not in smoke_out.out


def test_cli_check_smoke_output_fails_unsafe_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke_file = tmp_path / "unsafe.json"
    smoke_file.write_text(_json(_valid_payload(executed=1)), encoding="utf-8")

    exit_code = main(["check-smoke-output", "--file", str(smoke_file)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unsafe_side_effect" in captured.err
    assert captured.out == ""


def test_cli_check_smoke_output_fails_missing_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["check-smoke-output", "--file", str(tmp_path / "missing.json")])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unreadable_input" in captured.err


def test_ci_workflow_runs_local_only_smoke_gate() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "vyro-growth smoke-dry-run --local-only --json" in workflow
    assert "vyro-growth check-smoke-output --file" in workflow
    assert "smoke-dry-run:" in workflow
    assert 'OUTBOUND_ENABLED: "false"' in workflow
    assert "OPENAI_PERSONALIZATION_ENABLED: \"false\"" in workflow
    assert "SMARTLEAD_LIVE_ENABLED: \"false\"" in workflow
    assert "GOOGLE_CALENDAR_LIVE_ENABLED: \"false\"" in workflow
    assert "VOICE_LIVE_ENABLED: \"false\"" in workflow
    assert "unset DATABASE_URL" in workflow
    assert "OPENAI_API_KEY" in workflow
    assert "DATABASE_URL:" not in workflow
    assert "npx" not in workflow
    assert "openai.com" not in workflow.lower()
    sanitized = workflow.replace("sk-|AIza|BEGIN PRIVATE KEY", "")
    assert "sk-" not in sanitized
    assert "AIza" not in sanitized
    assert "BEGIN PRIVATE KEY" not in sanitized
