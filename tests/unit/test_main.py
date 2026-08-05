from types import SimpleNamespace

import pytest
from github.GithubException import GithubException

import repo_manager.main as main_module


class _ActionToolkitRecorder:
    def __init__(self):
        self.outputs = {}
        self.failed_messages = []
        self.warnings = []
        self.errors = []

    def set_output(self, key, value):
        self.outputs[key] = value

    def set_failed(self, message):
        self.failed_messages.append(str(message))

    def warning(self, message):
        self.warnings.append(str(message))

    def error(self, message):
        self.errors.append(str(message))

    def info(self, _message):
        return None

    def debug(self, _message):
        return None


def _config(**overrides):
    base = {
        "settings": None,
        "collaborators": None,
        "labels": None,
        "branch_protections": None,
        "rulesets": None,
        "secrets": None,
        "variables": None,
        "environments": None,
        "batch_file_operations": None,
        "org_settings": None,
        "teams": None,
        "org_rulesets": None,
        "org_secrets": None,
        "org_variables": None,
        "org_labels": None,
        "enterprise_settings": None,
        "enterprise_rulesets": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _inputs(action="check", fail_on_diff="false"):
    return {
        "action": action,
        "settings_file": "settings.yml",
        "scope": "repo",
        "fail_on_diff": fail_on_diff,
        "repo_object": SimpleNamespace(full_name="owner/repo"),
        "token": None,
        "github_server_url": "https://api.github.com",
        "org_object": None,
        "enterprise_requester": None,
        "enterprise_slug": None,
    }


def _patch_common(monkeypatch, recorder, *, inputs, config_obj):
    monkeypatch.setattr(main_module, "actions_toolkit", recorder)
    monkeypatch.setattr(main_module, "get_inputs", lambda: inputs)
    monkeypatch.setattr(main_module, "load_config", lambda *_args, **_kwargs: config_obj)
    monkeypatch.setattr(main_module, "generate", lambda *_args, **_kwargs: "summary")


def test_check_passed_with_permission_warning_sets_structured_outputs(monkeypatch):
    recorder = _ActionToolkitRecorder()
    cfg = _config(settings=SimpleNamespace())
    inp = _inputs(action="check", fail_on_diff="false")
    _patch_common(monkeypatch, recorder, inputs=inp, config_obj=cfg)

    def _raise_permission(*_args, **_kwargs):
        raise GithubException(status=403, data={"message": "forbidden"}, headers=None)

    monkeypatch.setattr(main_module, "check_repo_settings", _raise_permission)

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert recorder.outputs["result"] == "Check passed"
    assert recorder.outputs["result_code"] == "check_passed"
    assert recorder.outputs["diff_detected"] == "false"
    assert recorder.outputs["warning_count"] == "1"
    assert recorder.outputs["permission_warning_count"] == "1"
    assert recorder.failed_messages == []


def test_check_diff_non_blocking_sets_check_diff_result_code(monkeypatch):
    recorder = _ActionToolkitRecorder()
    cfg = _config(settings=SimpleNamespace())
    inp = _inputs(action="check", fail_on_diff="false")
    _patch_common(monkeypatch, recorder, inputs=inp, config_obj=cfg)

    monkeypatch.setattr(main_module, "check_repo_settings", lambda *_args, **_kwargs: (False, {"k": "v"}))

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert recorder.outputs["result"] == "Check completed, diff detected"
    assert recorder.outputs["result_code"] == "check_diff"
    assert recorder.outputs["diff_detected"] == "true"
    assert recorder.failed_messages == []


def test_check_diff_blocking_sets_failed_diff_result_code(monkeypatch):
    recorder = _ActionToolkitRecorder()
    cfg = _config(settings=SimpleNamespace())
    inp = _inputs(action="check", fail_on_diff="true")
    _patch_common(monkeypatch, recorder, inputs=inp, config_obj=cfg)

    monkeypatch.setattr(main_module, "check_repo_settings", lambda *_args, **_kwargs: (False, {"k": "v"}))

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert recorder.outputs["result"] == "Check failed, diff detected"
    assert recorder.outputs["result_code"] == "check_failed_diff"
    assert recorder.outputs["diff_detected"] == "true"
    assert recorder.failed_messages == ["Diff detected"]


def test_apply_failure_sets_apply_failed_result_code(monkeypatch):
    recorder = _ActionToolkitRecorder()
    cfg = _config(settings=SimpleNamespace())
    inp = _inputs(action="apply", fail_on_diff="false")
    _patch_common(monkeypatch, recorder, inputs=inp, config_obj=cfg)

    monkeypatch.setattr(main_module, "check_repo_settings", lambda *_args, **_kwargs: (False, {"k": "v"}))
    monkeypatch.setattr(
        main_module,
        "update_settings",
        lambda *_args, **_kwargs: ([{"type": "settings-update", "error": "boom"}], {}),
    )

    main_module.main()

    assert recorder.outputs["result"] == "Apply failed"
    assert recorder.outputs["result_code"] == "apply_failed"
    assert recorder.failed_messages == ["Errors during apply"]


def test_apply_success_sets_apply_passed_result_code(monkeypatch):
    recorder = _ActionToolkitRecorder()
    cfg = _config(settings=SimpleNamespace())
    inp = _inputs(action="apply", fail_on_diff="false")
    _patch_common(monkeypatch, recorder, inputs=inp, config_obj=cfg)

    monkeypatch.setattr(main_module, "check_repo_settings", lambda *_args, **_kwargs: (False, {"k": "v"}))
    monkeypatch.setattr(main_module, "update_settings", lambda *_args, **_kwargs: ([], {"ok": "done"}))

    main_module.main()

    assert recorder.outputs["result"] == "Apply successful"
    assert recorder.outputs["result_code"] == "apply_passed"
    assert recorder.failed_messages == []
