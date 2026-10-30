## Why each miss happened

These notes are hand-written and appended to the generated tables by `src/evaluate.py`.
They describe the run with `--trials 30 --seed 42`.

**`shift_endpoint`: 2/5 by the expected check, 4/5 by any check, 1 complete miss (trial 23).**
The fault moves one end node 0.5 to 2 m. `connection_gap` only searches for near-misses within
1.0 m (`connection_near_miss_m`), the threshold set in the original spec. Trials 2 and 9 (0.87 and
0.83 m) were caught. Trials 16 and 30 (1.64 and 1.33 m) shifted the approach lanelet; it then had
neither a predecessor nor a successor, so `unreachable_lanelet` caught it instead. Trial 23 (1.07 m)
shifted the intersection lanelet. It still had a predecessor, so it was not unreachable, and the gap
was just over the 1 m search radius, so nothing flagged it. Only its now-orphaned successor was
flagged. This is a real blind spot: a lane break between 1 and 2 m on a lanelet that still has a
predecessor goes unreported. The threshold was **not** raised to make this trial pass. Doing so
would be tuning the check to the test. A wider radius also has a cost in a dense map, because
adjacent lanes are about 3 m apart and would start matching each other.

**`swap_left_right`: 0/4 by the expected check, 4/4 by any check.**
`left_right_swapped` never fired. When Lanelet2 loads a lanelet, it reorders the bounds so they
are consistent with each other. After a swap, that reverses the lanelet's travel direction instead
of leaving a mirrored lane for the geometric check to find. The reversed lanelet no longer connects
to its neighbors, so `unreachable_lanelet` caught every trial. The defect is caught, but the issue
names the wrong cause, and an annotator reading it would look for a broken connection rather than
swapped roles. The same behavior was found while testing in Phase B (see `docs/checks.md`).

**`narrow_lanelet`: 4/4 after a fix, 3/4 before.**
The first run missed trial 5 (approach lanelet narrowed to 2.0 m). The width function paired
points at equal fractions of each bound's length. On the approach lanelet the curb starts about
4 m before the painted line, so those pairs were diagonal: the narrowed lane measured 2.53 m and
passed. The clean lane also read 3.47 m when it is really about 3.2 m. `lanelet_average_width` now
measures perpendicular distance from sampled points to the opposite bound. Fault injection found
this bug in the check itself.

## What the false positives are

All 16 "false positives" are real downstream effects of the injected fault on neighboring
primitives. None comes from a check misfiring on an untouched part of the map. They are counted
as false positives anyway, because ground truth lists only one primitive per trial.

- **`remove_stop_line_ref` → `lanelet_missing_regulatory_element` on -82 (5).** Once the stop
  line is no longer referenced, the approach lanelet ends 2 m from a stop line that nothing points
  to. That is correct.
- **`shift_endpoint` / `detach_successor` → `unreachable_lanelet` on -71 (5).** Breaking the
  intersection-to-exit connection leaves the exit lanelet with no predecessor and no successor. That
  is correct.
- **`narrow_lanelet` → `lane_width_outlier` on a neighbor (4).** The narrowed bound's end nodes are
  shared with the neighboring lanelets, so moving them also narrows one end of each neighbor. That
  is an artifact of how the fault is injected, and the neighbor really is narrower.
- **`swap_left_right` on -78 → `unreachable_lanelet` on -71 and -82 (2).** Reversing the middle
  lanelet cuts the lane in two places. That is correct.

## Limitations of this evaluation

- The map has 3 lanelets, 1 regulatory element and 1 stop line, so many trials hit the same
  primitive. The 30 trials are 7 fault types run on very few targets, not 30 independent maps.
- Fault types were chosen to mirror the checks, so high recall is expected. This tests whether
  each check does what it claims. It does not test whether the checks cover the defects that
  actually happen in production.
