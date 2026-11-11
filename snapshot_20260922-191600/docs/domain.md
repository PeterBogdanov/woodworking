# Domain: the product, the machine, the tooling

## What is being made

A **менажница** (snack / serving board): a round wooden disc with several shallow
compartments (**отсеки**, also called **карманы** = pockets) and a raised outer rim
(**бортик**). This design is the **«вертушка»** ("pinwheel"): compartments are separated by
thin curved **стенки** (walls) that spiral outward from a small central **втулка** (hub) to the
rim, all twisted in the same direction. Variants:

| `layout` (Customizer) | preset | shape |
|---|---|---|
| `spiral` | `spiral-3` | N spiral-walled compartments around a solid hub (N=3, sweep 200°) |
| `spiral_center` | `spiral-center-5` | same, plus a round central pocket of radius `hub_r − wall_w` (N=5, sweep 160°) |
| `sectors` | `sectors-4` | straight radial walls (`sweep_deg = 0`), N pie slices |

A second shape, `shapes/tray.scad`, is a rounded-rectangle tray with an `n_x × n_y` grid of
pockets (preset `tray-3x2`); it is the first non-round outline.

The reference piece (photo sent by the author in chat, not in repo) is a round board with
five pinwheel compartments and a central pocket, i.e. `spiral_center`.

