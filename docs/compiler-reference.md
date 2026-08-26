# Compiler Behavior Reference

This document describes the behavior of `scad-compiler` in detail. It is intended as an authoritative reference for users who want to understand exactly what the compiler does — and does not do — when inlining `use`/`include` directives.

---

## 1. `use` vs `include` semantics

OpenSCAD itself defines two directives for importing code from other files:

- `use <file.scad>` — makes the file's modules and functions available, but does **not** execute top-level statements or expose variables.
- `include <file.scad>` — pastes the file's entire content as if it appeared inline at that point.

The compiler preserves this distinction:

### `use <file.scad>`

When the compiler encounters `use <file.scad>` (pointing to a local file it can resolve):

1. It extracts only the **module and function definitions** from the referenced file, discarding top-level variable assignments and module calls.
2. The extracted content is wrapped in a bare `{ }` block in the output, which hides any remaining variables from the OpenSCAD Customizer UI.
3. The wrapping `{ }` block is emitted **after** all top-level variables from the entry file, so that Customizer parameters appear before the code block.
4. Variables that are already defined in the entry file are suppressed from the `use`'d block to avoid OpenSCAD "was overwritten" warnings.

Example output for `use <parts/bracket.scad>`:

```openscad
/* [Settings] */
Width = 60;

{
// --- Begin Content of bracket.scad ---
module bracket(w) {
  cube([w, 20, 6]);
}
// --- End Content of bracket.scad ---
}

bracket(Width);
```

### `include <file.scad>`

When the compiler encounters `include <file.scad>` (pointing to a local file it can resolve):

