# Options: build the configurator, or assemble it from stable parts?

> **Decision (2026-09-22): option B chosen.** The design is in `../DESIGN.md`; its §10
> summarises this page. Kept as the evidence and source list behind that decision.

Research date 2026-09-22. Question from the user: instead of a custom UI and a custom
engine, could the tool be **a 3-D design front end that already exists**, exchanging **a
simple, widely used 3-D format**, plus **a backend library** that decides which bit to use
and when, generates G-code, and otherwise **explains why the shape cannot be machined**?
This page evaluates that idea against the custom-build plan that preceded `../DESIGN.md` (option A below).

## 1. Decomposition

```
[design front end] --(exchange: shape + metadata)--> [backend library] --> G-code + verdict
        |                                                   |
   parameters UI                                  bit selection, feasibility,
   3-D preview                                    toolpaths, verification
```

Each box can be bought, borrowed or built. The findings below are per box, then §5 assembles
them into six candidate architectures and §6 scores them.

## 2. Front ends that already exist

| candidate | what you get | fit | cost of adoption |
|---|---|---|---|
| **OpenSCAD desktop + Customizer** | Script-defined parametric shapes; the Customizer panel is generated from `// [min:max]` comments; presets saved as `<model>.json`; CLI exports STL/3MF/OFF/DXF/SVG with `-D`, `-p preset.json -P name`; Manifold backend is fast | Exactly "a configuration UI over specific shapes, no drawing". Bowl-floor fillets via `minkowski`, in-plan fillets via `offset(r=±f)` (replaces the 400-step fillet search). GPL-2 desktop app installed by the user (Homebrew) | zero UI code; shapes rewritten in SCAD; tools/materials UI still needed elsewhere |
| **OpenSCAD in the browser** — `openscad-playground` (official), `web-customizer`, `openscad-customizer-web`, `openscad-web-gui` | Same, running as WASM in a page; live three.js preview; STL export; PWA offline | Embeddable in our own page; GPL-2 distribution obligations (serve source offer) | vendor a WASM bundle (tens of MB); still "experimental" UIs, 3MF export not in all |
| **CadQuery / build123d (Python) + viewers** — `yacv`, `ocp_vscode`, `PartCAD` params, `OCP.wasm` | Exact B-rep, STEP export, Python shapes | Powerful, but the parameter UI is code-first (VS Code / playground); browser build experimental and slow to load | `pip install cadquery` (OpenCascade, ~hundreds of MB); UI still largely ours |
| **FreeCAD** | Spreadsheet-driven parameters, CAM workbench with MASSO post (1.1), Python API, headless `FreeCADCmd` | Everything in one stable, widely used app; a custom workbench could host "board shapes" | heavy app; UI is FreeCAD's, not a simple configurator; scripting CAM is documented but fiddly |
| **Fusion 360 Personal** | Parameters, STEP/STL export, CAM with MASSO post | closed, cloud login; rapids forced to feed; not scriptable offline | not a fit for a library-style backend |
| **Custom form (current plan)** | Schema-generated sliders | perfect fit by construction | all code is ours |

## 3. Exchange formats

| format | carries | for this use |
|---|---|---|
| **STL** | triangles only, no units, no features | universal, trivial to write/read (binary `struct`); the backend must *infer* everything; fine for viewing |
| **3MF** | mesh + units + metadata (zip/XML) | can embed our feature JSON as metadata; OpenSCAD export still experimental |
| **STEP** | exact B-rep: planar faces = floors, cylinders/tori = fillets, edges = outlines | the *right* format for feature recognition; reading it needs OpenCascade (CadQuery/pythonocc) |
| **DXF/SVG per depth** | exact 2-D contours | classic hobby-CAM 2.5-D convention (Estlcam, jscut layer names); OpenSCAD exports `projection(cut=true)` slices |
| **heightmap PNG** | Z per pixel | VCarve/Kiri:Moto import it; loses exact edges |
| **parameters JSON + script** | intent | OpenSCAD's own preset files; smallest and most stable "design file" there is |

Key point: **for 2.5-D parts, a mesh plus a small semantic sidecar (outline, features,
depths, floor fillet radius) is enough.** Full B-rep only pays off if arbitrary CAD input is
a goal, which it is not.

## 4. Backend pieces

### 4.1 CAM engines with an API

