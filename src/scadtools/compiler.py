"""OpenSCAD compiler — inlines use/include dependencies into a single self-contained file."""

import os
import re
import sys

# Regular expression to find 'use <...>' or 'include <...>' statements.
INCLUDE_RE = re.compile(r"^\s*(use|include)\s*<\s*([^>]+)\s*>.*")
MODULE_OR_FUNCTION_RE = re.compile(r"^\s*(module)\s+\w+.*\{")
MODULE_START_RE = re.compile(r"^\s*(module)\s+\w+")
FUNCTION_RE = re.compile(r"^\s*function\s+\w+.*=")
VARIABLE_NAME_RE = re.compile(r"^\s*(\w+)\s*=")


def extract_top_level_items(lines: list[str], defined_variables: set[str] | None = None) -> tuple[list[str], set[str]]:
    """Extracts top-level variable assignments, constants, and other declarations.
    Returns (extracted_lines, variable_names)"""
    output: list[str] = []
    variable_names: set[str] = set()
    if defined_variables is None:
        defined_variables = set()
    inside_module = False
    brace_level = 0
    scope_depth = 0  # Track non-module { } scoping blocks
    inside_assignment = False
    inside_block_comment = False
    inside_call = False  # Track multi-line module calls to skip them
    assignment_lines: list[str] = []
    current_var_name: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track multi-line /* */ comments. These can span many lines
        # (e.g. license headers) and all lines must be preserved or skipped
        # as a unit to avoid leaving unterminated /* in the output.
        if inside_block_comment:
            if scope_depth == 0 and not inside_module:
                output.append(line)
            if "*/" in stripped:
                inside_block_comment = False
            i += 1
            continue

        # Preserve top-level comments and blank lines (needed for OpenSCAD customizer
        # labels, section headers like /* [Settings] */, and parameter descriptions)
        if (
            not inside_assignment
            and not inside_module
            and scope_depth == 0
            and (not stripped or stripped.startswith("//") or stripped.startswith("/*"))
        ):
            output.append(line)
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
            i += 1
            continue

        # Skip include/use statements
        if INCLUDE_RE.match(line):
            i += 1
            continue

        # Check if we're entering a module definition
        if MODULE_START_RE.match(line):
            inside_module = True
            brace_level = line.count("{") - line.count("}")

            if brace_level == 0:
                if "{" not in line:
                    # No opening brace on this line yet (multiline signature); look ahead
                    j = i + 1
                    while j < len(lines) and "{" not in lines[j]:
                        j += 1
                    if j < len(lines):  # Found line with {
                        brace_level = lines[j].count("{") - lines[j].count("}")
                        i = j
                else:
                    # Single-line module: opens and closes on the same line
                    inside_module = False

            i += 1
            continue

        # Track braces when inside module
        if inside_module:
            brace_level += line.count("{") - line.count("}")
            if brace_level <= 0:
                inside_module = False
            i += 1
            continue

        # Track non-module scoping braces. OpenSCAD uses bare { } blocks to
        # hide variables from the customizer UI. Variables inside these blocks
        # must stay inside braces in the compiled output to preserve that behavior.
        if not inside_module:
            open_braces = line.count("{")
            close_braces = line.count("}")
            if open_braces or close_braces:
                scope_depth += open_braces - close_braces
                if scope_depth < 0:
                    scope_depth = 0
                # If this line is just a brace, skip it
                if stripped == "{" or stripped == "}":
                    i += 1
                    continue

        # Skip everything inside scoping braces (not top-level)
        if scope_depth > 0:
            i += 1
            continue

        # Skip function definitions (they'll be handled separately)
        if FUNCTION_RE.match(line):
            i += 1
            continue

        # Skip module calls (e.g. `dualSidedSnap(...)`) — these are handled
        # by extract_other_statements, not here. Without this, the argument
        # lines (like `Lite_A=Lite_A,`) would be misidentified as variable
        # assignments because they contain `=`.
        if inside_call:
            if line.split("//")[0].rstrip().endswith(";"):
                inside_call = False
            i += 1
            continue

        # This is a top-level item (variable, constant, etc.)
        if not inside_module:
            # Check if this starts a variable assignment
            # Remove comments from line for keyword checking
            line_without_comment = line.split("//")[0]

            # Detect start of a module call — has '(' but is not a variable assignment
            if "(" in line_without_comment and "=" not in line_without_comment.split("(")[0]:
                if not line_without_comment.rstrip().endswith(";"):
                    inside_call = True
                i += 1
                continue

            if not inside_assignment:
                # Check if this line starts a variable assignment
                if "=" in line and not any(
                    keyword in line_without_comment for keyword in ["module", "function", "linear_extrude", "hull", "union", "if"]
                ):
                    # Extract variable name
                    var_match = VARIABLE_NAME_RE.match(line)
                    if var_match:
                        var_name = var_match.group(1)
                        current_var_name = var_name

                        # Only include if not already defined
                        if var_name not in defined_variables:
                            inside_assignment = True
                            assignment_lines = [line]

                            # Check if assignment is complete on this line.
                            # Must strip trailing comments first — OpenSCAD customizer
                            # dropdown syntax like `Grid_Version = "Lite"; // [Full,Lite]`
                            # would otherwise hide the semicolon and start a false
                            # multi-line assignment.
                            if line_without_comment.rstrip().endswith(";"):
                                inside_assignment = False
                                output.extend(assignment_lines)
                                variable_names.add(var_name)
                                assignment_lines = []
                                current_var_name = None
                        else:
                            # Skip this assignment - already defined
                            # We still need to track if it's multi-line to skip all of it
                            if not line_without_comment.rstrip().endswith(";"):
                                inside_assignment = True
                                current_var_name = None  # Don't collect lines for this
                                assignment_lines = []
            else:
                # We're inside a multi-line assignment
                if current_var_name and current_var_name not in defined_variables:
                    # Continue collecting assignment lines for new variable
                    assignment_lines.append(line)

                # Check if assignment is complete
                if line.split("//")[0].rstrip().endswith(";"):
                    inside_assignment = False
                    if current_var_name and current_var_name not in defined_variables:
                        output.extend(assignment_lines)
                        variable_names.add(current_var_name)
                    assignment_lines = []
                    current_var_name = None

        i += 1

    return output, variable_names


