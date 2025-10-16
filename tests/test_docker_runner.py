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

    run_commands = [list(cmd) for cmd, _ in commands if cmd[:3] == ("docker", "run", "--rm")]
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
        commands.append((tuple(command), dry_run))

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
    run_commands = [list(cmd) for cmd, _ in commands if cmd[:3] == ("docker", "run", "--rm")]
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


def test_main_supports_concurrency_suite(
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
            "--suite",
            "concurrency",
            "--tasks",
            "12",
            "--workers",
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
        "benchmarks.concurrency",
        "--tasks",
        "12",
        "--workers",
        "3",
    ]


def test_execute_runs_disable_gil_variant_for_python_314(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands = []

    def fake_run(command, dry_run=False):
        commands.append((command, dry_run))

    docker_root = tmp_path / "docker"
    context = tmp_path
    docker_root.mkdir()
    target_dir = docker_root / "py3.14"
    target_dir.mkdir()
    (target_dir / "Dockerfile").write_text("FROM scratch\n")

    monkeypatch.setattr(docker_runner, "run_command", fake_run)

    docker_runner.execute(
        context=context,
        docker_root=docker_root,
        dry_run=True,
        aggregate=False,
        suite="concurrency",
    )

    run_commands = [cmd for cmd, _ in commands if cmd[:3] == ["docker", "run", "--rm"]]
    assert len(run_commands) == 2
    regular, nogil = run_commands
    assert "--disable-gil" not in regular
    assert "--disable-gil" in nogil


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


def test_main_rejects_invalid_concurrency_overrides(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path
) -> None:
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
            "--suite",
            "concurrency",
            "--iterations",
            "10",
        ]
    )

    assert exit_code == 1
    assert commands == []


def test_main_rejects_tasks_without_concurrency(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path
) -> None:
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
            "--tasks",
            "5",
        ]
    )

    assert exit_code == 1
    assert commands == []


