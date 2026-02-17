"""CLI integration tests for scad-compiler."""

import os
import pathlib
import subprocess

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["scad-compiler", *args], capture_output=True, text=True)


def test_cli_help():
    result = run("--help")
    assert result.returncode == 0
    assert "scad-compiler" in result.stdout.lower() or "usage" in result.stdout.lower()


def test_cli_basic_stdout():
    result = run(str(FIXTURES / "simple.scad"))
    assert result.returncode == 0
    assert "Width = 10;" in result.stdout
    assert "module simpleBox" in result.stdout
    assert "simpleBox();" in result.stdout


def test_cli_output_file(tmp_path):
    output = str(tmp_path / "out.scad")
    result = run(str(FIXTURES / "simple.scad"), "-o", output)
    assert result.returncode == 0
    assert os.path.exists(output)
    content = pathlib.Path(output).read_text()
    assert "Width = 10;" in content


def test_cli_library_prefix(tmp_path):
    result = run(str(FIXTURES / "with_library.scad"), "-l", "BOSL2/")
    assert result.returncode == 0
    assert "use <BOSL2/std.scad>" in result.stdout


def test_cli_multiple_library_prefixes():
    result = run(
        str(FIXTURES / "with_library.scad"),
        "-l",
        "BOSL2/",
        "-l",
        "QuackWorks/",
    )
    assert result.returncode == 0
    assert "use <BOSL2/std.scad>" in result.stdout


def test_cli_missing_file():
    result = run("nonexistent.scad")
    assert result.returncode == 1
    assert "ERROR" in result.stderr


def test_cli_with_use():
    result = run(str(FIXTURES / "with_use.scad"))
    assert result.returncode == 0
    assert "module usedHelper" in result.stdout
    assert "use <used_module.scad>" not in result.stdout


def test_cli_with_include():
    result = run(str(FIXTURES / "with_include.scad"))
    assert result.returncode == 0
    assert "includedVar = 100" in result.stdout
    assert "include <included_file.scad>" not in result.stdout


def test_cli_nested():
    result = run(str(FIXTURES / "nested/deep.scad"))
    assert result.returncode == 0
    assert "module depModule" in result.stdout
    assert "depModule()" in result.stdout