| engine | operations | tools | API / packaging | post for MASSO | maturity | license |
|---|---|---|---|---|---|---|
| **FreeCAD CAM** (1.1) | profile, pocket, adaptive, drill, 3-D surface (via OpenCAMLib), tags (tabs), dressups | endmill, ballnose, bullnose, V, chamfer… | Python in `FreeCADCmd`; `Path.Main.Job.Create`, `Path.Op.*`; wrapper **`ocp-freecad-cam`** takes CadQuery/build123d shapes (`Job.pocket()`, `Job.profile()`) | yes (merged 2025) | FreeCAD stable; wrapper "fairly experimental", 67 stars, Pocket3D broken | LGPL / MIT |
| **Kiri:Moto engine** (grid-apps) | rough, pocket, outline, contour, trace, drill, tabs | end mill, ball, taper, drill — **no bull-nose/bowl** | MIT; Node CLI `kiri-run/cli --model --device --process --output`; browser worker; self-host via npm/Docker/Electron | generic G-code via device JSON | very active (5.5k commits, v4.x) | MIT |
| **OpenCAMLib** | drop-cutter, waterline (3-D from mesh) — **no 2-D pocketing/offsetting** | cyl, ball, **bull (torus)**, cone | `pip install opencamlib`, npm, C++ | n/a (paths only) | 2023 release | LGPL-2.1 |
| **PyCAM** | STL/DXF/SVG → parallel/contour paths | few | Python 3 | generic | slow-moving | GPL |
| **Fabex (BlenderCAM)** | full CAM | many | Blender extension only | generic | active | GPL |
| **jscut / OpenBuilds CAM** (Clipper) | 2-D pocket/outline/V | flat, V | browser JS; jscut unmaintained | GRBL-ish | frozen | MIT |
| **shapely / pyclipper** | 2-D offsetting only (building block) | — | pip | — | stable | BSD |

### 4.2 Turn-key "3-D file in, G-code out" products (for comparison)

| product | price | notes |
|---|---|---|
| **MeshCAM** Standard / Pro | $250 / $500 perpetual | STL → automatic toolpath wizard; no MASSO post but Mach3 post works; 15-day trial |
| **DeskProto** Entry / Hobby (Multi-Axis) | €145 / €248 (75 % hobby discount) | STL → toolpaths, wizards; **has a MASSO post**; Free edition = one part, one operation |
| Fusion 360 Personal | free | rapids at feed, no tool changes |
| Vectric VCarve Desktop | $349 | see `landscape.md` |

None of them selects bits automatically from the geometry or verifies against design intent;
they are manual CAM with good defaults.

### 4.3 Automatic bit selection and "why impossible"

No library does this. Academic and MVP projects recognise machining features from STEP
with rule-based adjacency graphs (e.g. a pythonocc MVP recognising pockets, holes, slots,
fillets) or ML (UV-Net); none is packaged for use. **This part is ours in every
architecture.** Its difficulty depends entirely on the input:

- From a **semantic 2.5-D design** (outline + pocket polygons + depths + floor fillet
  radius): straightforward rules. Tool fits if `offset(pocket, −r_tool)` is non-empty;
  inner corner radius vs tool radius decides leftover; `depth ≤ loc`; floor fillet radius
  must equal a bowl tool's corner radius in the library (or be zero); blank must fit the
  machine; wall thickness must exceed a minimum. Every failed rule yields a sentence
  ("pocket 3 has a 4 mm channel; smallest flat tool in the library is 6.35 mm").
- From a **bare mesh**: first recover the semantic design — heightmap from the mesh
  (z-buffer of triangles), cluster planar levels, extract contours per level (marching
  squares), fit floor fillet radius from the slope band at pocket edges. Feasible in the
  standard library for parts that really are 2.5-D; fragile for anything else; edges become
  polylines at grid resolution (0.25–0.5 mm), losing exact arcs.
- From **STEP**: floors are planar faces with +Z normals, their wires are the outlines,
  cylindrical/toroidal blend faces give fillet radii. Exact and robust, but needs
  OpenCascade in the backend.

### 4.4 Viewers

| viewer | formats | packaging | notes |
|---|---|---|---|
| **three.js** (+OrbitControls) | any (we build buffers) | 2 vendored files, MIT | current plan; we own the mesh pipeline |
| **Online3DViewer** | STL, 3MF, OBJ, STEP (via occt-import-js WASM), glTF… | one JS bundle, MIT; `embed.html` pattern | "one library that shows the file" — closest to the user's phrase |
| `<model-viewer>` | glTF only | one script | would need STL→glTF conversion |

## 5. Candidate architectures

### A — Custom build (the plan before this evaluation)
Custom schema-driven form; Python shapes → `Design`; custom 2.5-D engine; heightmap
verification; three.js. All stdlib except the viewer.

