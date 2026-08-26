"""OpenSCAD compiler — inlines use/include dependencies into a single self-contained file."""

import os
import re
import sys

from openscad_parser.ast import (
    Assignment,
    FunctionDeclaration,
    IncludeStatement,
    ModuleDeclaration,
    UseStatement,
    getASTfromString,
)

# Regular expression to find 'use <...>' or 'include <...>' statements.
INCLUDE_RE = re.compile(r"^\s*(use|include)\s*<\s*([^>]+)\s*>.*")
MODULE_START_RE = re.compile(r"^\s*(module)\s+\w+")
FUNCTION_START_RE = re.compile(r"^\s*function\s+\w+")  # matches any function start, incl. multiline signatures
FUNCTION_LITERAL_RE = re.compile(r"^\s*\$?\w+\s*=\s*function\s*\(")  # matches var = function(...)
VARIABLE_NAME_RE = re.compile(r"^\s*(\$?\w+)\s*=")
SECTION_HEADER_RE = re.compile(r"/\*\s*\[[^\]]+\]\s*\*/")  # matches /* [Section Name] */
# openscad_parser emits no AST node at all for a brace-bodied `if`/`for` at top level, so
# those statements have to be recognised from source instead.
CONTROL_START_RE = re.compile(r"^\s*(?:if|for|intersection_for)\s*\(")
ELSE_START_RE = re.compile(r"^\s*else\b")  # continuation of the preceding if statement

# Node types that are NOT module calls / other statements to emit
_SKIP_IN_OTHER_STATEMENTS = frozenset({ModuleDeclaration, FunctionDeclaration, Assignment, UseStatement, IncludeStatement})


def _classify_top_level(lines: list[str]) -> dict[int, type]:
    """Parse source and return {1-indexed line: AST node class} for top-level nodes.

    Function literals (var = function(...)) cannot be parsed by openscad_parser,
    so those lines are blanked before parsing and detected separately via
    FUNCTION_LITERAL_RE where needed.

    Returns an empty dict if parsing fails, which causes callers to fall back
    gracefully (blank lines/comments are still preserved, constructs at unknown
    lines are skipped rather than misclassified).
    """
    # Blank function-literal lines: the parser rejects `var = function(...)` syntax.
    cleaned = "".join("\n" if FUNCTION_LITERAL_RE.match(ln) else ln for ln in lines)
    try:
        result = getASTfromString(cleaned)
    except Exception as exc:
        print(f"  -> WARNING: AST parse failed, structural analysis degraded: {exc}", file=sys.stderr)
        return {}
    if result is None:
        return {}
    nodes = result if isinstance(result, list) else [result]
    return {node.position.line: type(node) for node in nodes}


def _declaration_spans(lines: list[str], classification: dict[int, type]) -> list[tuple[int, int]]:
    """Return 1-indexed inclusive line ranges occupied by top-level module/function declarations.

    Shared by extract_modules_and_functions (which emits these ranges) and
    extract_other_statements (which must not emit them).
    """
    module_starts = {ln for ln, cls in classification.items() if cls is ModuleDeclaration}
    function_starts = {ln for ln, cls in classification.items() if cls is FunctionDeclaration}
    # Function literals (var = function(...)) are blanked before AST parsing so they don't
    # appear in classification — detect them directly from source lines.
    function_literal_starts = {i + 1 for i, ln in enumerate(lines) if FUNCTION_LITERAL_RE.match(ln)}

    spans: list[tuple[int, int]] = []
    inside_module = False
    inside_block_comment = False
    start = 0
    end = 0
    brace_depth = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1
        stripped = line.strip()

        # Block comment tracking — braces inside a comment must not affect the depth count
        if inside_block_comment:
            if inside_module:
                end = line_num
            if "*/" in stripped:
                inside_block_comment = False
            i += 1
            continue

        if stripped.startswith("/*") and "*/" not in stripped:
            inside_block_comment = True
            if inside_module:
                end = line_num
            i += 1
            continue

        # Collecting a module body — it runs until the braces balance
        if inside_module:
            end = line_num
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                inside_module = False
                spans.append((start, end))
            i += 1
            continue

        # AST-confirmed top-level module definition
        if line_num in module_starts:
            inside_module = True
            start = end = line_num
            brace_depth = line.count("{") - line.count("}")

            # Handle multiline module signature (opening brace on a later line)
            if brace_depth == 0 and "{" not in line:
                j = i + 1
                while j < len(lines) and "{" not in lines[j]:
                    end = j + 1
                    j += 1
                if j < len(lines):
                    end = j + 1
                    brace_depth = lines[j].count("{") - lines[j].count("}")
                    i = j

            if brace_depth <= 0:
                inside_module = False
                spans.append((start, end))
            i += 1
            continue

        # AST-confirmed top-level function (terminated by semicolon)
        if line_num in function_starts or line_num in function_literal_starts:
            if not line.split("//")[0].rstrip().endswith(";"):
                i += 1
                while i < len(lines) and not lines[i].split("//")[0].rstrip().endswith(";"):
                    i += 1
            spans.append((line_num, min(i + 1, len(lines))))
            i += 1
            continue

        i += 1  # Skip everything else (variables, calls, use/include, comments)

    if inside_module:  # unbalanced braces — emit what was collected rather than dropping it
        spans.append((start, end))
    return spans