def extract_other_statements(lines: list[str]) -> list[str]:
    """Extracts statements that are not variables, modules, or functions - like module calls
    and scoping blocks ({ } containing variables and calls hidden from customizer)."""
    output: list[str] = []
    inside_module = False
    brace_level = 0
    scope_depth = 0  # Track non-module { } scoping blocks
    scope_lines: list[str] = []  # Collect lines inside scoping blocks
    inside_assignment = False
    inside_block_comment = False
    inside_statement = False
    statement_lines: list[str] = []
    statement_brace_depth = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track multi-line /* */ comments (e.g. license headers).
        # All lines must be consumed as a unit to avoid unterminated /* in output.
        if inside_block_comment:
            if scope_depth > 0:
                scope_lines.append(line)
            if "*/" in stripped:
                inside_block_comment = False
            i += 1
            continue

        # If inside a scoping block (bare { } used to hide vars from customizer),
        # collect all lines verbatim until the block closes, then emit them.
        if scope_depth > 0:
            scope_depth += line.count("{") - line.count("}")
            scope_lines.append(line)
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
            if scope_depth <= 0:
                # Block closed, emit all collected lines
                output.extend(scope_lines)
                scope_lines = []
                scope_depth = 0
            i += 1
            continue

        # If we're collecting a multi-line statement (e.g. module call), keep going
        if inside_statement:
            statement_lines.append(line)
            statement_brace_depth += line.count("{") - line.count("}")
            is_done = (statement_brace_depth <= 0 and stripped.endswith(";")) or (
                statement_brace_depth == 0 and stripped.endswith("}")
            )
            if is_done:
                inside_statement = False
                output.extend(statement_lines)
                statement_lines = []
                statement_brace_depth = 0
            i += 1
            continue

        # Skip empty lines and comments
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            if stripped.startswith("/*") and "*/" not in stripped:
                inside_block_comment = True
            i += 1
            continue

        # Skip include/use statements
        if INCLUDE_RE.match(line):
            i += 1
            continue

        # Check if we're entering a module definition
        if MODULE_START_RE.match(line):
            inside_module = True
            brace_level = line.count("{") - line.count("}")

            if brace_level == 0:
                if "{" not in line:
                    # No opening brace on this line yet (multiline signature); look ahead
                    j = i + 1
                    while j < len(lines) and "{" not in lines[j]:
                        j += 1
                    if j < len(lines):  # Found line with {
                        brace_level = lines[j].count("{") - lines[j].count("}")
                        i = j
                else:
                    # Single-line module: opens and closes on the same line
                    inside_module = False

            i += 1
            continue

        # Track braces when inside module definition
        if inside_module:
            brace_level += line.count("{") - line.count("}")
            if brace_level <= 0:
                inside_module = False
            i += 1
            continue

        # Skip function definitions
        if FUNCTION_RE.match(line):
            i += 1
            continue

        # Detect scoping blocks — OpenSCAD uses bare { } blocks to hide
        # variables from the customizer UI. Collect the entire block and
        # emit it verbatim so the scoping is preserved in compiled output.
        if stripped == "{":
            scope_depth = 1
            scope_lines = [line]
            i += 1
            continue

        # If we are inside a multi-line variable assignment, keep consuming
        # lines until the terminating semicolon. This check must come before
        # the variable-assignment detection block so that continuation lines
        # (which may themselves contain '=') are not re-classified as new
        # variable assignments.
        if inside_assignment:
            if stripped.endswith(";"):
                inside_assignment = False
            i += 1
            continue

        # Skip variable assignments at top level.
        # Only treat as an assignment when '=' appears before any '(' so that
        # module calls containing '==' (e.g. `down(x == y) diff()`) are not
        # incorrectly classified as variable assignments.
        line_without_comment = line.split("//")[0]
        before_paren = line_without_comment.split("(")[0]
        if "=" in before_paren and not any(
            keyword in line_without_comment for keyword in ["module", "function", "linear_extrude", "hull", "union", "if"]
        ):
            # This looks like a variable assignment, skip it
            if not line_without_comment.rstrip().endswith(";"):
                # Multi-line assignment, skip until we find the semicolon
                inside_assignment = True
            i += 1
            continue

        # This is some other statement (like a module call) - preserve it
        if not inside_module:
            if not stripped.endswith(";"):
                inside_statement = True
                statement_lines = [line]
                statement_brace_depth = line.count("{") - line.count("}")
            else:
                output.append(line)

        i += 1

    return output


