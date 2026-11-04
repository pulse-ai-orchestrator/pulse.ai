from pulse.cli.main import _build_parser, main


def test_parser_accepts_init():
    args = _build_parser().parse_args(["init"])
    assert args.command == "init"
    assert args.force is False


def test_parser_accepts_init_force():
    args = _build_parser().parse_args(["init", "--force"])
    assert args.command == "init"
    assert args.force is True


def test_parser_accepts_doctor_test_acp():
    args = _build_parser().parse_args(["doctor", "--test-acp"])
    assert args.command == "doctor"
    assert args.test_acp is True


def test_parser_accepts_config_init():
    args = _build_parser().parse_args(["config", "init"])
    assert args.command == "config"
    assert args.config_action == "init"


def test_parser_accepts_config_show_workflow():
    args = _build_parser().parse_args(
        ["config", "show", "--workflow", "fluxo-a"],
    )
    assert args.command == "config"
    assert args.config_action == "show"
    assert args.workflow == "fluxo-a"


def test_main_dispatches_init(monkeypatch):
    captured: dict[str, bool] = {}

    def fake_init(*, force: bool = False) -> int:
        captured["force"] = force
        return 0

    monkeypatch.setattr("pulse.tui.app.run_onboarding_app", fake_init)
    assert main(["init", "--force"]) == 0
    assert captured["force"] is True


def test_main_dispatches_doctor(monkeypatch):
    captured: dict[str, bool] = {}

    def fake_doctor(*, test_acp: bool = False, as_json: bool = False) -> int:
        captured["test_acp"] = test_acp
        captured["as_json"] = as_json
        return 0

    monkeypatch.setattr("pulse.cli.main.run_doctor", fake_doctor)
    assert main(["doctor", "--test-acp", "--local"]) == 0
    assert captured == {"test_acp": True, "as_json": False}


def test_parser_accepts_daemon_status():
    args = _build_parser().parse_args(["daemon", "status"])
    assert args.command == "daemon"
    assert args.daemon_action == "status"


def test_main_dispatches_config_init(monkeypatch):
    captured: dict[str, str | None] = {}

    def fake_config(*, action: str = "show", workflow: str | None = None) -> int:
        captured["action"] = action
        captured["workflow"] = workflow
        return 0

    monkeypatch.setattr("pulse.cli.main.run_config_command", fake_config)
    assert main(["config", "init"]) == 0
    assert captured["action"] == "init"
    assert captured["workflow"] is None