### B — OpenSCAD front, our backend, semantic sidecar
Shapes are `.scad` files with Customizer annotations. The user designs in OpenSCAD
(desktop first; WASM page later if wanted). Each shape script **also `echo()`s a JSON
description of its features** (outline, pockets, depths, fillet radii) — OpenSCAD's CLI
prints echoes to stderr, so one `openscad -o model.stl -p design.json -P preset shape.scad`
run yields both the 3-D model and the semantic design. Our backend (the library) consumes
the JSON, selects bits, verifies, writes G-code; the STL feeds the viewer and the heightmap
check. Design persistence = OpenSCAD preset JSON. Tools/materials still need a small UI
(a static page over the library JSON) or plain file editing.

### C — Mesh-only generic backend ("STL in, G-code out")
Any CAD exports STL; the backend infers the 2.5-D design from the mesh (4.3, second
bullet), then does bit selection, verification, G-code, or explains failure. Front end is
whatever the user likes. Most general, hardest core, least exact.

### D — Python B-rep stack: build123d + STEP + FreeCAD CAM
Shapes in build123d (Python), exact STEP; features read from B-rep; toolpaths from FreeCAD
CAM through `ocp-freecad-cam` (pocket/profile/tabs/dressups, MASSO post). Our code: shapes,
bit selection, verification wrapper. Everything exists; the wrapper is experimental and the
dependency footprint is FreeCAD + CadQuery (gigabyte class, conda/AppImage Python).

### E — Kiri:Moto as the CAM engine
STL + our generated device/process JSON → Kiri:Moto CLI (Node) → G-code; our library does
bit selection and verification around it. MIT, active, tabs and pockets exist, but **no
bull-nose tool**, so the bowl-bit finishing pass (the one thing the current engine gets
right that $700 software gets wrong) cannot be expressed. Verification still ours.

### F — No software project: OpenSCAD/any CAD + MeshCAM or DeskProto
€145–$250, manual CAM each time, MASSO supported (DeskProto natively). Zero development,
zero automation, no verification, no bit selection. The baseline to beat.

## 6. Scoring

Scale 1 (poor) – 5 (good). "Simplicity" = single process, offline, few and small dependencies.

| criterion | A custom | B OpenSCAD+ours | C mesh-only | D B-rep+FreeCAD | E Kiri:Moto | F buy |
|---|---|---|---|---|---|---|
| Fits "configurator over specific shapes" | 5 | 5 | 3 | 4 | 3 | 2 |
| Reuses stable front end | 1 | 5 | 5 | 3 | 3 | 5 |
| Bowl-bit fidelity (floor fillet, full-depth finish) | 5 | 5 | 3 | 4 | 1 | 3 |
| Automatic bit selection + explained errors | 5 | 5 | 3 | 4 | 4 | 1 |
| Verification (gouge/leftover, lint) | 5 | 5 | 4 | 3 | 3 | 1 |
| 3-D preview quality | 4 | 5 | 4 | 4 | 4 | 4 |
| Simplicity of packaging | 4 | 4 (needs OpenSCAD installed) | 5 | 1 | 2 (Node) | 5 |
| Backend usable as a library | 5 | 5 | 5 | 3 | 3 | 0 |
| Development effort to first useful result | 3 | 4 | 2 | 3 | 3 | 5 |
| Licensing friction | 5 | 4 (GPL app, used not linked) | 5 | 4 | 5 | 5 |
| Exactness of geometry (arcs, fillets) | 5 | 5 | 2 | 5 | 4 | 4 |
| **Total** | **47** | **52** | **41** | **38** | **35** | **36** |

## 7. Feasibility verdict

**Yes, the "assemble from stable parts" approach is feasible, and the strongest form of it is
B: OpenSCAD as the configurator, a semantic sidecar as the exchange, our code as the backend
library.** Reasons:

1. OpenSCAD's Customizer *is* the requested UI: parameters from annotations, presets on
   disk, live 3-D, STL/3MF/DXF export, used by a very large community, stable for years.
   It removes the entire "schema-driven form + editor" work of the custom-build plan and
   most of its 3-D viewer work.
2. Geometry gets simpler, not harder: 2-D `offset(r=±f)` gives in-plan fillets exactly,
   `minkowski` with a sphere gives the bowl-bit floor, `linear_extrude` gives pockets; the
   Manifold backend renders these in well under a second. The 400-step fillet search and its
   performance problem disappear.
3. The hard, novel part — deciding bits and proving safety — stays in Python, unchanged in
   spirit from today: raster, clearance-safe contour, tabs, flip, heightmap comparison, lint.
   It becomes a library with two entry points: `from_design(json)` and `from_mesh(stl)`
   (the latter reusing the heightmap code to recover a design, with explicit errors when the
   mesh is not 2.5-D or a feature has no fitting tool).
4. "Stable outcome" improves: the design file is a tiny preset JSON, the shape is a text
   script under version control, and every run can store both plus the STL.

