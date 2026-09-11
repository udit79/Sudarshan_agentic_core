from pathlib import Path
from threading import Event, Timer

import pytest

from pipelines.common.sandbox import (
    ContainerSandboxAdapter,
    LocalSandboxAdapter,
    SandboxPolicy,
    SandboxViolation,
    sandbox_adapter_from_environment,
)


def _adapter() -> LocalSandboxAdapter:
    return LocalSandboxAdapter(SandboxPolicy(allowed_commands=frozenset({"python"})))


def test_sandbox_runs_allowlisted_command_and_collects_contained_output() -> None:
    result = _adapter().execute(
        "python",
        ("-c", "from pathlib import Path; Path('out.txt').write_text('ok')"),
        expected_outputs=("out.txt",),
    )

    assert result.succeeded is True
    assert result.artifacts[0].size_bytes == 2
    assert len(result.artifacts[0].sha256) == 64


def test_sandbox_rejects_unallowlisted_commands_and_redacts_diagnostics() -> None:
    with pytest.raises(SandboxViolation):
        _adapter().execute("cmd", ("/c", "echo unsafe"))

    result = _adapter().execute("python", ("-c", "print('api_key=secret-value')"))
    assert "secret-value" not in result.stdout
    assert "[redacted]" in result.stdout


def test_sandbox_marks_timeout_and_cooperative_cancellation() -> None:
    policy = SandboxPolicy(allowed_commands=frozenset({"python"}), timeout_seconds=0.05)
    timed = LocalSandboxAdapter(policy).execute("python", ("-c", "import time; time.sleep(1)"))
    assert timed.timed_out is True

    cancelled = Event()
    cancelled.set()
    result = _adapter().execute("python", ("-c", "print('done')"), cancel_event=cancelled)
    assert result.cancelled is True


def test_sandbox_cancels_a_running_process() -> None:
    cancelled = Event()
    trigger = Timer(0.05, cancelled.set)
    trigger.start()
    result = _adapter().execute("python", ("-c", "import time; time.sleep(5)"), cancel_event=cancelled)

    assert result.cancelled is True
    assert result.succeeded is False


def test_container_command_is_shell_free_and_confined() -> None:
    policy = SandboxPolicy(
        allowed_commands=frozenset({"python"}),
        environment={"LANG": "C"},
    )
    adapter = ContainerSandboxAdapter(policy, image="python:3.12-slim", runtime="docker")
    argv = adapter.command_argv("python", ("-c", "print('ok')"), workspace=Path("/tmp/job"))

    assert argv[0:4] == ["docker", "run", "--rm", "--init"]
    assert "--network" in argv and argv[argv.index("--network") + 1] == "none"
    assert "--read-only" in argv
    assert "--cap-drop" in argv and argv[argv.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in argv
    assert "--volume" in argv and ":/workspace:rw" in argv[argv.index("--volume") + 1]
    assert argv[-3:] == ["python", "-c", "print('ok')"]
    assert all("&&" not in value and ";" not in value for value in argv)


def test_sandbox_factory_requires_explicit_local_opt_in() -> None:
    policy = SandboxPolicy(allowed_commands=frozenset({"python"}))
    with pytest.raises(SandboxViolation, match="explicit opt-in"):
        sandbox_adapter_from_environment(
            policy,
            environ={"SUDARSHAN_SANDBOX_MODE": "local", "SUDARSHAN_ALLOW_LOCAL_SANDBOX": "false"},
        )

    adapter = sandbox_adapter_from_environment(
        policy,
        environ={"SUDARSHAN_SANDBOX_MODE": "local", "SUDARSHAN_ALLOW_LOCAL_SANDBOX": "true"},
    )
    assert isinstance(adapter, LocalSandboxAdapter)


def test_sandbox_factory_defaults_to_container() -> None:
    policy = SandboxPolicy(allowed_commands=frozenset({"python"}))
    adapter = sandbox_adapter_from_environment(
        policy,
        environ={"SUDARSHAN_SANDBOX_CONTAINER_IMAGE": "python:3.12-slim"},
    )
    assert isinstance(adapter, ContainerSandboxAdapter)
