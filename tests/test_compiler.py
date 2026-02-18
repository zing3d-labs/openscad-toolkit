"""Unit tests for scadtools.compiler."""

import os
import pathlib

import pytest

from scadtools.compiler import (
    compile_scad,
    extract_modules_and_functions,
    extract_other_statements,
    extract_top_level_items,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# extract_top_level_items
# ---------------------------------------------------------------------------


def test_etli_single_var():
    lines = ["x = 5;\n"]
    output, vars_ = extract_top_level_items(lines)
    assert any("x = 5;" in line for line in output)
    assert "x" in vars_


def test_etli_multiline_var():
    lines = ["Colors = [\n", '  "red",\n', '  "blue"\n', "];\n"]
    output, vars_ = extract_top_level_items(lines)
    assert "Colors" in vars_
    assert any("Colors" in line for line in output)
    assert any('"red"' in line for line in output)


def test_etli_skips_module_internals():
    lines = ["module foo() {\n", "  inner = 5;\n", "}\n"]
    output, vars_ = extract_top_level_items(lines)
    assert not any("inner" in line for line in output)
    assert "inner" not in vars_


def test_etli_deduplication():
    lines = ["x = 5;\n"]
    output, vars_ = extract_top_level_items(lines, defined_variables={"x"})
    assert not any("x = 5" in line for line in output)
    assert "x" not in vars_


def test_etli_preserves_customizer_comments():
    lines = ["/* [Basic Settings] */\n", "\n", "// Width\n", "Width = 10;\n"]
    output, vars_ = extract_top_level_items(lines)
    joined = "".join(output)
    assert "/* [Basic Settings] */" in joined
    assert "// Width" in joined
    assert "Width = 10;" in joined


def test_etli_preserves_dropdown_comment():
    lines = ['Material = "PLA"; // [PLA, PETG, ABS]\n']
    output, vars_ = extract_top_level_items(lines)
    joined = "".join(output)
    assert "// [PLA, PETG, ABS]" in joined
    assert "Material" in vars_


def test_etli_skips_include_lines():
    lines = ["use <some_file.scad>\n", "x = 1;\n"]
    output, vars_ = extract_top_level_items(lines)
    assert not any("use <" in line for line in output)
    assert "x" in vars_


def test_etli_skips_function_definitions():
    lines = ["function double(x) = x * 2;\n"]
    output, vars_ = extract_top_level_items(lines)
    assert not any("function" in line for line in output)


# ---------------------------------------------------------------------------
# extract_other_statements
# ---------------------------------------------------------------------------


def test_eos_module_call():
    lines = ["module foo() { cube(1); }\n", "foo();\n"]
    output = extract_other_statements(lines)
    assert any("foo();" in line for line in output)


def test_eos_skips_variable_assignments():
    lines = ["x = 5;\n", "foo();\n"]
    output = extract_other_statements(lines)
    assert not any("x = 5" in line for line in output)
    assert any("foo();" in line for line in output)


def test_eos_skips_module_definitions():
    lines = ["module bar() {\n", "  cube(1);\n", "}\n", "bar();\n"]
    output = extract_other_statements(lines)
    assert not any("module bar" in line for line in output)
    assert any("bar();" in line for line in output)


def test_eos_multiline_call():
    lines = ["multilineBox(\n", "  5,\n", "  10,\n", "  15\n", ");\n"]
    output = extract_other_statements(lines)
    assert any("multilineBox" in line for line in output)
    # All lines of the call should be included
    assert len([line for line in output if line.strip()]) == 5


def test_eos_skips_include_lines():
    lines = ["use <lib.scad>\n", "foo();\n"]
    output = extract_other_statements(lines)
    assert not any("use <" in line for line in output)


# ---------------------------------------------------------------------------
# extract_modules_and_functions
# ---------------------------------------------------------------------------


def test_emf_basic_module():
    lines = ["x = 5;\n", "module foo() {\n", "  cube(1);\n", "}\n", "foo();\n"]
    output = extract_modules_and_functions(lines)
    assert any("module foo" in line for line in output)
    assert not any("x = 5" in line for line in output)
    assert not any("foo();" in line for line in output)


def test_emf_function():
    lines = ["function double(x) = x * 2;\n"]
    output = extract_modules_and_functions(lines)
    assert any("function double" in line for line in output)


def test_emf_skips_top_level_vars():
    lines = ["Width = 10;\n", "module box() {\n", "  cube(Width);\n", "}\n"]
    output = extract_modules_and_functions(lines)
    assert any("module box" in line for line in output)
    # Width at top level should not appear, but Width inside module body should
    assert any("cube(Width)" in line for line in output)


def test_emf_multiline_module_signature():
    lines = [
        "module multilineBox(\n",
        "  width,\n",
        "  depth) {\n",
        "  cube([width, depth]);\n",
        "}\n",
    ]
    output = extract_modules_and_functions(lines)
    assert any("module multilineBox" in line for line in output)
    assert any("cube" in line for line in output)


# ---------------------------------------------------------------------------
# compile_scad — end-to-end
# ---------------------------------------------------------------------------


def test_compile_simple():
    result = compile_scad(str(FIXTURES / "simple.scad"))
    assert "Width = 10;" in result
    assert "Height = 20;" in result
    assert "module simpleBox" in result
    assert "simpleBox();" in result


def test_compile_no_use_in_output():
    """The compiled output should not contain raw use/include directives."""
    result = compile_scad(str(FIXTURES / "with_use.scad"))
    assert "use <used_module.scad>" not in result


def test_compile_use_inlines_module():
    result = compile_scad(str(FIXTURES / "with_use.scad"))
    assert "module usedHelper" in result
    assert "usedHelper(Size)" in result


def test_compile_include_inlines_all():
    result = compile_scad(str(FIXTURES / "with_include.scad"))
    assert "includedVar = 100" in result
    assert "module includedModule" in result
    assert "include <included_file.scad>" not in result


def test_compile_library_prefix_preserved():
    result = compile_scad(str(FIXTURES / "with_library.scad"), library_prefixes=["BOSL2/"])
    assert "use <BOSL2/std.scad>" in result
    # Library include should appear before the module body
    lib_pos = result.index("use <BOSL2/std.scad>")
    module_pos = result.index("module libraryExample")
    assert lib_pos < module_pos


def test_compile_library_not_inlined_as_file():
    """Without a prefix, missing library file keeps the original line (warning)."""
    # This just verifies it doesn't crash on missing library files
    result = compile_scad(str(FIXTURES / "with_library.scad"), library_prefixes=[])
    assert "LibSize = 30" in result


def test_compile_customizer_comments_preserved():
    result = compile_scad(str(FIXTURES / "customizer.scad"))
    assert "/* [Basic Settings] */" in result
    assert "/* [Advanced] */" in result
    assert "/* [Hidden] */" in result
    assert "// [PLA, PETG, ABS]" in result


def test_compile_multiline_assignment():
    result = compile_scad(str(FIXTURES / "multiline.scad"))
    assert "Colors" in result
    assert '"red"' in result


def test_compile_nested_dependency():
    result = compile_scad(str(FIXTURES / "nested/deep.scad"))
    assert "module depModule" in result
    assert "depModule()" in result
    assert "use <dep.scad>" not in result


def test_compile_output_file(tmp_path):
    output = str(tmp_path / "out.scad")
    compile_scad(str(FIXTURES / "simple.scad"), output=output)
    assert os.path.exists(output)
    content = pathlib.Path(output).read_text()
    assert "Width = 10;" in content


def test_compile_output_file_return_value(tmp_path):
    output = str(tmp_path / "out.scad")
    result = compile_scad(str(FIXTURES / "simple.scad"), output=output)
    assert isinstance(result, str)
    assert "Width = 10;" in result


def test_compile_missing_file():
    with pytest.raises(FileNotFoundError):
        compile_scad("nonexistent.scad")


def test_compile_no_library_prefix_by_default():
    """compile_scad accepts None for library_prefixes."""
    result = compile_scad(str(FIXTURES / "simple.scad"), library_prefixes=None)
    assert "Width = 10;" in result


def test_compile_block_statement():
    """Block statements (ending with }) should be fully preserved."""
    result = compile_scad(str(FIXTURES / "block_statement.scad"))
    assert "down(1) diff()" in result
    assert "attach(BOTTOM)" in result  # line after an intermediate ;


def test_compile_variable_with_function_call():
    """Variables assigned from function calls like max() should be extracted."""
    result = compile_scad(str(FIXTURES / "block_statement.scad"))
    assert "Width = max(10, 5);" in result
    assert "Height = min(20, 30);" in result
