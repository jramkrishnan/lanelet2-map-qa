# Pittsburgh HD Map QA

A portfolio project showing three things end to end: annotating an HD map to a written policy,
catching map defects automatically with rule-based QA checks, and working the result into GIS
tools. The map covers one signalized intersection (Penn Ave and 16th St, Strip District,
Pittsburgh) hand-annotated in JOSM over Esri World Imagery, in the Lanelet2 format used by
Autoware and other AV stacks. HD map QA matters because autonomous vehicles plan and localize
directly against these maps — a missing stop line reference or a mistagged lane boundary becomes
a routing or behavior bug downstream, not just a cosmetic error.

## Setup

Environment: Mac (Apple Silicon) + an Ubuntu 24.04 VM in VMware, tried in the order below.

1. **RoboStack on Mac (native, preferred) — did not work.** `ros-jazzy-lanelet2-python` via
   micromamba/conda-forge segfaults on import (`EXC_BAD_ACCESS` inside `PyFloat_FromDouble`,
   i.e. a boost::python/CPython ABI mismatch), reproduced across three different Python versions
   (3.11, 3.12, 3.14) and two separate env rebuilds. This looks like an upstream packaging issue
   with the osx-arm64 build of `libboost-python` 1.90, not something fixable by pinning versions
   from this end.
2. **Ubuntu VM** — skipped. The VM wasn't running and this session has no SSH access or shared
   folder into it, so there was no way to drive it from here.
3. **Docker, `--platform linux/amd64`, `pip install lanelet2`** — this is what's actually used.
   Works cleanly: the PyPI wheel imports and loads `map/annotations.osm` with no issues.

Run commands:

```bash
docker build -t josm-qa .
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work josm-qa python3 src/load_map.py
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work josm-qa python3 src/run_qa.py
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work josm-qa python3 src/inject_faults.py --trials 30 --seed 42
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work josm-qa python3 src/evaluate.py
```

(Or skip the build and run directly: `docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work python:3.11-slim bash -c "pip install -r requirements.txt && python3 src/load_map.py"`.)

`run_qa.py` runs all the checks in `docs/checks.md` and writes `outputs/issues.geojson` and
`outputs/issues.csv`. The clean map currently produces zero issues.

## Evaluation

`inject_faults.py` makes 30 corrupted copies of the map, one fault per copy (7 fault types that
mirror the checks), and records what was broken in `outputs/ground_truth.csv`. `evaluate.py`
runs every check on every copy and writes `outputs/eval.md`.

| Fault type | Trials | Caught by expected check | Caught by any check |
|---|---|---|---|
| `detach_regulatory_element` | 4 | 4/4 | 4/4 |
| `detach_successor` | 4 | 4/4 | 4/4 |
| `narrow_lanelet` | 4 | 4/4 | 4/4 |
| `remove_speed_limit` | 4 | 4/4 | 4/4 |
| `remove_stop_line_ref` | 5 | 5/5 | 5/5 |
| `shift_endpoint` | 5 | 2/5 | 4/5 |
| `swap_left_right` | 4 | 0/4 | 4/4 |
| **All** | 30 | **23/30 (77%)** | **29/30 (97%)** |

One fault was missed completely: a 1.07 m gap, just past the 1 m search radius of
`connection_gap`. A swap of left and right is always caught, but as `unreachable_lanelet`,
because Lanelet2 reverses the lanelet on load. Fault injection also found a bug in the width
check (diagonal rather than perpendicular measurement), which has been fixed. All 16 issues
outside ground truth are real knock-on effects on neighboring lanelets. Details for every trial
are in `outputs/eval.md`.

## GIS layer

```bash
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work josm-qa python3 src/export_gis.py
bash sql/load_postgis.sh   # optional: PostGIS in Docker, loads the GeoPackage, runs sql/0*.sql
```

`export_gis.py` writes two GeoPackages with the same layers:
`outputs/map_qa.gpkg` (EPSG:4326, for viewing) and `outputs/map_qa_2272.gpkg` (EPSG:2272, PA
South in US survey feet, for measuring lengths and areas).

| Layer | Geometry | What it holds |
|---|---|---|
| `lanelets` | polygon | tags, width (m), length (m), predecessors/successors, regulatory elements |
| `centerlines` | line | one per lanelet, drawn in the travel direction |
| `boundaries` | line | every linestring: curbs, lane lines, virtual bounds, stop line, traffic light |
| `regulatory_elements` | multiline | the light and stop line of each regulatory element, plus attached lanelets |
| `issues` | point | QA issues on the clean map (currently empty) |
| `faulty_issues` | point | QA issues from all 30 faulty copies, with `trial_id` |

The SQL queries in `sql/` cast to `geography` so distances come back in meters:
total lane length, lanelets within 30 m of a traffic light, issues per lanelet across the
faulty runs, and issue density per 100 m of lane.

### QGIS checklist (built by hand)

1. Add a basemap: *XYZ Tiles* → Esri World Imagery (the same imagery the map was annotated on).
2. *Layer → Add Layer → Add Vector Layer* → `outputs/map_qa.gpkg` and select all layers.
3. Set the project CRS to EPSG:2272 (or 3857) so the map isn't stretched.
4. `lanelets`: semi-transparent fill, *Categorized* by `lanelet_id`.
5. `boundaries`: *Categorized* by `type`. Solid line for `curbstone`, dashed for `line_thin`,
   dotted grey for `virtual`, thick red for `stop_line`, a marker for `traffic_light`.
6. `centerlines`: line with an arrow marker at the end, to show travel direction.
7. `faulty_issues`: *Categorized* by `check`. Add a filter such as `"trial_id" = 23` to show one
   run, or leave it unfiltered to see where issues cluster.
8. Label lanelets with `lanelet_id` and `width_m`.
9. *Project → Import/Export → Export Map to Image* → `outputs/figures/qgis_map.png`.

## Limitations

- One intersection, one lane mapped so far.
- Annotated from aerial imagery, not lidar; traffic light position taken from Street View since
  signal heads aren't visible from above.
- QA checks are rule-based, not learned.
- The evaluation injects faults the checks were designed for, into a 3-lanelet map, so recall
  measures whether each check works as intended, not how much of the real-world defect space
  it covers.
