# QA checks

Each check in `src/checks.py` returns a list of issues: `{check, severity, primitive_type,
primitive_id, message, lon, lat}`. Thresholds live in `checks.DEFAULT_CONFIG`.

The routing graph used by several checks is built with Lanelet2's **default German vehicle
traffic rules** (`lanelet2.traffic_rules.Locations.Germany`). That's a library default, not a
Pittsburgh-specific choice — Lanelet2 ships rule sets for a handful of countries, and Germany's
is the most complete/general-purpose one for a basic "can a car legally drive through this
lanelet" question. It's not expected to matter for these checks, which only use the routing
graph for connectivity (predecessor/successor), not for right-of-way or speed-limit semantics.

## unreachable_lanelet (error)

A road lanelet with neither a predecessor nor a successor in the routing graph — completely
isolated. A lanelet at the edge of the mapped area is expected to be missing one side (that's
just where the map stops); this only flags one missing **both**.

**Why it matters:** a planner can route *through* a lane but nothing can route *onto* or *off*
of an isolated one. In practice it means a piece of road geometry that the AV stack will never
actually drive.

## connection_gap (error / warning)

Two related problems:
- **error** — two lanelets the routing graph treats as connected, but whose bound endpoints
  don't actually coincide (gap > 0.1 m).
- **warning** — the end of one lanelet is within 1 m of the start of another, they don't share
  nodes, and the routing graph doesn't link them.

Lanelet2's own routing graph turned out to have almost zero tolerance for this in testing — even
a 5 cm one-sided gap was enough for it to stop treating two lanelets as connected at all. So in
practice almost everything this check catches comes through the second (warning) branch; the
first (error) branch exists for completeness per spec but is narrow by nature of how Lanelet2
itself behaves.

**Why it matters:** this is the "duplicate node instead of shared node" mistake — easy to make
by eye in JOSM (the gap can be invisible at normal zoom) and exactly the kind of thing that
breaks routing silently rather than throwing an error.

## traffic_light_missing_stop_line (error)

A `traffic_light` regulatory element with no `ref_line` (stop line).

**Why it matters:** this is required by the regulatory element itself — Lanelet2 lets the field
be empty, but AV stacks that use the stop line to decide where to stop at a red light will have
nowhere to stop.

## lanelet_missing_regulatory_element (error)

A road lanelet whose end lies within 2 m of a stop line, but which has no regulatory element
referencing that stop line.

**Why it matters:** catches the opposite mistake from the one above — a stop line exists and is
geometrically in the right place, but nothing on the lanelet actually points to it, so the AV
stack has no reason to treat it as controlling that lane.

## crosswalk_untagged (warning)

A crosswalk lanelet that no regulatory element refers to. Skips gracefully (returns no issues,
no error) when the map has no crosswalks yet — true for this map today.

**Why it matters:** an unreferenced crosswalk is invisible to planning even though it's drawn on
the map — pedestrians could be crossing there and the AV stack would never know to look.

## lane_width_outlier (warning)

A road lanelet whose average width (sampled at 5 points along each bound's own length, since
left and right bounds don't need the same number of vertices) falls outside 2.5–4.5 m.

**Why it matters:** a width outside this range is usually a digitizing mistake — a bound drawn
against the wrong curb, or a lane pinched by a misplaced node — rather than a real road. It's a
warning, not an error, because an unusually wide or narrow lane (e.g. a turn lane) can be
legitimate.

## missing_speed_limit (error)

A road lanelet with no `speed_limit` tag.

**Why it matters:** several AV behaviors (speed planning, time-to-stop calculations) need a
speed limit per lanelet; without the tag the stack has to fall back to a default that may not
match the real road.

## left_right_swapped (error)

Two distinct symptoms, both filed under this one check name per the original spec:

1. **Geometric swap:** after Lanelet2's own bound-direction auto-alignment on load, the bound
   tagged `left` is not geometrically on the left of the lanelet's travel direction.
2. **Unexpected member role:** the raw lanelet relation has a member role other than
   `left`/`right`/`centerline`/`regulatory_element`. Lanelet2 silently ignores roles it doesn't
   recognize when building `leftBound`/`rightBound`, so this has to be caught by reading the
   source OSM XML directly rather than the loaded map.

**A real finding from testing this check:** simply swapping which way is tagged `left` vs.
`right` on a lanelet that already has a routing neighbor does **not** reliably trigger symptom
1. Lanelet2's auto-alignment, when loading, reversed both bounds' point order to keep them
internally consistent with each other — which flipped the lanelet's whole apparent travel
direction instead of leaving a geometric mismatch for the cross-product check to catch. The
flipped direction then broke the lanelet's connection to its neighbor, so the fault surfaced as
`unreachable_lanelet`, not `left_right_swapped`. Both checks are doing their job correctly here;
it's just that this particular fault's symptom depends on whether the lanelet has a routing
neighbor at all. This is called out again in `outputs/eval.md` once Phase C's fault injection
runs this scenario for real.

**Why it matters:** if left/right are swapped, anything that reasons about lane position (lane
keeping, oncoming-traffic detection, where the curb is) gets a mirrored, wrong answer.

---

## Baseline: the official `lanelet2_validation` tool

RoboStack's `ros-jazzy-lanelet2-python` segfaults on this Mac (see `README.md`), and the
validator CLI isn't in the PyPI `lanelet2` wheel used for the rest of this project. It **does**
install cleanly via `apt` on plain `ubuntu:24.04` from the ROS 2 package repo (Jazzy targets
Ubuntu 24.04 natively), via Docker on this Mac — see `Dockerfile.validator`.

```bash
docker build -t lanelet2-validator -f Dockerfile.validator .
docker run --rm --platform linux/amd64 -v "$PWD":/work -w /work lanelet2-validator bash -c \
  "source /opt/ros/jazzy/setup.bash && \
   /opt/ros/jazzy/lib/x86_64-linux-gnu/lanelet2_validation/lanelet2_validate \
     --map_file map/annotations.osm --lat 40.4489 --lon -79.9875"
```

With no `-f` filter, it runs 8 default checks: `mapping.bool_tags`, `mapping.curvature_too_big`,
`mapping.duplicated_points`, `mapping.mandatory_tags`, `mapping.points_too_close`,
`mapping.unknown_tag_value`, `mapping.unknown_tags`, `routing.graph_is_valid`.

**Result on the clean map:** 0 issues — matches `run_qa.py`.

**Result on every one of this project's fault scenarios** (missing stop line reference, missing
regulatory element, a connection gap, a narrow lane, a missing speed limit, left/right roles
swapped): also 0 issues from `lanelet2_validate`. To confirm the tool wasn't just silently
failing, it was tested against an unrelated, deliberately bad tag value (`subtype=
not_a_real_subtype`) and correctly reported 3 warnings — so it works, it simply isn't looking
for any of these problems.

**What it catches that this project's checks don't:** generic cartographic sanity — duplicate or
too-close points, unknown tag keys/values, boolean tags with non-boolean values, pathologically
tight curvature, and internal routing-graph validity (cycles, malformed graph structure).

**What this project's checks catch that it doesn't:** every project-specific policy rule above
— missing speed limits, missing/mismatched regulatory element references, lane width bounds,
left/right role consistency, and small connection gaps. `lanelet2_validation` is a generic
linter; it has no notion of *this* project's policy that a lanelet near a stop line must
reference it, or that a lane should be 2.5–4.5 m wide. That's expected and is exactly why this
project has its own checks instead of relying on the baseline tool alone.