def test_summarize_results(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    payload = {
        "python_implementation": "CPython",
        "python_version": "3.14.0",
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
    payload3 = {
        "python_implementation": "CPython",
        "python_version": "3.11.7",
        "iterations": 10,
        "repeat": 5,
        "cases": [
            {"name": "case1", "mean": 0.12, "stdev": 0.015},
        ],
    }
    payload4 = {
        "python_implementation": "CPython",
        "python_version": "3.14.0t",
        "iterations": 10,
        "repeat": 5,
        "cases": [
            {"name": "case1", "mean": 0.05, "stdev": 0.01},
        ],
    }
    (results_dir / "benchmarks-cpython-3.14.0.json").write_text(json.dumps(payload))
    (results_dir / "benchmarks-pypy-3.12.1.json").write_text(json.dumps(payload2))
    (results_dir / "benchmarks-cpython-3.11.7-alt.json").write_text(json.dumps(payload3))
    (results_dir / "benchmarks-cpython-3.14.0t.json").write_text(json.dumps(payload4))

    summary_text = docker_runner.summarize_results(results_dir)
    assert summary_text is not None
    assert "case1" in summary_text
    assert "CPython 3.14.0" in summary_text
    assert "total" in summary_text
    assert "faster vs CPython 3.14" in summary_text or "slower vs CPython 3.14" in summary_text
    assert "CPython 3.14.0t" in summary_text
    summary_payload = json.loads((results_dir / "summary.json").read_text())
    assert summary_payload["python_versions"] == ["3.11.7", "3.14.0", "3.14.0t", "3.12.1"]
    assert summary_payload["python_implementations"] == ["CPython", "CPython", "CPython", "PyPy"]
    assert summary_payload["python_runtimes"] == [
        {"python_implementation": "CPython", "python_version": "3.11.7"},
        {"python_implementation": "CPython", "python_version": "3.14.0"},
        {"python_implementation": "CPython", "python_version": "3.14.0t"},
        {"python_implementation": "PyPy", "python_version": "3.12.1"},
    ]
    assert summary_payload["cases"][0]["name"] == "case1"
    first_result = summary_payload["cases"][0]["results"][0]
    assert first_result["iterations"] == 10
    assert first_result["repeat"] == 5
    assert first_result["python_implementation"] == "CPython"
    assert summary_payload["cases"][0]["results"][0]["relative_to_cpython_3_14"] is not None
    relative_values = {
        entry["python_version"]: entry["relative_to_cpython_3_14"]
        for entry in summary_payload["cases"][0]["results"]
    }
    assert relative_values["3.14.0"] == pytest.approx(1.0)
    assert relative_values["3.14.0t"] == pytest.approx(0.5)


def test_baseline_mean_prefers_standard_gil_build() -> None:
    results = [
        {
            "python_implementation": "CPython",
            "python_version": "3.14.0t",
            "mean": 0.05,
        },
        {
            "python_implementation": "CPython",
            "python_version": "3.14.0",
            "mean": 0.1,
        },
    ]
    baseline = docker_runner._baseline_mean(results)
    assert baseline == pytest.approx(0.1)


def test_summarize_results_handles_missing(tmp_path: Path) -> None:
    assert docker_runner.summarize_results(tmp_path) is None


def test_summarize_concurrency_results(tmp_path: Path) -> None:
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    payload = {
        "metadata": {
            "python_implementation": "CPython",
            "python_version": "3.14.0",
            "tasks": 12,
            "workers": 3,
            "gil_disabled": False,
        },
        "workloads": [
            {
                "name": "cpu_bound_fibonacci",
                "category": "cpu",
                "description": "CPU-bound workload",
                "strategies": [
                    {
                        "name": "sequential",
                        "supported": True,
                        "duration": 1.0,
                        "tasks_per_second": 12.0,
                        "speedup_vs_sequential": 1.0,
                    },
                    {
                        "name": "threading",
                        "supported": True,
                        "duration": 0.5,
                        "tasks_per_second": 24.0,
                        "speedup_vs_sequential": 2.0,
                    },
                    {
                        "name": "process",
                        "supported": False,
                        "duration": None,
                        "tasks_per_second": None,
                        "speedup_vs_sequential": None,
                        "reason": "not available",
                    },
                ],
            }
        ],
    }
    payload2 = {
        "metadata": {
            "python_implementation": "CPython",
            "python_version": "3.14.0",
            "tasks": 12,
            "workers": 3,
            "gil_disabled": True,
        },
        "workloads": [
            {
                "name": "cpu_bound_fibonacci",
                "category": "cpu",
                "description": "CPU-bound workload",
                "strategies": [
                    {
                        "name": "sequential",
                        "supported": True,
                        "duration": 0.8,
                        "tasks_per_second": 15.0,
                        "speedup_vs_sequential": 1.0,
                    },
                    {
                        "name": "threading",
                        "supported": True,
                        "duration": 0.4,
                        "tasks_per_second": 30.0,
                        "speedup_vs_sequential": 2.0,
                    },
                ],
            }
        ],
    }
    (results_dir / "concurrency-cpython-3.14.0.json").write_text(json.dumps(payload))
    (results_dir / "concurrency-cpython-3.14.0-nogil.json").write_text(
        json.dumps(payload2)
    )

    summary_text = docker_runner.summarize_results(results_dir, suite="concurrency")
    assert summary_text is not None
    assert "Aggregate concurrency benchmark results" in summary_text
    assert "cpu_bound_fibonacci" in summary_text
    assert "GIL disabled" in summary_text
    summary_payload = json.loads((results_dir / "summary.json").read_text())
    assert summary_payload["suite"] == "concurrency"
    assert summary_payload["workloads"][0]["results"][0]["strategies"]
    assert summary_payload["workloads"][0]["results"][1]["strategies"][0][
        "duration"
    ] == pytest.approx(0.8)


def test_main_uses_suite_specific_results_dirs(
    monkeypatch: pytest.MonkeyPatch, docker_tree: Path
) -> None:
    captured: list[Path] = []

    def fake_execute(*, results_dir: Path, **kwargs):
        captured.append(results_dir)
        return []

    monkeypatch.setattr(docker_runner, "execute", fake_execute)

    exit_code_micro = docker_runner.main(
        [
            "--docker-root",
            str(docker_tree),
            "--context",
            str(docker_tree.parent),
            "--skip-build",
            "--skip-run",
        ]
    )
    exit_code_concurrency = docker_runner.main(
        [
            "--docker-root",
            str(docker_tree),
            "--context",
            str(docker_tree.parent),
            "--skip-build",
            "--skip-run",
            "--suite",
            "concurrency",
        ]
    )

    assert exit_code_micro == 0
    assert exit_code_concurrency == 0
    assert captured[0] == docker_runner.REPO_ROOT / "results" / "micro"
    assert captured[1] == docker_runner.REPO_ROOT / "results" / "concurrency"
