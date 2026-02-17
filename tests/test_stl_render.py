"""STL rendering tests: compile a fixture, render both original and compiled to STL,
and verify the geometry (facet count) is identical."""

import pathlib
import shutil
import struct
import subprocess

import pytest

from scadtools.compiler import compile_scad

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

openscad = pytest.mark.skipif(
    not shutil.which("openscad"),
    reason="openscad not installed",
)


def _facet_count(stl_path: pathlib.Path) -> int:
    """Return triangle count from a binary STL file."""
    data = stl_path.read_bytes()
    # Binary STL layout: 80-byte header, then uint32 triangle count
    return struct.unpack_from("<I", data, 80)[0]


def _render(scad_path: pathlib.Path, out: pathlib.Path) -> None:
    subprocess.run(
        ["openscad", "-o", str(out), str(scad_path)],
        check=True,
        capture_output=True,
    )


@openscad
def test_stl_simple(tmp_path):
    """Compiled simple.scad renders to identical geometry (cube)."""
    src = FIXTURES / "simple.scad"
    compiled_scad = tmp_path / "compiled.scad"
    compiled_scad.write_text(compile_scad(str(src)))

    orig_stl = tmp_path / "orig.stl"
    compiled_stl = tmp_path / "compiled.stl"
    _render(src, orig_stl)
    _render(compiled_scad, compiled_stl)

    assert _facet_count(orig_stl) == _facet_count(compiled_stl)


@openscad
def test_stl_with_use(tmp_path):
    """Compiled with_use.scad renders to identical geometry (sphere via use-inlined module)."""
    src = FIXTURES / "with_use.scad"
    compiled_scad = tmp_path / "compiled.scad"
    compiled_scad.write_text(compile_scad(str(src)))

    orig_stl = tmp_path / "orig.stl"
    compiled_stl = tmp_path / "compiled.stl"
    _render(src, orig_stl)
    _render(compiled_scad, compiled_stl)

    assert _facet_count(orig_stl) == _facet_count(compiled_stl)


@openscad
def test_stl_with_include(tmp_path):
    """Compiled with_include.scad renders to identical geometry (cylinder via include)."""
    src = FIXTURES / "with_include.scad"
    compiled_scad = tmp_path / "compiled.scad"
    compiled_scad.write_text(compile_scad(str(src)))

    orig_stl = tmp_path / "orig.stl"
    compiled_stl = tmp_path / "compiled.stl"
    _render(src, orig_stl)
    _render(compiled_scad, compiled_stl)

    assert _facet_count(orig_stl) == _facet_count(compiled_stl)


@openscad
def test_stl_nested(tmp_path):
    """Compiled nested/deep.scad renders to identical geometry (sphere via nested dep)."""
    src = FIXTURES / "nested" / "deep.scad"
    compiled_scad = tmp_path / "compiled.scad"
    compiled_scad.write_text(compile_scad(str(src)))

    orig_stl = tmp_path / "orig.stl"
    compiled_stl = tmp_path / "compiled.stl"
    _render(src, orig_stl)
    _render(compiled_scad, compiled_stl)

    assert _facet_count(orig_stl) == _facet_count(compiled_stl)
