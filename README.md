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
```

(Or skip the build and run directly: `docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work python:3.11-slim bash -c "pip install -r requirements.txt && python3 src/load_map.py"`.)

`run_qa.py` runs all the checks in `docs/checks.md` and writes `outputs/issues.geojson` and
`outputs/issues.csv`. The clean map currently produces zero issues.

## Limitations

- One intersection, one lane mapped so far.
- Annotated from aerial imagery, not lidar; traffic light position taken from Street View since
  signal heads aren't visible from above.
- QA checks are rule-based, not learned.
