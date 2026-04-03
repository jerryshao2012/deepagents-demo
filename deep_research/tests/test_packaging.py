from pathlib import Path
import tomllib


def test_pyproject_packages_include_skill_modules() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    include = pyproject["tool"]["setuptools"]["packages"]["find"]["include"]

    assert "research_agent" in include
    assert "research_agent.*" in include
