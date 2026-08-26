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


def test_etli_skips_nested_module_body_vars():
    """Variables inside a module that also contains a nested module must not leak to top level.

    Regression test for: nested `module` declarations resetting brace tracking in
    extract_top_level_items, causing the outer module's body to be treated as top-level code.
    """
    lines = [
        "module outer(lite=false) {\n",
        "  module inner(w) {\n",
        "    x = w;\n",
        "  }\n",
        "  h = lite ? 1 : 2;\n",  # this must NOT appear at top level
        "  core = 3;\n",
        "}\n",
        "top_var = 42;\n",
    ]
    output, vars_ = extract_top_level_items(lines)
    joined = "".join(output)
    assert "h = lite" not in joined, "nested module body variable leaked to top level"
    assert "core = 3" not in joined, "nested module body variable leaked to top level"
    assert "top_var" in joined
    assert "top_var" in vars_


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


def test_emf_multiline_function():
    """A function whose body spans multiple lines must be fully captured (issue #27)."""
    lines = [
        'function testfunc(data = "testfunc") =\n',
        "  data;\n",
        "\n",
        "module testmodule() {\n",
        '  echo("testmodule");\n',
        "}\n",
    ]
    output = extract_modules_and_functions(lines)
    joined = "".join(output)
    assert "function testfunc" in joined
    assert "data;" in joined
    assert "module testmodule" in joined
    # The module must not be fused into the function body
    func_pos = joined.index("function testfunc")
    data_pos = joined.index("data;")
    module_pos = joined.index("module testmodule")
    assert func_pos < data_pos < module_pos


def test_emf_function_literal_single_line():
    """A function literal (var = function(...) expr;) must be captured."""
    lines = ["my_func = function(x) x * x;\n"]
    output = extract_modules_and_functions(lines)
    assert any("my_func" in line for line in output)


def test_emf_function_literal_multiline():
    """A multi-line function literal must be fully captured (not truncated)."""
    lines = [
        "selector = function(which)\n",
        "  which == 1 ? function(x) x + x\n",
        "             : function(x) x * x;\n",
    ]
    output = extract_modules_and_functions(lines)
    joined = "".join(output)
    assert "selector" in joined
    assert "which == 1" in joined
    assert "x * x;" in joined


def test_emf_function_multiline_signature():
    """A function with its `=` on a continuation line (multiline signature) must be fully captured."""
    lines = [
        "function compute(\n",
        "  param1,\n",
        "  param2\n",
        ") = param1 + param2;\n",
    ]
    output = extract_modules_and_functions(lines)
    joined = "".join(output)
    assert "function compute" in joined
    assert "param1 + param2;" in joined


def test_eos_skips_function_literals():
    """`extract_other_statements` must not emit function literals as statements."""
    lines = ["my_func = function(x) x * x;\n", "foo();\n"]
    output = extract_other_statements(lines)
    assert not any("my_func" in line for line in output)
    assert any("foo();" in line for line in output)


def test_eos_skips_multiline_function_signature():
    """`extract_other_statements` must skip a function with a multiline signature."""
    lines = [
        "function compute(\n",
        "  param1,\n",
        "  param2\n",
        ") = param1 + param2;\n",
        "foo();\n",
    ]
    output = extract_other_statements(lines)
    assert not any("function compute" in line for line in output)
    assert any("foo();" in line for line in output)


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


def test_compile_use_inlines_module_nested_in_bare_block():
    """A module def wrapped in a bare { } block (used to hide a helper
    variable from the Customizer) must still be found and inlined when the
    containing file is `use`'d, not just when it's the entry file."""
    result = compile_scad(str(FIXTURES / "with_use_block_wrapped_module.scad"))
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
    """Without a prefix, missing `use` is treated as external (promoted to top)."""
    result = compile_scad(str(FIXTURES / "with_library.scad"), library_prefixes=[])
    assert "LibSize = 30" in result
    # use <BOSL2/std.scad> should now appear at the top, before any module definitions
    assert "use <BOSL2/std.scad>" in result
    lib_pos = result.index("use <BOSL2/std.scad>")
    lib_size_pos = result.index("LibSize")
    assert lib_pos < lib_size_pos


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


