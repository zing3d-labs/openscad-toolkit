# openscad-toolkit

OpenSCAD build tools. Currently includes a **SCAD compiler** that inlines `use`/`include` dependencies into a single self-contained `.scad` file.

The compiler lets you structure your OpenSCAD projects across multiple files for modularity and reuse, then bundle everything into one file for publishing — for example to [MakerWorld](https://makerworld.com) or [Printables](https://www.printables.com), which require a single self-contained `.scad` file for the Customizer to work.

## What the compiler does

- Recursively resolves `use <file.scad>` and `include <file.scad>` directives
- `use` → inlines only module and function definitions (variables are hidden from the customizer)
- `include` → inlines all content
- Deduplicates variables across files
- Preserves library references (e.g. `BOSL2/`, `QuackWorks/`) as external `use`/`include` lines at the top of the output
- Keeps OpenSCAD Customizer compatibility — section comments, parameter labels, and dropdown syntax are preserved

## Installation

### uvx (no install required)

[Install uv](https://docs.astral.sh/uv/getting-started/installation/), then run directly without installing anything:

```bash
uvx --from "git+https://github.com/zing3d-labs/openscad-toolkit" scad-compiler my_model.scad
```

To avoid typing the full command every time, add an alias to your shell profile:

```bash
alias scad-compiler='uvx --from "git+https://github.com/zing3d-labs/openscad-toolkit" scad-compiler'
```

### Docker

```bash
docker run --rm -v "$PWD":/work ghcr.io/zing3d-labs/openscad-toolkit:latest input.scad -o output.scad
```

### pip (alternative)

```bash
pip install "git+https://github.com/zing3d-labs/openscad-toolkit"
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

**uvx:**
```bash
uvx --from "git+https://github.com/zing3d-labs/openscad-toolkit" scad-compiler my_model.scad -o compiled.scad
uvx --from "git+https://github.com/zing3d-labs/openscad-toolkit" scad-compiler my_model.scad -l BOSL2/ -l parts/ -o compiled.scad
```

**Docker:**
```bash
docker run --rm -v "$PWD":/work ghcr.io/zing3d-labs/openscad-toolkit:latest my_model.scad -o compiled.scad
docker run --rm -v "$PWD":/work ghcr.io/zing3d-labs/openscad-toolkit:latest my_model.scad -l BOSL2/ -l parts/ -o compiled.scad
```

**With the alias (or after `pip install`):**
```bash
scad-compiler my_model.scad -o compiled.scad
scad-compiler my_model.scad -l BOSL2/ -l parts/ -o compiled.scad
```

### Options

| Flag | Description |
|---|---|
| `-o / --output FILE` | Write output to file (default: stdout) |
| `-l / --library-prefix PREFIX` | Preserve includes matching this prefix as external references. Repeat for multiple. |

> **Note on `-l`:** preserving a library reference only works if the target platform has that library installed. Check what your publishing target supports before using this flag — for example, MakerWorld bundles BOSL2 so `-l BOSL2/` is safe there, but other libraries may need to be inlined. When in doubt, omit `-l` to produce a fully self-contained file.

## License

[CC BY-NC-SA 4.0](LICENSE)