def _declared_lines(lines: list[str], classification: dict[int, type]) -> set[int]:
    """1-indexed line numbers claimed by a top-level declaration or a use/include directive.

    Only used to keep the source-level control-structure fallback in
    extract_other_statements from firing on an `if`/`for` that is really part of a list
    comprehension inside a multi-line assignment.
    """
    declared: set[int] = set()
    for span_start, span_end in _declaration_spans(lines, classification):
        declared.update(range(span_start, span_end + 1))

    for assignment_start in (ln for ln, cls in classification.items() if cls is Assignment):
        line_num = assignment_start
        while line_num <= len(lines):
            declared.add(line_num)
            if lines[line_num - 1].split("//")[0].rstrip().endswith(";"):
                break
            line_num += 1

    declared.update(i + 1 for i, ln in enumerate(lines) if INCLUDE_RE.match(ln))
    return declared


def _statement_ends(stripped: str, brace_depth: int) -> bool:
    """True when a buffered statement is complete at this line."""
    # Tested both with and without any trailing line comment: stripping `//` would break on a
    # string containing one (a url), keeping it would break on a real trailing comment.
    for text in (stripped, stripped.split("//")[0].rstrip()):
        if (brace_depth <= 0 and text.endswith(";")) or (brace_depth == 0 and text.endswith("}")):
            return True
    return False


def _else_follows(lines: list[str], start: int) -> bool:
    """True if the next actual code at/after index `start` opens an `else` clause.

    Blank lines and comments (line and block) in between are skipped, so an `else` that a
    reader sees as continuing the preceding `if` is treated as part of the same statement
    rather than dropped as an unrecognised line.
    """
    inside_block_comment = False
    for line in lines[start:]:
        rest = line
        while True:
            if inside_block_comment:
                if "*/" not in rest:
                    break
                rest = rest.split("*/", 1)[1]
                inside_block_comment = False
            code = rest.lstrip()
            if not code or code.startswith("//"):
                break
            if code.startswith("/*"):
                rest = code[2:]
                inside_block_comment = True
                continue
            return ELSE_START_RE.match(code) is not None
    return False


def extract_top_level_items(lines: list[str], defined_variables: set[str] | None = None) -> tuple[list[str], set[str]]:
    """Extracts top-level variable assignments and other declarations.
    Returns (extracted_lines, variable_names)"""
    if defined_variables is None:
        defined_variables = set()

    # AST tells us exactly which lines are top-level Assignments — no brace-counting needed.
    # Function literals appear as Assignment in source but are excluded here (they belong
    # in extract_modules_and_functions instead).
    classification = _classify_top_level(lines)
    assignment_starts = {
        ln for ln, cls in classification.items() if cls is Assignment and not FUNCTION_LITERAL_RE.match(lines[ln - 1])
    }

    output: list[str] = []
    variable_names: set[str] = set()
    inside_assignment = False
    inside_block_comment = False
    current_var_name: str | None = None
    assignment_lines: list[str] = []

    for i, line in enumerate(lines):
        line_num = i + 1
        stripped = line.strip()

        # Block comment continuation
        if inside_block_comment:
            output.append(line)
            if "*/" in stripped:
                inside_block_comment = False
            continue

        # Multi-line assignment continuation
        if inside_assignment:
            if current_var_name:
                assignment_lines.append(line)
            if line.split("//")[0].rstrip().endswith(";"):
                inside_assignment = False
                if current_var_name and current_var_name not in defined_variables:
                    output.extend(assignment_lines)
                    variable_names.add(current_var_name)
                assignment_lines = []
                current_var_name = None
            continue

        # Blank lines and comment lines: preserve (needed for OpenSCAD Customizer labels,
        # section headers like /* [Settings] */, and parameter descriptions).
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            output.append(line)
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
            continue

        # AST-confirmed top-level variable assignment
        if line_num in assignment_starts:
            var_match = VARIABLE_NAME_RE.match(line)
            if var_match:
                var_name = var_match.group(1)
                line_without_comment = line.split("//")[0]
                if var_name not in defined_variables:
                    if line_without_comment.rstrip().endswith(";"):
                        output.append(line)
                        variable_names.add(var_name)
                    else:
                        inside_assignment = True
                        current_var_name = var_name
                        assignment_lines = [line]
                else:
                    # Already defined — skip, but consume multi-line body
                    if not line_without_comment.rstrip().endswith(";"):
                        inside_assignment = True
                        current_var_name = None
                        assignment_lines = []

        # All other lines (modules, functions, calls, use/include): skip

    return output, variable_names


