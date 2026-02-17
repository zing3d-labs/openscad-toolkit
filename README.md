# openscad-toolkit

OpenSCAD build tools. Currently includes a **SCAD compiler** that inlines `use`/`include` dependencies into a single self-contained `.scad` file, suitable for distribution without requiring end users to install libraries.

## What the compiler does

- Recursively resolves `use <file.scad>` and `include <file.scad>` directives
- `use` → inlines only module and function definitions (variables are hidden from the customizer)
- `include` → inlines all content
- Deduplicates variables across files
- Preserves library references (e.g. `BOSL2/`, `QuackWorks/`) as external `use`/`include` lines at the top of the output
- Keeps OpenSCAD Customizer compatibility — section comments, parameter labels, and dropdown syntax are preserved

## Installation

### pip (from git, no registry)

```bash
pip install "git+https://github.com/zing3d-labs/openscad-toolkit"
```

### Docker

```bash
docker pull ghcr.io/zing3d-labs/openscad-toolkit:latest
docker run --rm -v "$PWD":/work ghcr.io/zing3d-labs/openscad-toolkit input.scad -o output.scad
```

### GitHub Action

> Coming soon — the composite action is planned for a future release.

## Example

**Source files (before):**

`my_model.scad`
```openscad
use <parts/bracket.scad>
use <BOSL2/std.scad>

/* [Settings] */
Width = 60;  // [20:120]
Material = "PLA";  // [PLA, PETG, ABS]

bracket(Width);
```

`parts/bracket.scad`
```openscad
wall = 2;

module bracket(w) {
  cuboid([w, 20, wall * 3], rounding=1);
}
```

---

**`scad-compiler my_model.scad -l BOSL2/ -o compiled.scad`**

Local file is inlined; BOSL2 is preserved as an external reference:

```openscad
use <BOSL2/std.scad>

/* [Settings] */
Width = 60;  // [20:120]
Material = "PLA";  // [PLA, PETG, ABS]

{
module bracket(w) {
  cuboid([w, 20, 6], rounding=1);
}
}

bracket(Width);
```

**`scad-compiler my_model.scad -l BOSL2/ -l parts/ -o compiled.scad`**

Both dependencies preserved as external references — useful when
distributing alongside your local library folder:

```openscad
use <BOSL2/std.scad>
use <parts/bracket.scad>

/* [Settings] */
Width = 60;  // [20:120]
Material = "PLA";  // [PLA, PETG, ABS]

bracket(Width);
```

## Usage

```bash
# Compile to stdout
scad-compiler my_model.scad

# Write to file
scad-compiler my_model.scad -o my_model_compiled.scad

# Preserve external library references (don't try to inline them)
scad-compiler my_model.scad -l BOSL2/ -l QuackWorks/ -o output.scad
```

### Options

| Flag | Description |
|---|---|
| `-o / --output FILE` | Write output to file (default: stdout) |
| `-l / --library-prefix PREFIX` | Preserve includes matching this prefix as external references. Repeat for multiple. |

## License

[CC BY-NC-SA 4.0](LICENSE)