# ---------------------------------------------------------------------------
# compile_scad — missing use/include auto-detection (issue #11)
# ---------------------------------------------------------------------------


def test_compile_missing_use_promoted_to_top():
    """A missing `use` file should be registered as an external reference at the top."""
    result = compile_scad(str(FIXTURES / "with_missing_use.scad"))
    assert "use <nonexistent_library/tool.scad>" in result
    use_pos = result.index("use <nonexistent_library/tool.scad>")
    module_pos = result.index("module missingUseUser")
    assert use_pos < module_pos


def test_compile_missing_use_warning(capsys):
    """A missing `use` file should print a 'not found on disk' warning."""
    compile_scad(str(FIXTURES / "with_missing_use.scad"))
    captured = capsys.readouterr()
    assert "not found on disk" in captured.err


def test_compile_missing_include_stays_inline():
    """A missing `include` file should be kept inline in the output."""
    result = compile_scad(str(FIXTURES / "with_missing_include.scad"))
    assert "include <nonexistent_library/defs.scad>" in result


def test_compile_missing_include_warning(capsys):
    """A missing `include` file should print a 'not found on disk' warning."""
    compile_scad(str(FIXTURES / "with_missing_include.scad"))
    captured = capsys.readouterr()
    assert "not found on disk" in captured.err


def test_compile_entry_var_not_shadowed_by_use():
    """Variables defined in use'd files must be suppressed when the entry file
    defines the same name (avoids OpenSCAD 'overwritten' warnings), but kept
    when only the use'd file defines them (their default is still useful inside
    the { } scope).  Entry-file variables must appear before the { } block."""
    result = compile_scad(str(FIXTURES / "entry_overrides_use_var.scad"))
    # Entry file defines SharedVar = 5 — must appear at top level
    assert "SharedVar = 5;" in result
    # Entry-only variable must also be present
    assert "EntryOnly = 10;" in result
    # use'd file's SharedVar = 99 must NOT appear — entry file already defines it
    assert "SharedVar = 99;" not in result
    # use'd file's LibOnlyVar = 7 must appear — entry file does not define it
    assert "LibOnlyVar = 7;" in result
    # Module from use'd file must still be present
    assert "module libModule" in result
    # Entry file's variables must appear before the use'd { } block
    pos_entry_var = result.index("SharedVar = 5;")
    pos_module = result.index("module libModule")
    assert pos_entry_var < pos_module, "entry-file variable must precede the use'd module block"


def test_compile_vector_with_if_conditions_preserved():
    """A vector literal whose elements use `if` comprehension syntax must be
    preserved verbatim.  Previously, lines like `if (cond) val,` inside a
    multi-line assignment were misidentified as module call starts, corrupting
    the output."""
    result = compile_scad(str(FIXTURES / "vector_if.scad"))
    assert "empty = [" in result
    assert 'if (condition1) "content1",' in result
    assert 'if (condition2) "content2",' in result
    assert "];" in result
    # The never_empty vector must also be intact
    assert "never_empty = [" in result
    assert '!condition1 ? "" : "content1",' in result


def test_compile_special_variables_preserved():
    """OpenSCAD special variables ($fn, $fs, $fa) start with $ and must not be
    silently dropped by the variable-name regex."""
    result = compile_scad(str(FIXTURES / "vector_if.scad"))
    assert "$fn = 100;" in result


# ---------------------------------------------------------------------------
# compile_scad — keyword-as-substring false positives (issue #30)
#
# Variable names that contain OpenSCAD keywords as substrings (e.g.
# test_value_diff contains "if", hull_size contains "hull") were
# misclassified by a simple `"keyword" in line` substring check in
# extract_top_level_items and extract_other_statements.  This caused
# them to be silently dropped from the customizer or emitted in the
# wrong position.
# ---------------------------------------------------------------------------


def test_etli_variable_name_containing_keyword_as_substring():
    """A variable whose name contains a keyword substring (e.g. 'diff' ⊃ 'if')
    must be extracted normally from extract_top_level_items."""
    lines = [
        "test_value = 10;\n",
        "test_value_diff = 20;\n",  # contains "if"
        "hull_size = 5;\n",  # contains "hull"
        "union_count = 3;\n",  # contains "union"
    ]
    output, vars_ = extract_top_level_items(lines)
    assert "test_value" in vars_
    assert "test_value_diff" in vars_
    assert "hull_size" in vars_
    assert "union_count" in vars_