def extract_other_statements(lines: list[str]) -> list[str]:
    """Extracts statements that are not variables, modules, or functions — like module calls
    and scoping blocks ({ } containing variables and calls hidden from customizer)."""
    classification = _classify_top_level(lines)

    # Everything not in the skip set is a module call or control structure to emit.
    call_starts = {ln for ln, cls in classification.items() if cls not in _SKIP_IN_OTHER_STATEMENTS}

    # A brace-bodied `if`/`for` at top level produces no AST node, so it is invisible to
    # classification — recognise those from source, skipping any line a declaration already
    # claims (a list comprehension starts lines with `if`/`for` too).
    declared = _declared_lines(lines, classification)
    control_starts = {i + 1 for i, ln in enumerate(lines) if CONTROL_START_RE.match(ln) and i + 1 not in declared}

    # Bare { } scoping blocks (OpenSCAD trick to hide vars from Customizer) don't appear
    # as typed AST nodes — detect them directly from source content.
    scope_line_starts = {i + 1 for i, ln in enumerate(lines) if ln.strip() == "{"}

    output: list[str] = []
    inside_block_comment = False
    inside_statement = False
    statement_lines: list[str] = []
    statement_brace_depth = 0
    inside_scope = False
    scope_depth = 0
    scope_buf: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        line_num = i + 1
        stripped = line.strip()

        if inside_block_comment:
            if inside_scope:
                scope_buf.append(line)
            elif inside_statement:
                statement_lines.append(line)
            if "*/" in stripped:
                inside_block_comment = False
            i += 1
            continue

        # Collecting a bare scoping block verbatim
        if inside_scope:
            scope_depth += line.count("{") - line.count("}")
            scope_buf.append(line)
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
            if scope_depth <= 0:
                output.extend(scope_buf)
                scope_buf = []
                inside_scope = False
            i += 1
            continue

        # Collecting a multi-line module call or if/else chain
        if inside_statement:
            statement_lines.append(line)
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
                i += 1
                continue
            statement_brace_depth += line.count("{") - line.count("}")
            # An `else` on the next code line continues this statement — without this the
            # rest of the chain matches nothing and is silently dropped.
            if _statement_ends(stripped, statement_brace_depth) and not _else_follows(lines, i + 1):
                inside_statement = False
                output.extend(statement_lines)
                statement_lines = []
                statement_brace_depth = 0
            i += 1
            continue

        # Bare scoping block
        if line_num in scope_line_starts:
            inside_scope = True
            scope_depth = 1
            scope_buf = [line]
            i += 1
            continue

        # AST-confirmed module call, or a source-detected brace-bodied control structure
        if line_num in call_starts or line_num in control_starts:
            statement_brace_depth = line.count("{") - line.count("}")
            if _statement_ends(stripped, statement_brace_depth) and not _else_follows(lines, i + 1):
                output.append(line)
                statement_brace_depth = 0
            else:
                inside_statement = True
                statement_lines = [line]

        i += 1

    # Flush anything left unterminated at EOF rather than dropping it silently
    if inside_statement:
        output.extend(statement_lines)
    if inside_scope:
        output.extend(scope_buf)

    return output


def extract_modules_and_functions(lines: list[str]) -> list[str]:
    """Extracts only module and function bodies from a list of lines,
    excluding top-level variables and module calls."""
    classification = _classify_top_level(lines)

    output: list[str] = []
    for span_start, span_end in _declaration_spans(lines, classification):
        output.extend(lines[span_start - 1 : span_end])
    return output


