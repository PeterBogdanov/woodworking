# Landscape: what else exists, and where this project sits

Web research done 2026-09-22 (generic queries only, no project identifiers). Prices are as
published on the cited pages and change; treat them as order-of-magnitude.

## The niche this project fills

The generator makes G-code for **a handful of specific objects** (round pinwheel boards) from
**a dozen parameters**, and proves the result safe before it leaves the computer. Nothing found
on the market does exactly that. Existing tools split into four groups, each missing something
the author wanted.

| group | examples | what they do well | what they miss for this use case |
|---|---|---|---|
| Full hobby CAM (paid) | Vectric VCarve Desktop/Pro, Carveco Maker/Maker+ | draw anything, pockets/profiles/tabs, tool database, simulation, MASSO post | cost; every new board is drawn by hand; bowl bits are approximated and users still get undercuts; no automated safety verdict |
| Free/limited CAM | Fusion 360 Personal, Carbide Create, Easel Basic, Estlcam, OpenBuilds CAM, Kiri:Moto, FreeCAD CAM, ivaCAM | zero or low cost | rapids removed (Fusion), export caps (Easel), no bowl-bit tool type (Carbide Create), mesh-only input (Kiri:Moto), steep UI (FreeCAD); none is parametric per object |
| Parametric shape → G-code | LinuxCNC simple-gcode-generators, GCode-Builder, GCMC, cnc-apps.com, SteelSolver | type numbers, get G-code, no drawing step | primitives only (rectangle/circle pockets, bolt circles); no real product geometry, no verification |
| Standalone G-code checkers/simulators | CAMotics, NC Viewer, CutViewer, gcode-checker, AryaA94 G-Code linter | visualise, catch missing feed, bounds | separate manual step; CAMotics explicitly does not detect rapids in material; none knows the *design intent* (pocket walls, allowance, coverage) |

The project combines groups 3 and 4 with domain knowledge that only group 1 has (bowl-bit
geometry, tabs, flip). That combination is the differentiator, not any single feature.

## Closest relatives, in detail

### Parametric generators

- **LinuxCNC simple-gcode-generators** (Python, Tk GUIs). Twelve generators: rectangular and
  circular pockets, facing, bolt circles, grids, engraving, counterbores. Same philosophy
  ("no CAD for simple routines"), no verification, low maintenance activity.
  https://github.com/LinuxCNC/simple-gcode-generators
- **GCode-Builder** (Python + Flask, browser UI, MIT). Circle/rectangle pockets, slots,
  surfacing, drilling patterns, material presets. Architecturally the nearest match to
  `serve.py` + `interactive.html`, but primitive shapes only and last touched Dec 2021,
  "under construction". https://github.com/mrRobot62/gcodebuilder
- **GCMC** (G-Code Meta Compiler). A real programming language that emits G-code, SVG, DXF;
  tool offsetting, canned drilling, trochoidal paths, path ordering. Active (1.9.2, May 2024).
  It is what one would use to write this project *in* rather than a competitor; it has no
  toolpath verification. https://www.vagrearg.org/content/gcmc
- **Web shape generators** — cnc-apps.com (rectangle/circle to G-code), SteelSolver
  (pocket/slot/facing/bolt-circle tabs, several dialects), olympia-art, MIDILLI. Copy-paste
  primitives, no stock model, no checks.
  https://cnc-apps.com/en/app/rectangle · https://www.steelsolver.com/p/cnc-g-code-generator.html

### Free CAM and its catches

- **Fusion 360 for Personal Use**: free, full 2.5D CAM and simulation, MASSO/LinuxCNC posts.
  Catches: rapids are output at cutting feed, no automatic tool changes, 10 editable documents.
  Community tools re-insert rapids after the fact (Root_Rapidise).
  https://vagon.io/blog/fusion-360-pricing · https://forums.autodesk.com/t5/fusion-manufacture-forum/fusion-360-personal-use-limitations-for-cam/td-p/13864420 · https://github.com/RootCNC/Root_Rapidise
- **Carbide Create**: free basic version, GRBL post selectable; Pro is ~$120/yr. A flat-bottom
  bit with corner radius (bowl bit) is **not a supported tool type**; users enter it as a square
  or ball end mill. https://carbide3d.com/carbidecreate/buy/ · https://community.carbide3d.com/t/using-a-bowl-bit-in-carbide-create/44788
- **Easel Basic**: one carve/export per week on the free plan; Starter 20/week; Pro unlimited.
  Cloud-only. https://support.easel.com/hc/en-us/articles/52649769958163-Easel-Plans-Pricing
- **Estlcam**: ~$59 perpetual (+$19/yr updates), strong 2.5D, no MASSO-specific post (generic works).
  https://www.rocketronics.de/shop/en/controls/cnc-controller/estlcam-softwarelicense/