Default finished part: Ø 406.4 mm (exactly 16"), 25 mm high, pockets 12 mm deep, rim 25 mm
wide, cut from a **square blank** 430 × 430 × 25 mm. Pocket floors are flat with an
R6.35 fillet where wall meets floor, because the finishing bit (Whiteside 1372 bowl & tray)
has that corner radius. In-plan corners where walls meet rim/hub are filleted `CORNER_F`
(14 mm), which must exceed the finishing bit radius (9.53 mm) or the bit cannot reach them.

## Why a generator

The author wanted to choose a layout and dimensions in a browser and get machine-ready
G-code, with automatic proof that the toolpaths are safe (no rapid moves inside material,
no cut outside the blank, no bit driven into a wall, no unmachined floor). Commercial CAM
was not used; all geometry is analytical Python with no third-party dependencies so it runs
anywhere offline.

## Machine and controller

- **Onefinity Elite 2 Woodworker**, working field 812 × 812 mm (blank side limited to 800).
- **MASSO G3 Touch** controller. G-code dialect: `G21 G17 G90 G94`, `G54`, `M03/M05`, `M30`,
  `G0/G1` only, plain-text comments in parentheses (Cyrillic is fine in comments).
- **Makita RT0701C** trim router, 6.35 mm (1/4") collet. Speed dial 1–6 with a measured
  linear map `rpm ≈ 5000·dial + 2000` (`DIAL_K`, `DIAL_B`, `dial_for()`); the G-code `S` word
  is informational, the operator sets the dial by hand. A 3/8" collet (Makita 763637-1)
  would be needed for a "Jenny" bit; not owned.
- Workholding: the blank is screwed/clamped to a sacrificial board; the profile cut goes
  `PROFILE_EXTRA = 1.2 mm` into it. Five tabs (`TABS`, `TAB_LEN = 23`, `TAB_H = 4`) hold the
  disc on the final pass.

## Bits (`data/tools.json`, ids used by jobs and the page)

| id | roles | bit | Ø mm | flute length `loc` | used for |
|---|---|---|---|---|---|
| `molly_mill_250` | `rough` | IDC/Cadence "Molly Mill" 8675309-250MM, 1/4" spiral drilling endmill | 6.35 | 19.0 (conservative guess, **measure it**) | roughing pockets with 0.6 mm allowance on walls and floor, wider in the floor-fillet zone |
| `whiteside_1372` | `finish` | Whiteside 1372 Bowl & Tray, R6.35 (type `bowl`) | 19.05 | 15.8 | finishing walls + floor in one full-depth Z pass; forms the wall-floor fillet; chosen because its `corner_r` equals the pocket's floor fillet |
| `molly_mill_250_profile` | `profile` | same Molly Mill at contour feeds | 6.35 | 19.0 | outer contour outside the part, top side then flipped bottom side |
| `surfacing_38` | `surface` | generic surfacing bit (not owned) | 38.1 | 12.7 | `00_flatten_top` when the blank is thicker than the part |
| `whiteside_1406` | `groove` | Whiteside 1406 Round Nose R9.53 (type `ball`) | 19.05 | 11.1 | juice groove when a shape declares one |

Physical facts that agents keep getting wrong (stated in README, tasks/C_texts.md, code comments):

- **Neither 1372 nor 1406 can round over the outer edge.** Both have flat/concave bottoms;
  driven along the rim they would cut the rim away. Edge rounding is done by hand router or sanding.
- The sharp "horns" where a compartment meets rim or hub cannot be reached by any bit in the
  set; wood stays there and the wall blends into the rim. The report counts such nodes.
- `loc` (length of cut) values in `data/tools.json` are placeholders until measured with callipers.

## Wood species (`data/materials.json`)

Feeds in `tools.json` are baseline for hard maple (`reference: true`). Each species has
`feed_scale`, `rpm`, `dial`, `notes` (goes into G-code headers and the report) and a `hint`
for the page. Nine ids: `maple, walnut, cherry, birch, oak, ash, hickory, jatoba, soft`.
Harder wood (higher Janka) → lower scale; jatoba also raises rpm to 19000 (dial 4).

## Shop procedure (from `board_v3/README.md`)

1. Square blank, board centred in it. **X0 Y0 = left-near corner of the blank**, **Z0 = top
   of blank**. The centre is printed in the report (X215 Y215 for a 430 blank).
2. *(optional)* `00_flatten_top_OPTIONAL.nc` — skims `BLANK_THICK − THICK`. **Re-zero Z** after.
3. `01_rough_pockets_MollyMill.nc` — roughing, ≤ 3.8 mm per level (4 levels at defaults).
4. `02_finish_pockets_1372_bowl.nc` — finishing, one full-depth pass.
5. `03a_profile_top.nc` — outer contour from the top, not through.
6. **Flip** the blank (any axis: square + centred board means the circle lands in the same
   place), re-zero XY at the corner and Z on the new top. `03b_profile_bottom_FLIP.nc` — the
   rest of the contour, with tabs.
7. Cut tabs, sand, round the edge by hand.

If a profile bit with `loc ≥ THICK + 1.2 + 1.2` is entered, `PROFILE_MODE='auto'` produces
one `03_profile_full.nc` instead of the a/b pair.

Default-parameter machine time estimate: rough ~67 min, finish ~10, profile ~11 (report
adds 35 % to pure feed time).

## Glossary (RU → EN)

| RU | EN / meaning in this project |
|---|---|
| менажница | serving/snack board with compartments |
| вертушка | pinwheel layout (spiral walls) |
| отсек / карман | compartment / pocket (`Pocket`) |
| бортик | outer rim, width `RIM_W` |
| втулка | central hub, radius `HUB_R` |
| стенка | dividing wall, `WALL_W` |
| перемычка | the wall as a bridge between pockets |
| заготовка | blank / stock (`BLANK_SIZE`, `BLANK_THICK`) |
| жертвенник | sacrificial board under the blank |
| торцовка | surfacing / flattening (`op_flatten`, bit `surf`) |
| черновая / чистовая | roughing / finishing |
| контур | outer profile cut |
| табы | hold-down tabs |
| переворот | flip (second setup) |
| припуск | allowance (`WALL_ALLOW`, `FLOOR_ALLOW`) |
| скругление | fillet (in plan: `CORNER_F`; wall-floor: R6.35 from the bit) |
| закрутка | spiral sweep angle (`SPIRAL_SWEEP`) |
| подача / врезание / рампа | feed / plunge feed / ramp feed (mm/min) |
| обороты / регулятор | rpm / router speed dial |
| порода | wood species |
| растр | polar raster (concentric arcs) that clears a pocket floor |
| обход | contour pass along the pocket wall |
| зазор | clearance between bit centre and wall |
| покрытие | floor coverage check |
| дыра в траектории | a reachable floor spot no toolpath covers (hard failure) |
| игла | needle: a degenerate sharp spike on a pocket outline |
| жёлоб | juice groove |
| ноль | machine zero |
| рапид в материале | G0 (rapid) while below Z0 — forbidden |