def process_scad_file(
    filepath: str,
    processed_files: set[str],
    library_prefixes: set[str],
    unique_library_includes: list[str],
    only_modules_functions: bool = False,
    is_entry_file: bool = False,
    defined_variables: set[str] | None = None,
) -> str:
    filepath = os.path.abspath(filepath)
    if filepath in processed_files:
        return ""
    processed_files.add(filepath)

    try:
        with open(filepath, encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"WARNING: File not found: {filepath}", file=sys.stderr)
        return ""

    print(f"Processing: {filepath}")
    output_content: list[str] = []

    # Only add file markers for non-entry files (they'll be inside braces)
    if not is_entry_file:
        output_content.append(f"// --- Begin Content of {os.path.basename(filepath)} ---\n")

    file_dir = os.path.dirname(filepath)

    if defined_variables is None:
        defined_variables = set()

    # If only inlining module/function definitions (for `use` lines), extract them
    if only_modules_functions:
        # Process lines in segments split at include/use boundaries, emitting each
        # segment's variables before inlining the following include/use in-place.
        # This preserves dependency order: library variables defined by an `include`
        # are available to entry-file variables that appear after it in the source.
        # use'd { } blocks are buffered here and emitted after all variables so
        # that top-level variables appear before module definitions in the output,
        # which is required for the OpenSCAD Customizer to recognise them.
        use_blocks: list[str] = []

        def _inline_include(inc_line: str) -> None:
            match = INCLUDE_RE.match(inc_line)
            if not match:
                return
            included_filename = match.group(2)
            kind = match.group(1)
            is_library_line = any(included_filename.startswith(prefix) for prefix in library_prefixes)

            if is_library_line:
                clean_line = inc_line.strip()
                if clean_line not in unique_library_includes:
                    print(f"  -> Registering library include: {clean_line}")
                    unique_library_includes.append(clean_line)
                return

            included_filepath = os.path.join(file_dir, included_filename)
            if not os.path.exists(included_filepath):
                if kind == "use":
                    print(
                        f"  -> WARNING: '{included_filename}' not found on disk — treating as external reference",
                        file=sys.stderr,
                    )
                    clean_line = inc_line.strip()
                    if clean_line not in unique_library_includes:
                        unique_library_includes.append(clean_line)
                else:
                    print(
                        f"  -> WARNING: '{included_filename}' not found on disk — keeping inline (include order matters)",
                        file=sys.stderr,
                    )
                    output_content.append(inc_line)
                return

            if kind == "include":
                print(f"  -> Inlining all content of: {included_filename}")
                inlined_content = process_scad_file(
                    included_filepath,
                    processed_files,
                    library_prefixes,
                    unique_library_includes,
                    False,
                    False,
                    defined_variables,
                )
                output_content.append(inlined_content)
            elif kind == "use":
                print(f"  -> Inlining only modules/functions from: {included_filename}")
                inlined_content = process_scad_file(
                    included_filepath,
                    processed_files,
                    library_prefixes,
                    unique_library_includes,
                    True,
                    False,
                    set(defined_variables) | _entry_var_names,
                )
                # Wrap use'd content in braces to prevent variables from appearing as
                # customizable.  Buffer the block — it will be emitted after all
                # top-level variables so that the Customizer sees the variables first.
                if inlined_content.strip():
                    use_blocks.append("{\n")
                    use_blocks.append(inlined_content)
                    use_blocks.append("}\n")

        # Pre-scan the entry file's own variable names so that use'd files can
        # suppress any variables that the entry file already defines.
        _entry_var_names: set[str]
        if is_entry_file:
            _non_directive_lines = [ln for ln in lines if not INCLUDE_RE.match(ln)]
            _, _entry_var_names = extract_top_level_items(_non_directive_lines)
        else:
            _entry_var_names = set()

        seg: list[str] = []
        for line in lines:
            if INCLUDE_RE.match(line):
                # Emit variables accumulated in this segment, then inline the include
                seg_items, new_vars = extract_top_level_items(seg, defined_variables)
                if not is_entry_file:
                    seg_items = [SECTION_HEADER_RE.sub("/* [Hidden] */", ln) for ln in seg_items]
                defined_variables.update(new_vars)
                output_content.extend(seg_items)
                seg = []
                _inline_include(line)
            else:
                seg.append(line)

        # Emit variables from the final segment (after the last include)
        seg_items, new_vars = extract_top_level_items(seg, defined_variables)
        if not is_entry_file:
            seg_items = [SECTION_HEADER_RE.sub("/* [Hidden] */", ln) for ln in seg_items]
        defined_variables.update(new_vars)
        output_content.extend(seg_items)
        if seg_items:
            output_content.append("\n")

        # Emit buffered use'd { } blocks after all variables
        output_content.extend(use_blocks)

        # For entry file, also extract other statements like module calls
        if is_entry_file:
            other_statements = extract_other_statements(lines)
            for item in other_statements:
                output_content.append(item)
            if other_statements:
                output_content.append("\n")

        # Then extract modules and functions from current file
        extracted = extract_modules_and_functions(lines)
        # Recursively expand includes/uses found inside those modules/functions
        for line in extracted:
            match = INCLUDE_RE.match(line)
            if match:
                kind = match.group(1)
                included_filename = match.group(2)
                included_filepath = os.path.join(file_dir, included_filename)
                if kind == "include":
                    output_content.append(
                        process_scad_file(
                            included_filepath,
                            processed_files,
                            library_prefixes,
                            unique_library_includes,
                            False,
                            False,
                            defined_variables,
                        )
                    )
                elif kind == "use":
                    inlined_content = process_scad_file(
                        included_filepath,
                        processed_files,
                        library_prefixes,
                        unique_library_includes,
                        True,
                        False,
                        set(defined_variables),
                    )
                    if inlined_content.strip():
                        output_content.append("{\n")
                        output_content.append(inlined_content)
                        output_content.append("}\n")
            else:
                output_content.append(line)

        if not is_entry_file:
            output_content.append(f"// --- End Content of {os.path.basename(filepath)} ---\n\n")
        return "".join(output_content)

    # Full inlining mode (for entry file or includes)
    for line in lines:
        match = INCLUDE_RE.match(line)
        if not match:
            if not is_entry_file:
                line = SECTION_HEADER_RE.sub("/* [Hidden] */", line)
            output_content.append(line)
            continue

        included_filename = match.group(2)
        kind = match.group(1)
        is_library_line = any(included_filename.startswith(prefix) for prefix in library_prefixes)

        if is_library_line:
            clean_line = line.strip()
            if clean_line not in unique_library_includes:
                print(f"  -> Registering library include: {clean_line}")
                unique_library_includes.append(clean_line)
            else:
                print(f"  -> Skipping duplicate library include: {clean_line}")
            continue

        included_filepath = os.path.join(file_dir, included_filename)
        if not os.path.exists(included_filepath):
            if kind == "use":
                print(
                    f"  -> WARNING: '{included_filename}' not found on disk — treating as external reference",
                    file=sys.stderr,
                )
                clean_line = line.strip()
                if clean_line not in unique_library_includes:
                    unique_library_includes.append(clean_line)
            else:
                print(
                    f"  -> WARNING: '{included_filename}' not found on disk — keeping inline (include order matters)",
                    file=sys.stderr,
                )
                output_content.append(line)
            continue

        if kind == "include":
            print(f"  -> Inlining all content of: {included_filename}")
            inlined_content = process_scad_file(
                included_filepath,
                processed_files,
                library_prefixes,
                unique_library_includes,
                False,
                False,
                defined_variables,
            )
            output_content.append(inlined_content)
        elif kind == "use":
            print(f"  -> Inlining only modules/functions from: {included_filename}")
            inlined_content = process_scad_file(
                included_filepath,
                processed_files,
                library_prefixes,
                unique_library_includes,
                True,
                False,
                set(defined_variables),
            )
            if inlined_content.strip():
                output_content.append("{\n")
                output_content.append(inlined_content)
                output_content.append("}\n")

    if not is_entry_file:
        output_content.append(f"// --- End Content of {os.path.basename(filepath)} ---\n\n")
    return "".join(output_content)