What B costs: OpenSCAD must be installed (or its WASM vendored), which relaxes "standard
library only" to "standard library plus one external tool invoked by subprocess"; each
shape is written in SCAD, and its feature echo must be kept consistent with its geometry
(a mismatch is caught by the heightmap check, which compares the STL with the toolpaths);
tools and materials need their own small UI or file editing. The current UI's material
and bit pickers would move into the Customizer as dropdown parameters populated from the
library at script-generation time, or stay in a separate page.

Option C (mesh-only) is worth keeping as the **second entry point of the same library**,
not as the architecture: it makes the backend useful for shapes drawn elsewhere, at the cost
of exactness, and its feature-recovery code is the same heightmap machinery B needs anyway.

Options D and E trade our small engine for large ones that either lack the bowl bit (E) or
bring a gigabyte of dependencies and an experimental glue layer (D). F is the fallback if
development stops.

## 8. What changed in the plan once B was chosen (now in `../DESIGN.md`)

- Phase 2 shrinks to: library JSON + tiny tools/materials page; the design editor is
  OpenSCAD. `shapes/*.py` become `shapes/*.scad` plus a Python loader that runs OpenSCAD
  and parses the echo. Preset JSON replaces `designs/*.json` (same idea, OpenSCAD's format).
- Phase 3 keeps the heightmap verification; the machined-vs-design comparison uses the STL
  from OpenSCAD as the design surface (no second implementation of pocket floors). The
  viewer can be Online3DViewer loading the STL, or three.js as planned.
- New phase 1b: `openscad` invocation, echo protocol, mesh→heightmap loader, the
  `from_mesh` recovery path with error messages.
- Package layers: `shapes` becomes "SCAD scripts + echo contract"; `design`
  gains `from_mesh`; the rest stands.

## 9. Recommended next step: a two-day spike before deciding

1. Rewrite the pinwheel (`spiral`, `spiral_center`, `sectors`) as one `.scad` with
   Customizer annotations and an `echo(design=…)` of outline/pockets/depths/fillets.
2. Run `openscad` from Python, parse the echo into the existing engine's inputs, generate
   G-code, and diff against today's output for the three presets.
3. Load the STL into the heightmap prototype and compare with the toolpaths.
4. Measure: OpenSCAD render time per parameter change, echo parse robustness, how the
   Customizer feels for the intended user.

If the diff is clean and the Customizer is acceptable, B stands as designed. If not, the
custom-build option A is the fallback, and the spike's echo contract still serves as the
`Design` JSON schema.

## Sources

- OpenSCAD web ports: https://github.com/openscad/openscad-playground · https://github.com/fsantini/web-customizer · https://github.com/TheFehr/openscad-customizer-web · https://github.com/seasick/openscad-web-gui · https://www.npmjs.com/package/openscad-wasm
- OpenSCAD 3MF export status: https://en.wikibooks.org/wiki/OpenSCAD_User_Manual/Export · https://hackaday.com/2025/10/14/openscad-in-living-color/
- Kiri:Moto API/CLI, tools, repo: https://docs.grid.space/kiri-moto/apis/ · https://docs.grid.space/kiri-moto/CAM/tools/ · https://github.com/GridSpace/grid-apps
- OpenCAMLib: https://github.com/aewallin/opencamlib/blob/master/README.rst · https://pypi.org/project/opencamlib/
- FreeCAD CAM scripting and MASSO post: https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/CAM_scripting.md · https://github.com/spanner888/CamScripts · https://github.com/FreeCAD/FreeCAD/pull/18845
- ocp-freecad-cam: https://github.com/voneiden/ocp-freecad-cam · https://ocp-freecad-cam.readthedocs.io/en/latest/
- CadQuery/build123d viewers and WASM: https://build123d.readthedocs.io/en/latest/external.html · https://github.com/yeicor-3d/yet-another-cad-viewer · https://github.com/CadQuery/cadquery/discussions/1876
- Feature recognition MVPs: https://github.com/Steven-Tran04/feature-recognition · https://github.com/sguerin13/cad-feature-detection
- Formats: https://www.rapid-protos.com/cad-file-format/ · https://www.3dpeople.uk/3dpeopleuk-blog/step-stl-and-3mf-explained/
- Viewers: https://github.com/kovacsv/Online3DViewer · https://www.3dviewer.net/embed.html
- MeshCAM: https://www.grzsoftware.com/ · https://forums.masso.com.au/threads/anyone-using-meshcam-is-there-a-post.2454/
- DeskProto: https://www.deskproto.com/order/prices.php · https://www.deskproto.com/products/free-ed.php · https://www.deskproto.com/support-tips-tricks/dp-tips-onefinity.php
- PyCAM, Fabex: https://pycam.sourceforge.net/ · https://github.com/vilemduha/blendercam
- jscut: https://github.com/tbfleming/jscut
