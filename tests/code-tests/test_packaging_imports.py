"""Optional dependency metadata and lightweight imports."""
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    import tomli as tomllib

import subprocess
import sys
import re
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def project_optional_dependencies():
    return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]


def starlette_specifier(extra):
    deps = project_optional_dependencies()[extra]
    matches = [dep for dep in deps if dep.startswith("starlette")]
    assert len(matches) == 1
    return matches[0]


def version_tuple(value):
    return tuple(int(part) for part in value.split("."))


def allows_version(requirement, version):
    clauses = requirement.split("starlette", 1)[1].split(",")
    target = version_tuple(version)
    for clause in clauses:
        match = re.fullmatch(r"(>=|<)([0-9]+(?:\.[0-9]+)*)", clause.strip())
        assert match, f"unsupported Starlette specifier clause: {clause!r}"
        op, boundary = match.groups()
        boundary_tuple = version_tuple(boundary)
        if op == ">=" and target < boundary_tuple:
            return False
        if op == "<" and target >= boundary_tuple:
            return False
    return True


def test_ui_extra_is_jinja_only_and_web_extra_keeps_fastapi_stack():
    optional = project_optional_dependencies()
    assert optional["ui"] == ["jinja2>=3.1,<4.0"]
    assert "jinja2>=3.1,<4.0" in optional["web"]
    assert any(dep.startswith("fastapi>=") for dep in optional["web"])
    assert any(dep.startswith("starlette>=") for dep in optional["web"])
    assert 'tomli>=2.0,<3.0; python_version<"3.11"' in optional["dev"]


def test_web_starlette_window_admits_verified_1x_and_keeps_lower_minimum():
    for extra in ("web", "dev"):
        requirement = starlette_specifier(extra)
        assert allows_version(requirement, "0.40.0")
        assert allows_version(requirement, "1.3.1")
        assert allows_version(requirement, "1.6.0")
        assert not allows_version(requirement, "0.39.9")
        assert not allows_version(requirement, "2.0.0")


def test_dependency_window_has_compatibility_gate():
    workflows = "\n".join(path.read_text() for path in (ROOT / ".github" / "workflows").glob("*.yml"))
    workflows += "\n".join(path.read_text() for path in (ROOT / ".github" / "workflows").glob("*.yaml"))
    web = " ".join(project_optional_dependencies()["web"])
    assert "starlette>=0.40,<2.0" in web
    assert "starlette-line" in workflows
    assert "0.x" in workflows
    assert "1.3.x" in workflows


def test_web_compatibility_install_command_quotes_each_requirement():
    workflow = (ROOT / ".github" / "workflows" / "web-compatibility.yml").read_text()
    assert "${{ matrix.deps }}" not in workflow
    assert '"${{ matrix.fastapi }}" "${{ matrix.starlette }}"' in workflow

    install_line = next(line for line in workflow.splitlines() if "python -m pip install -e" in line)
    command = install_line.split("run:", 1)[1].strip()
    rendered = (command
                .replace("${{ matrix.fastapi }}", "fastapi>=0.110,<1.0")
                .replace("${{ matrix.starlette }}", "starlette>=0.40,<1.0"))
    script = f'python() {{ printf "<%s>\\n" "$@"; }}; {rendered}'
    with tempfile.TemporaryDirectory() as directory:
        result = subprocess.run(["bash", "-lc", script], cwd=directory, text=True,
                                capture_output=True, check=True)
    assert result.stdout.splitlines()[-2:] == ["<fastapi>=0.110,<1.0>", "<starlette>=0.40,<1.0>"]


def test_distribution_exports_new_public_apis():
    script = ("import chatlogin as cl; assert cl.__version__ == '0.1.6.dev1'; "
              "assert cl.AsyncCallbackBackend; assert cl.AsyncCredentialBackend; "
              "assert cl.PrivateSQLite")
    subprocess.run([sys.executable, "-c", script], cwd="/tmp", check=True)


def test_core_import_does_not_load_optional_web_modules():
    script = (
        "import sys, chatlogin; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'starlette' not in sys.modules; "
        "assert 'jinja2' not in sys.modules; "
        "assert chatlogin.__version__ == '0.1.6.dev1'"
    )
    subprocess.run([sys.executable, "-c", script], cwd="/tmp", check=True)