- **OpenBuilds CAM**: free browser 2.5D from SVG/DXF, GRBL-oriented. https://software.openbuilds.com/
- **Kiri:Moto**: free browser CAM with rough/pocket/contour and tabs, but input is a mesh
  (STL/OBJ/3MF); flip workflows have had tab bugs. https://grid.space/kiri/ · https://forum.grid.space/t/possible-bug-contour-cutting-through-tabs/3003
- **FreeCAD 1.x CAM workbench**: free, pocket/profile/tags, simulator; a MASSO G3 post was
  merged Jan 2025 (`T5 M6` order). Heavy learning curve for a one-object workflow.
  https://github.com/FreeCAD/FreeCAD/pull/18845
- **ivaCAM** (Rust/Tauri/WASM, GPL-3): DXF/SVG → profile/pocket/drill/V-carve with tabs,
  3-D material-removal simulation, LinuxCNC/GRBL dialects. Young, no releases seen.
  https://github.com/crappy-coder1/ivacam

### Paid CAM the author is avoiding

| product | price (2025 sources) | notes |
|---|---|---|
| Vectric VCarve Desktop | $349 perpetual | 24" × 24" job limit (a 430 mm blank is 16.9", fits); MASSO post; ~80 % of Onefinity users |
| Vectric VCarve Pro | $699 perpetual | unlimited size |
| Carveco Maker | $17.50/mo ≈ $180/yr | subscription only |
| Carveco Maker+ | $50/mo ≈ $540/yr, or $1200 perpetual | the "~$600/year" tier |

https://jamesdeandesigns.com/carveco-maker-vs-vectric-vcarve/ · https://www.vectric.com/purchase/vcarve/ · https://forum.onefinitycnc.com/t/what-cad-cam-software-can-be-used-to-make-gcode-files-for-the-onefinity-cnc/10253

Even with VCarve, Onefinity forum threads show the exact "debugging inconsistencies" pain the
author describes: a bowl bit finishing pass cutting 0.03" wider than the vector after a
stepover change, or widening with each deeper pass because the tool's corner radius is not
modelled the way the user expects. Replies amount to "cut the final pass at full depth in
one go", which is precisely what `op_finish` does by design.
https://forum.onefinitycnc.com/t/bowl-and-tray-bit-not-what-i-m-expecting/34751 ·
https://forum.onefinitycnc.com/t/bowl-bit-creating-undercut-after-step-over-change/30721

### G-code checkers (compare with `check_nc`)

- **CAMotics** (GPL-2, 3-axis material-removal simulator). Explicitly "does not yet detect
  over/under cutting, collisions with the tool shaft or fixtures or rapid moves in the
  material". Good for eyeballing, not for a verdict. https://camotics.org/
- **AryaA94/G-Code** (C++20, MIT): nine lint rules incl. rapid into stock, outside travel,
  missing feed, spindle off while cutting, plunge deeper than tool diameter; machine JSON;
  SVG output. Two commits, early-stage. https://github.com/AryaA94/G-Code
- **Hajjouz/gcode-checker** (Python, MIT): syntax, coordinates, feed, travel range, PNG plots.
  Limits hard-coded in source. https://github.com/Hajjouz/gcode-checker
- **NC Viewer**, **CutViewer**, **MechSimulator**: browser backplotters for visual review.
  https://ncviewer.com/ · https://cutviewer.com/

`check_nc` covers the same rule family (rapid in material, bounds, missing feed, depth, height)
but is tied to the actual stock dimensions and origin of the run, and it runs automatically
on every generated file. What no external checker can do is the project's coverage and
clearance analysis, because that needs the pocket polygons and allowances.

### Where boards come from today

Search for parametric board generators turned up only static template packs (Etsy, Design
Bundles, Coffey Custom Builds: SVG/DXF/CRV files, 28–60 designs per bundle) and Onefinity's
Filefinity file-sharing site. None is parametric; users resize vectors in VCarve.
https://www.etsy.com/market/cutting_board_cnc_files · https://filefinity.com/

## Takeaways for development

1. **Keep the differentiator sharp**: parametric object + built-in acceptance. Adding generic
   CAM features (arbitrary SVG import, V-carving) moves the project into a crowded field where
   Estlcam at $59 already wins.
2. **Bowl-bit correctness is a real, recurring user pain** even in $700 software. The
   full-depth single-pass finish and the explicit `CORNER_F > r_bowl` rule are worth
   documenting prominently for users, not just in code.
3. **Free CAM's rapid-move restriction (Fusion Personal)** and **export caps (Easel)** are the
   concrete reasons a home user would rather run a script. Worth one line in the README.
4. If external verification is ever wanted as a second opinion, CAMotics for visual
   simulation and the AryaA94 linter for a machine-bounds JSON check are the free candidates.
   Neither replaces `report.txt`.
5. **GCMC** is the one tool worth knowing if the geometry ever needs true tool-radius
   offsetting of arbitrary polylines; today `offset_poly` + `_snap_in` does that job in-house
   with no dependency, which matches decision 3 in `status.md`.