def compile_scad(
    input_file: str,
    library_prefixes: list[str] | None = None,
    output: str | None = None,
    *,
    deps_out: set[str] | None = None,
) -> str:
    """Compile an OpenSCAD file by inlining all use/include dependencies.

    Args:
        input_file: Path to the main .scad file to compile.
        library_prefixes: Library prefixes to preserve as external references (e.g. ["BOSL2/", "QuackWorks/"]).
        output: Optional output file path. If provided, writes result to file.

    Returns:
        The compiled SCAD content as a string.
    """
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input file not found: {input_file}")

    prefix_set = set(library_prefixes or [])
    processed_files: set[str] = set()
    unique_library_includes: list[str] = []
    defined_variables: set[str] = set()

    result = process_scad_file(
        input_file,
        processed_files,
        prefix_set,
        unique_library_includes,
        only_modules_functions=True,
        is_entry_file=True,
        defined_variables=defined_variables,
    )

    # Prepend library includes
    output_lines: list[str] = []
    for lib_include in unique_library_includes:
        output_lines.append(lib_include + "\n")
    if unique_library_includes:
        output_lines.append("\n")

    output_lines.append(result)
    final_output = "".join(output_lines)

    if deps_out is not None:
        deps_out.update(processed_files)

    if output:
        os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
        with open(output, "w", encoding="utf-8") as f:
            f.write(final_output)
        print(f"Output written to: {output}")

    return final_output