1. It inlines the **entire content** of the referenced file in-place.
2. Section header comments (`/* [Section Name] */`) from the included file are rewritten to `/* [Hidden] */` (see [Customizer compatibility](#3-customizer-compatibility)).
3. Top-level variables from included files participate in deduplication (see [Variable deduplication](#2-variable-deduplication)).

### Dependency order is preserved

When a file contains both directives and variable definitions interleaved, the compiler processes them in source order. Variables defined before a `use`/`include` are emitted before the inlined content; variables defined after it are emitted after. This preserves any ordering dependencies (for example, a variable defined in an `include`'d file that is referenced by a subsequent variable in the entry file).

### Missing files

If the compiler cannot find the referenced file on disk:

- For `use`: the directive is treated as an **external library reference** and preserved at the top of the output (same behavior as a library prefix match).
- For `include`: the directive is kept inline in the output with a warning, because `include` order matters for OpenSCAD.

---

## 2. Variable deduplication

When the same variable name appears in multiple files (common when library files define defaults that the entry file overrides), the compiler emits only the **first** definition it encounters.

The order of precedence is determined by source order in the entry file:

1. Variables in the entry file that appear **before** any `use`/`include` directive.
2. Variables from `include`'d files (inlined in-place at the point of the `include`).
3. Variables in the entry file that appear **after** a `use`/`include` directive.

Concretely: if the entry file defines `Width = 60` and `parts/defaults.scad` also defines `Width = 40`, the compiler will emit `Width = 60` and suppress `Width = 40` from the included file.

For `use`'d files, variables that are also defined in the entry file are suppressed from the `{ }` block to prevent OpenSCAD "was assigned … but was overwritten" warnings.

### Special variables

Special variables (`$fn`, `$fs`, `$fa`, and other names beginning with `$`) are treated as ordinary variables for deduplication purposes — they are recognized by the `VARIABLE_NAME_RE` pattern and included or suppressed using the same first-seen logic.

### Multi-line assignments

The compiler correctly handles assignments that span multiple lines, including:

- Vector literals with embedded conditionals:
  ```openscad
  sizes = [
    if (condition) val_a,
    val_b,
  ];
  ```
- Function literals assigned to variables:
  ```openscad
  my_func = function(x) x * 2;
  ```

The entire multi-line assignment is treated as a unit — it is either included or suppressed as a whole.

---

## 3. Customizer compatibility

The compiler is designed to produce output that works correctly with the OpenSCAD Customizer (as used on platforms such as MakerWorld and Printables).

### Section headers are preserved for the entry file

Comments of the form `/* [Section Name] */` in the entry file are passed through unchanged:

```openscad
/* [Dimensions] */
Width = 60;   // [20:120]
Height = 30;
```

### Section headers from included files are hidden

Section headers from `include`'d files are rewritten to `/* [Hidden] */` so that they do not create empty, confusing sections in the Customizer UI. This behavior was introduced in **v0.9.0**.

Before (in `parts/defaults.scad`):
```openscad
/* [Part Defaults] */
wall = 2;
```

After inlining:
```openscad
/* [Hidden] */
wall = 2;
```

### Parameter labels and dropdown syntax are preserved

Inline comments that follow variable assignments — used by the Customizer for labels and dropdown menus — are left untouched:

```openscad
Material = "PLA";       // [PLA, PETG, ABS]
Wall_Thickness = 2;     // [1:0.5:5]
```

### `use`'d variables are hidden from the Customizer

Because `use`'d file content is wrapped in a `{ }` block, any variables it defines are hidden from the Customizer UI. Only variables at the top level of the compiled output (outside any `{ }` block) appear as Customizer parameters.

### Top-level variables appear before module definitions

The compiler buffers all `use`'d `{ }` blocks and emits them **after** all top-level variable assignments from the entry file. This ordering is required for the OpenSCAD Customizer to recognize parameters: it stops scanning for parameters when it encounters a module definition. This behavior was introduced in **v0.7.0**.

---

## 4. Function and module handling

### Module definitions

Module definitions are recognized by the pattern `module name(...)` and collected in full, including their entire brace-delimited body. Nested module definitions (modules defined inside other modules) are treated as part of the outer module's body, not as separate top-level modules.

Multi-line module signatures (where the opening `{` appears on a line after the `module` keyword) are handled correctly by looking ahead for the first line containing `{`.

### Function definitions

The compiler recognizes three forms of function definitions:

1. **Single-line named functions:**
   ```openscad
   function area(r) = PI * r * r;
   ```

2. **Multi-line named functions** (body spans multiple lines, terminated by `;`):
   ```openscad
   function clamp(v, lo, hi) =
     v < lo ? lo :
     v > hi ? hi : v;
   ```
   Multi-line function body collection was made reliable in **v0.9.0**.

3. **Function literals** (assigned to a variable):
   ```openscad
   my_func = function(x) x * 2;
   ```

All three forms are extracted verbatim and included in the output, regardless of whether the file was `use`'d or `include`'d.

### Module calls (top-level statements)

Top-level module calls from the entry file (statements that invoke modules) are preserved in the output. They are collected by `extract_other_statements` and emitted after the variable block and `use`'d `{ }` blocks.

Top-level module calls from `use`'d files are discarded (only module/function definitions are extracted from `use`'d files, per OpenSCAD's own `use` semantics).

Top-level module calls from `include`'d files are inlined verbatim.

### Top-level control structures

A top-level `if` / `else if` / `else` chain in the entry file is preserved whole, including branches whose body is a `{ }` block and chains whose `else` is separated from the preceding branch by blank lines or comments. Top-level `for` and `intersection_for` are preserved the same way.

This matters for a model whose entry point dispatches on a Customizer parameter (`Render_Plate = 0` for the assembly, `1..N` for a plate) — dropping a branch would compile to a file permanently stuck on the first one.

### Scoping blocks

OpenSCAD allows bare `{ }` blocks at the top level to hide variables from the Customizer. The compiler preserves these blocks verbatim in the output, including all their contents.

---

## 5. Library prefix handling (`-l`)

The `-l` / `--library-prefix` flag tells the compiler to treat any `use`/`include` whose path starts with the given prefix as an **external library reference** rather than a local file to inline.

### How it works

When a `use` or `include` directive matches a library prefix:

1. The directive is **not** inlined — the file is not read or expanded.
2. The directive is collected into a deduplicated list of library includes.
3. All library includes are emitted at the very **top** of the compiled output, before anything else.

This ensures that the compiled file correctly references libraries that are pre-installed on the target platform.

### Deduplication

If the same library `use`/`include` line appears multiple times across the entry file and its dependencies, only one copy is emitted in the output.

### Multiple prefixes

The flag may be repeated to specify multiple prefixes:

```bash
scad-compiler my_model.scad -l BOSL2/ -l QuackWorks/ -o compiled.scad
```

Any `use`/`include` whose path starts with `BOSL2/` or `QuackWorks/` will be preserved as an external reference.

### Choosing when to use `-l`

A library prefix should be used only when the target platform is known to have that library pre-installed. MakerWorld bundles BOSL2, so `-l BOSL2/` is safe for uploads there. If the library is not available on the target platform, omit `-l` to have the compiler inline the library files directly (producing a fully self-contained file).

---

## 6. Ordering guarantees

The compiler produces output in this fixed order:

1. **Library includes** — all `use`/`include` lines for library-prefix matches, deduplicated, in the order they were first encountered during the traversal.
2. **Blank line** (if any library includes were emitted).
3. **Entry-file content** — processed in source order:
   a. Top-level variable assignments from the entry file (and from `include`'d files, interleaved at the point of each `include`).
   b. A blank line (if variables were emitted).
   c. Buffered `use`'d `{ }` blocks (one block per `use`'d file that contributed content), in the order the `use` directives appeared in the source.
   d. Top-level module calls from the entry file (and `include`'d files), in source order.
   e. A blank line (if module calls were emitted).
   f. Module and function definitions from the entry file (in source order).

### Deduplication across files

Each file is processed at most once. If the same file is referenced (directly or transitively) by multiple `use`/`include` directives, only the first encounter is processed; subsequent references are silently skipped.

---

## 7. Watch mode

Watch mode (`--watch`) recompiles the entry file automatically whenever any source `.scad` file in the dependency graph changes.

### Requirements

Watch mode requires the `watchdog` package, which is an optional dependency:

```bash
pip install "git+https://github.com/zing3d-labs/openscad-toolkit[watch]"
```

The Docker image includes `watchdog` by default.

### How it works

1. On startup, the compiler performs an initial compilation and records all files that were read (the transitive dependency set).
2. The compiler sets up filesystem watchers on all directories containing those files, plus the directory containing the entry file.
3. When any `.scad` file in a watched directory is created or modified, the compiler recompiles and updates the watcher set to reflect any new dependencies.
4. The output file is never watched — changes to it do not trigger a recompile.
5. Watch mode runs until interrupted with Ctrl+C.

### Requirements and constraints

- `--output` is required with `--watch`. Watch mode cannot write to stdout.
- Watchers are set up per-directory, not per-file (`recursive=False`). Adding a new source file in a directory that is already watched will trigger a recompile correctly. Adding a new source file in a new subdirectory will not be detected until the next recompile registers the new directory.

### Typical usage

```bash
scad-compiler my_model.scad -l BOSL2/ -o compiled.scad --watch
```

Keep OpenSCAD's preview open on `compiled.scad` — it will reload automatically as you save changes to any source file.

---

## 8. Known limitations / out of scope

### Conditional `use`/`include` is not supported

OpenSCAD does not actually support conditional `use`/`include` at the language level, and neither does the compiler. All `use`/`include` directives are processed unconditionally.

### Dynamic file paths are not supported

The compiler resolves file paths as literal strings. Expressions like `use <concat(prefix, "/file.scad")>` (if such syntax were valid OpenSCAD) would not be resolved.

### Comment stripping inside strings

The compiler uses a simple `line.split("//")[0]` approach to strip trailing comments before making syntactic decisions (e.g., detecting whether a semicolon terminates a statement). If a string literal contains `//`, this can produce incorrect results. This is a known limitation of the line-oriented parsing approach.

### Brace counting for nesting

The compiler counts `{` and `}` characters on each line to track nesting depth. String literals or comments that contain braces can cause miscounting in pathological cases.

### No macro or preprocessor support

OpenSCAD has no preprocessor. The compiler does not interpret or expand any macro-like constructs.

### Variable scoping beyond top-level is not tracked

The compiler only tracks top-level variable definitions for deduplication. Variables defined inside modules, functions, or `{ }` scoping blocks are not tracked and are always emitted verbatim.

### Circular dependencies

If two files `use` or `include` each other (directly or transitively), the compiler will process each file at most once and silently skip the second encounter, which may produce incomplete output. Circular dependencies in OpenSCAD source files should be avoided.

### No type checking or semantic validation

The compiler is a text-level tool. It does not parse OpenSCAD expressions, validate types, or check that referenced modules/functions are actually defined. Errors in the source `.scad` files will only be caught when OpenSCAD itself opens the compiled output.
