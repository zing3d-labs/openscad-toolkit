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


# Bug regression tests — one test per specific bug fixed in PR #13
# ---------------------------------------------------------------------------
# Bug 1: block statement collector terminated at first internal `;`
#
# Before fix: `inside_statement` ended on any line ending with `;`, so a
# brace-delimited block like `modifier() shape() { ... ; ... }` was truncated
# after the first internal semicolon — the closing `}` and everything after it
# was silently dropped.
#
# Fix: track `statement_brace_depth`; end the statement only when the brace
# depth returns to 0 AND the line ends with `;` or `}`.
# ---------------------------------------------------------------------------


def test_eos_block_statement_not_split_at_internal_semicolon():
    """Brace-delimited block statement must be emitted in full, not truncated at first `;`."""
    lines = [
        "down(1) diff()\n",
        "    cube([10, 20, 2]) {\n",
        "      attach(TOP) cube([5, 5, 1]);\n",  # internal ';' — must NOT end statement
        "      attach(BOTTOM) cube([5, 5, 1]);\n",
        "    }\n",  # closing brace — actual end of statement
    ]
    output = extract_other_statements(lines)
    joined = "".join(output)
    assert "down(1) diff()" in joined
    assert "attach(TOP)" in joined
    assert "attach(BOTTOM)" in joined  # would be missing if statement ended early


# ---------------------------------------------------------------------------
# Bug 2: `==` in a module-call argument misidentified as a variable assignment
#
# Before fix: `"=" in line_without_comment` matched `==`, so a line like
# `down(x == eps ? eps : 0) diff()` was classified as a variable assignment
# and the entire statement was silently dropped.
#
# Fix: only test for `=` in the portion of the line *before* the first `(`.
# ---------------------------------------------------------------------------


def test_eos_equality_operator_not_mistaken_for_assignment():
    """`==` inside a module-call argument must not suppress the statement."""
    lines = [
        "down(x == eps ? eps : 0) diff()\n",
        "    cuboid([10, 20, 2]);\n",
    ]
    output = extract_other_statements(lines)
    joined = "".join(output)
    assert "down(x == eps" in joined
    assert "cuboid" in joined


# ---------------------------------------------------------------------------
# Bug 3: continuation lines of a multi-line variable assignment re-classified
#
# Before fix: the `inside_assignment` guard came *after* the variable-detection
# block, so continuation lines that happened to contain `=` (e.g. ternary
# expressions like `x == 1 ? A : B`) were re-classified as new assignments and
# emitted into the output when they should have been silently consumed.
#
# Fix: move the `inside_assignment` continuation check *before* the
# variable-detection block so continuation lines are never re-examined.
# ---------------------------------------------------------------------------


def test_eos_multiline_assignment_continuation_not_reclassified():
    """Continuation lines of a multi-line assignment must be consumed, not emitted."""
    lines = [
        "my_val =\n",
        "  x == 1 ? A\n",  # contains '==' — must not be re-classified as new assignment
        "  : B;\n",
        "foo();\n",
    ]
    output = extract_other_statements(lines)
    joined = "".join(output)
    assert "my_val" not in joined  # entire assignment skipped
    assert "foo();" in joined  # call after the assignment is preserved


# ---------------------------------------------------------------------------
# Bug 4: variables assigned from function calls excluded from extraction
#
# Before fix: `"("` was in the exclusion keyword list in `extract_top_level_items`,
# so any line like `Width = max(10, 5);` (which contains `(`) was skipped
# entirely and never added to the output.
#
# Fix: remove `"("` from the exclusion list; instead, guard against module-call
# misclassification using VARIABLE_NAME_RE (which requires `word =` at the start).
# ---------------------------------------------------------------------------


def test_etli_variable_with_function_call():
    """Variables assigned via function calls like max() / min() must be extracted."""
    lines = ["Width = max(10, 5);\n", "Height = min(20, 30);\n"]
    output, vars_ = extract_top_level_items(lines)
    assert "Width" in vars_
    assert "Height" in vars_
    joined = "".join(output)
    assert "Width = max(10, 5);" in joined
    assert "Height = min(20, 30);" in joined


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


# ---------------------------------------------------------------------------
# compile_scad — deps_out
# ---------------------------------------------------------------------------


def test_compile_deps_out_entry_file():
    """deps_out should contain the entry file itself."""
    deps: set[str] = set()
    compile_scad(str(FIXTURES / "simple.scad"), deps_out=deps)
    assert any("simple.scad" in p for p in deps)


def test_compile_deps_out_includes_transitive():
    """deps_out should include all transitively referenced local files."""
    deps: set[str] = set()
    compile_scad(str(FIXTURES / "with_include.scad"), deps_out=deps)
    basenames = {pathlib.Path(p).name for p in deps}
    assert "with_include.scad" in basenames
    assert "included_file.scad" in basenames


def test_compile_deps_out_absolute_paths():
    """All paths in deps_out must be absolute."""
    deps: set[str] = set()
    compile_scad(str(FIXTURES / "with_use.scad"), deps_out=deps)
    assert deps, "deps_out should not be empty"
    for p in deps:
        assert pathlib.Path(p).is_absolute(), f"Expected absolute path, got: {p}"


def test_compile_deps_out_not_modified_without_kwarg():
    """Calling compile_scad without deps_out should not raise and return normally."""
    result = compile_scad(str(FIXTURES / "simple.scad"))
    assert "Width = 10;" in result