def test_eos_variable_name_containing_keyword_as_substring_skipped():
    """`extract_other_statements` must skip assignments even when the variable
    name contains a keyword as a substring."""
    lines = [
        "test_value_diff = 20;\n",  # contains "if"
        "hull_size = 5;\n",  # contains "hull"
        "foo();\n",
    ]
    output = extract_other_statements(lines)
    assert not any("test_value_diff" in line for line in output)
    assert not any("hull_size" in line for line in output)
    assert any("foo();" in line for line in output)


def test_compile_variable_with_keyword_substring_in_customizer(tmp_path):
    """End-to-end: a variable whose name contains a keyword substring must
    appear at the top level in the compiled output (in the customizer)."""
    src = tmp_path / "model.scad"
    src.write_text("test_value = 10;\ntest_value_diff = 20;\necho(test_value_diff);\n")
    result = compile_scad(str(src))
    # Both must appear before any module calls
    assert "test_value = 10;" in result
    assert "test_value_diff = 20;" in result
    diff_pos = result.index("test_value_diff = 20;")
    echo_pos = result.index("echo(test_value_diff);")
    assert diff_pos < echo_pos


# ---------------------------------------------------------------------------
# compile_scad — section headers in included files (issue #31)
# ---------------------------------------------------------------------------


def test_compile_included_section_headers_become_hidden():
    """Section headers from included files must be rewritten to /* [Hidden] */
    so they don't create empty sections in the MakerWorld/OpenSCAD customizer."""
    result = compile_scad(str(FIXTURES / "include_with_sections.scad"))
    assert "/* [Library Settings] */" not in result
    assert "/* [Library Advanced] */" not in result
    # Both should have been replaced with [Hidden]
    assert result.count("/* [Hidden] */") >= 2


def test_compile_entry_file_section_headers_preserved():
    """Section headers in the entry file itself must not be rewritten — the
    user intentionally wants those sections visible in the customizer."""
    result = compile_scad(str(FIXTURES / "include_with_sections.scad"))
    assert "/* [My Settings] */" in result


def test_compile_existing_hidden_section_not_duplicated():
    """A /* [Hidden] */ section already in an included file must remain as-is
    (not be rewritten to a second [Hidden])."""
    result = compile_scad(str(FIXTURES / "customizer.scad"))
    # customizer.scad is the entry file — its own [Hidden] section is preserved
    assert "/* [Hidden] */" in result


def test_compile_used_section_headers_become_hidden():
    """Section headers from use'd files must be rewritten to /* [Hidden] */
    so they don't create empty sections in the MakerWorld/OpenSCAD customizer.

    Regression test: the only_modules_functions path in process_scad_file was not
    applying SECTION_HEADER_RE substitution to seg_items from extract_top_level_items.
    """
    result = compile_scad(str(FIXTURES / "entry_with_use_sections.scad"))
    # Section headers from used_with_sections.scad must be hidden
    assert "/* [Required Dimensions] */" not in result
    assert "/* [Advanced Options] */" not in result
    # Entry file's own section header must be preserved
    assert "/* [My Settings] */" in result


# ---------------------------------------------------------------------------
# Top-level if / else if / else chains (zing-9nf)
#
# Before fix: only the first branch of a top-level if chain reached the output.
# Continuation lines starting with `else` matched no AST node and no source
# rule, so they were silently dropped — a compiled model whose entry point
# dispatches on a parameter was permanently stuck on the first branch.
#
# A brace-bodied `if`/`for` was worse: openscad_parser emits no node at all for
# those, so the whole statement disappeared.
#
# Fix: continue a buffered statement across an `else` (skipping intervening
# blank lines and comments), and detect brace-bodied control structures from
# source for the lines the AST cannot classify.
# ---------------------------------------------------------------------------