def extract_modules_and_functions(lines: list[str]) -> list[str]:
    """Extracts only module and function bodies from a list of lines,
    excluding top-level variables and module calls."""
    output: list[str] = []
    inside_module = False
    inside_block_comment = False
    brace_level = 0
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Track multi-line /* */ comments (e.g. license headers).
        # All lines must be consumed as a unit to avoid unterminated /* in output.
        if inside_block_comment:
            if inside_module:
                output.append(line)
            if "*/" in stripped:
                inside_block_comment = False
            i += 1
            continue

        if stripped.startswith("/*") and "*/" not in stripped:
            inside_block_comment = True
            if inside_module:
                output.append(line)
            i += 1
            continue

        # Skip single-line comments when not inside a module
        if not inside_module and (stripped.startswith("//") or (stripped.startswith("/*") and "*/" in stripped)):
            i += 1
            continue

        # Check for function (single line with =)
        if FUNCTION_RE.match(line):
            output.append(line)
            i += 1
            continue

        # Check start of module
        if MODULE_START_RE.match(line):
            if not inside_module:
                # This is a top-level module
                inside_module = True
                output.append(line)
                brace_level = line.count("{") - line.count("}")

                # If no opening brace on this line, look ahead for it
                if brace_level == 0:
                    j = i + 1
                    while j < len(lines) and "{" not in lines[j]:
                        output.append(lines[j])
                        j += 1
                    if j < len(lines):  # Found line with {
                        output.append(lines[j])
                        brace_level = lines[j].count("{") - lines[j].count("}")
                        i = j
                    else:
                        # No opening brace found, treat as single line
                        inside_module = False

                # Only exit module if we have a complete brace pair (net 0) or negative
                if brace_level < 0:
                    inside_module = False
            else:
                # This is a nested module, treat as regular content
                output.append(line)
                brace_level += line.count("{") - line.count("}")
                if brace_level <= 0:
                    inside_module = False
            i += 1
            continue

        if inside_module:
            output.append(line)
            brace_level += line.count("{") - line.count("}")
            # Close when brace level returns to zero or below
            if brace_level <= 0:
                inside_module = False

        i += 1
        # Skip all code not inside a module or function (top-level variables, module calls, etc.)

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
                    defined_variables,
                )
                # Wrap use'd content in braces to prevent variables from appearing as customizable
                if inlined_content.strip():
                    output_content.append("{\n")
                    output_content.append(inlined_content)
                    output_content.append("}\n")

        seg: list[str] = []
        for line in lines:
            if INCLUDE_RE.match(line):
                # Emit variables accumulated in this segment, then inline the include
                seg_items, new_vars = extract_top_level_items(seg, defined_variables)
                defined_variables.update(new_vars)
                output_content.extend(seg_items)
                seg = []
                _inline_include(line)
            else:
                seg.append(line)

        # Emit variables from the final segment (after the last include)
        seg_items, new_vars = extract_top_level_items(seg, defined_variables)
        defined_variables.update(new_vars)
        output_content.extend(seg_items)
        if seg_items:
            output_content.append("\n")

        # For entry file, also extract other statements like module calls
        if is_entry_file:
            other_statements = extract_other_statements(lines)
            for item in other_statements:
                output_content.append(item)

            # Add a separator if we found other statements
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
                        defined_variables,
                    )
                    # Wrap use'd content in braces to prevent variables from appearing as customizable
                    if inlined_content.strip():
                        output_content.append("{\n")
                        output_content.append(inlined_content)
                        output_content.append("}\n")
            else:
                output_content.append(line)

        # Only add end marker for non-entry files (they'll be inside braces)
        if not is_entry_file:
            output_content.append(f"// --- End Content of {os.path.basename(filepath)} ---\n\n")
        return "".join(output_content)

    # Full inlining mode (for entry file or includes)
    for line in lines:
        match = INCLUDE_RE.match(line)
        if not match:
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
                defined_variables,
            )
            # Wrap use'd content in braces to prevent variables from appearing as customizable
            if inlined_content.strip():
                output_content.append("{\n")
                output_content.append(inlined_content)
                output_content.append("}\n")

    # Only add end marker for non-entry files (they'll be inside braces)
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
