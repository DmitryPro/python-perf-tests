import json
from pathlib import Path

import pytest

from benchmarks import docker_runner


@pytest.fixture()
def docker_tree(tmp_path: Path) -> Path:
    root = tmp_path / "docker"
    root.mkdir()
    for name in ("py3.7", "py3.11"):
        directory = root / name
        directory.mkdir()
        (directory / "Dockerfile").write_text("FROM scratch\n")
    return root


def test_discover_targets(docker_tree: Path) -> None:
    targets = docker_runner.discover_targets(docker_tree)
    assert [t.version for t in targets] == ["3.11", "3.7"]
    # Directories are sorted lexicographically so 3.11 precedes 3.7
    assert all(target.dockerfile.name == "Dockerfile" for target in targets)


def test_execute_runs_build_and_run(monkeypatch: pytest.MonkeyPatch, docker_tree: Path, tmp_path: Path) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append((tuple(command), dry_run))

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    docker_runner.execute(
        context=docker_tree.parent,
        docker_root=docker_tree,
        results_dir=tmp_path / "results",
        aggregate=False,
    )

    run_commands = [cmd for cmd, _ in commands if cmd[:3] == ("docker", "run", "--rm")]
    assert len(run_commands) == 2
    assert {
        next(value for value in cmd if value.startswith("python-perf:"))
        for cmd in run_commands
    } == {"python-perf:3.11", "python-perf:3.7"}
    volume_args = [cmd for cmd in run_commands if "-v" in cmd]
    assert len(volume_args) == 2
    build_commands = [cmd for cmd, _ in commands if cmd[:3] == ("docker", "build", "-f")]
    assert len(build_commands) == 2


def test_execute_resets_results_dir(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path, tmp_path: Path
) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append((tuple(command), dry_run))

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "stale.json").write_text("{}")
    nested = results_dir / "nested"
    nested.mkdir()
    (nested / "artifact.txt").write_text("data")

    docker_runner.execute(
        context=docker_tree.parent,
        docker_root=docker_tree,
        results_dir=results_dir,
        aggregate=False,
        skip_build=True,
    )

    assert results_dir.exists()
    assert list(results_dir.iterdir()) == []


def test_execute_keeps_results_dir_on_dry_run(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path, tmp_path: Path
) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append((tuple(command), dry_run))

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    stale_file = results_dir / "stale.json"
    stale_file.write_text("{}")

    docker_runner.execute(
        context=docker_tree.parent,
        docker_root=docker_tree,
        results_dir=results_dir,
        aggregate=False,
        dry_run=True,
    )

    assert results_dir.exists()
    assert stale_file.exists()
    assert stale_file.read_text() == "{}"


def test_main_supports_run_cmd(monkeypatch: pytest.MonkeyPatch, docker_tree: Path) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    exit_code = docker_runner.main(
        [
            "--docker-root",
            str(docker_tree),
            "--context",
            str(docker_tree.parent),
            "--dry-run",
            "--run-cmd",
            "python -m pytest -q",
            "--results-dir",
            str(docker_tree.parent / "results"),
        ]
    )
    assert exit_code == 0
    run_commands = [cmd for cmd in commands if cmd[:3] == ["docker", "run", "--rm"]]
    assert len(run_commands) == 2
    assert {
        next(value for value in cmd if value.startswith("python-perf:"))
        for cmd in run_commands
    } == {"python-perf:3.11", "python-perf:3.7"}
    assert run_commands[0][-4:] == ["python", "-m", "pytest", "-q"]


def test_main_supports_iteration_overrides(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path
) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append((command, dry_run))

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    exit_code = docker_runner.main(
        [
            "--docker-root",
            str(docker_tree),
            "--context",
            str(docker_tree.parent),
            "--dry-run",
            "--iterations",
            "25",
            "--repeat",
            "3",
            "--results-dir",
            str(docker_tree.parent / "results"),
        ]
    )

    assert exit_code == 0
    run_commands = [cmd for cmd, _ in commands if cmd[:3] == ["docker", "run", "--rm"]]
    assert len(run_commands) == 2
    assert run_commands[0][-7:] == [
        "python",
        "-m",
        "benchmarks.benchmark",
        "--iterations",
        "25",
        "--repeat",
        "3",
    ]
    # Check both overrides are applied
    assert "--iterations" in run_commands[0]
    assert "--repeat" in run_commands[0]


def test_main_rejects_conflicting_command(monkeypatch: pytest.MonkeyPatch, docker_tree: Path) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append(command)

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    exit_code = docker_runner.main(
        [
            "--docker-root",
            str(docker_tree),
            "--context",
            str(docker_tree.parent),
            "--dry-run",
            "--run-cmd",
            "python -m pytest -q",
            "--iterations",
            "10",
        ]
    )

    assert exit_code == 1
    assert commands == []


def test_summarize_results(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    payload = {
        "python_implementation": "CPython",
        "python_version": "3.11.7",
        "iterations": 10,
        "repeat": 5,
        "cases": [
            {
                "name": "case1",
                "mean": 0.1,
                "stdev": 0.01,
            },
            {
                "name": "case2",
                "mean": 0.2,
                "stdev": 0.02,
            },
        ],
    }
    payload2 = {
        "python_implementation": "PyPy",
        "python_version": "3.12.1",
        "iterations": 12,
        "repeat": 4,
        "cases": [
            {"name": "case1", "mean": 0.09, "stdev": 0.005},
        ],
    }
    (results_dir / "benchmarks-cpython-3.11.7.json").write_text(json.dumps(payload))
    (results_dir / "benchmarks-pypy-3.12.1.json").write_text(json.dumps(payload2))

    summary_text = docker_runner.summarize_results(results_dir)
    assert summary_text is not None
    assert "case1" in summary_text
    assert "CPython 3.11.7" in summary_text
    assert "total" in summary_text
    summary_payload = json.loads((results_dir / "summary.json").read_text())
    assert summary_payload["python_versions"] == ["3.11.7", "3.12.1"]
    assert summary_payload["python_implementations"] == ["CPython", "PyPy"]
    assert summary_payload["python_runtimes"] == [
        {"python_implementation": "CPython", "python_version": "3.11.7"},
        {"python_implementation": "PyPy", "python_version": "3.12.1"},
    ]
    assert summary_payload["cases"][0]["name"] == "case1"
    first_result = summary_payload["cases"][0]["results"][0]
    assert first_result["iterations"] == 10
    assert first_result["repeat"] == 5
    assert first_result["python_implementation"] == "CPython"


def test_summarize_results_handles_missing(tmp_path: Path) -> None:
    assert docker_runner.summarize_results(tmp_path) is None