def test_eos_else_if_chain_preserved():
    """Every branch of a top-level if / else if / else chain must be emitted."""
    lines = [
        "if (Sel == 0) a();\n",
        "else if (Sel == 1) b();\n",
        'else echo("none");\n',
    ]
    output = extract_other_statements(lines)
    assert output == lines


def test_eos_else_chain_with_brace_bodies_preserved():
    """The brace-bodied form of the chain must survive too, and stop at its end."""
    lines = [
        "if (P == 0) {\n",
        "  assembly();\n",
        "} else if (P == 1) {\n",
        "  plate1();\n",
        "} else {\n",
        '  echo("none");\n',
        "}\n",
        "footer();\n",
    ]
    output = extract_other_statements(lines)
    assert output == lines  # chain plus the following call, nothing dropped


def test_eos_else_on_its_own_line_preserved():
    """An `else` split onto its own line must still continue the statement."""
    lines = ["if (x)\n", "  a();\n", "else\n", "  b();\n"]
    output = extract_other_statements(lines)
    assert output == lines


def test_eos_else_after_comment_preserved():
    """Comments between a branch and its `else` must not break the chain."""
    lines = [
        "if (x) a();\n",
        "// pick the other one\n",
        "/* still\n",
        "   deciding */\n",
        "else b();\n",
    ]
    output = extract_other_statements(lines)
    assert output == lines


def test_eos_else_inside_comment_does_not_extend_statement():
    """The word `else` inside a comment must not glue the next statement on."""
    lines = ["if (x) a();\n", "/* else fake */\n", "c();\n"]
    output = extract_other_statements(lines)
    joined = "".join(output)
    assert "if (x) a();" in joined
    assert "c();" in joined
    assert "else fake" not in joined  # the comment is not part of either statement


def test_eos_brace_bodied_if_not_dropped():
    """A brace-bodied top-level `if` produces no AST node — it must still be emitted."""
    lines = ["if (x) { a(); }\n", "c();\n"]
    output = extract_other_statements(lines)
    assert output == lines


def test_eos_brace_bodied_for_not_dropped():
    """Same for a brace-bodied top-level `for`."""
    lines = ["for (i = [0:3]) { a(i); }\n", "c();\n"]
    output = extract_other_statements(lines)
    assert output == lines


def test_eos_comprehension_if_not_emitted_as_statement():
    """`if` inside a list comprehension belongs to the assignment, not to statements."""
    lines = [
        "empty = [\n",
        '  if (c1) "a",\n',
        '  if (c2) "b",\n',
        "];\n",
        "if (len(empty) == 0)\n",
        '  echo("e");\n',
    ]
    output = extract_other_statements(lines)
    assert output == lines[4:]  # only the real top-level if, not the comprehension lines


def test_compile_top_level_if_else_chain_preserved(tmp_path):
    """End-to-end: the chain from the bug report must survive compilation intact."""
    src = tmp_path / "elif2.scad"
    src.write_text(
        "Sel = 0;\n"
        "module a() { cube(1); }\n"
        "module b() { cube(2); }\n"
        "if (Sel == 0) a();\n"
        "else if (Sel == 1) b();\n"
        'else echo("none");\n'
    )
    result = compile_scad(str(src))
    assert "if (Sel == 0) a();" in result
    assert "else if (Sel == 1) b();" in result
    assert 'else echo("none");' in result
    # The chain must stay contiguous, or OpenSCAD will reject the orphaned `else`
    first = result.index("if (Sel == 0) a();")
    assert result[first:].startswith('if (Sel == 0) a();\nelse if (Sel == 1) b();\nelse echo("none");')


def test_compile_top_level_if_else_chain_with_use(tmp_path):
    """The chain must survive when the entry file also `use`s a library."""
    (tmp_path / "lib.scad").write_text("module a() { cube(1); }\nmodule b() { cube(2); }\n")
    src = tmp_path / "entry.scad"
    src.write_text('Sel = 0;\nuse <lib.scad>\nif (Sel == 0) a();\nelse if (Sel == 1) b();\nelse echo("none");\n')
    result = compile_scad(str(src))
    assert "else if (Sel == 1) b();" in result
    assert 'else echo("none");' in result
    # Variables still lead so the Customizer picks them up
    assert result.index("Sel = 0;") < result.index("if (Sel == 0) a();")
