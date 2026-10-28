"""QA checks for a loaded Lanelet2 map. One function per check.

Each check function takes (lanelet_map, graph, projector, config) and returns a list of
issue dicts: {check, severity, primitive_type, primitive_id, message, lon, lat}.
"""

from xml.etree import ElementTree

import lanelet2.core
import lanelet2.geometry
import lanelet2.routing
import lanelet2.traffic_rules

DEFAULT_CONFIG = {
    "connection_gap_tolerance_m": 0.1,
    "connection_near_miss_m": 1.0,
    "stop_line_search_radius_m": 2.0,
    "lane_width_min_m": 2.5,
    "lane_width_max_m": 4.5,
}

# The only member roles a lanelet relation should have (lanelet2_core/primitives/Lanelet).
ALLOWED_LANELET_ROLES = {"left", "right", "centerline", "regulatory_element"}


def build_routing_graph(lanelet_map):
    """RoutingGraph using Lanelet2's default (German) vehicle traffic rules — a library default,
    not a Pittsburgh-specific choice; noted in docs/checks.md."""
    rules = lanelet2.traffic_rules.create(
        lanelet2.traffic_rules.Locations.Germany, lanelet2.traffic_rules.Participants.Vehicle
    )
    return lanelet2.routing.RoutingGraph(lanelet_map, rules)


def _issue(check, severity, primitive_type, primitive_id, message, point, projector):
    gps = projector.reverse(point)
    return {
        "check": check,
        "severity": severity,
        "primitive_type": primitive_type,
        "primitive_id": primitive_id,
        "message": message,
        "lon": gps.lon,
        "lat": gps.lat,
    }


def _mean_point(points):
    points = list(points)
    x = sum(p.x for p in points) / len(points)
    y = sum(p.y for p in points) / len(points)
    z = sum(p.z for p in points) / len(points)
    return lanelet2.core.BasicPoint3d(x, y, z)


def lanelet_point(lanelet):
    """A representative point for a lanelet: the mean of its left and right bound points."""
    return _mean_point(list(lanelet.leftBound) + list(lanelet.rightBound))


def linestring_point(linestring):
    """A representative point for a linestring: the mean of its points."""
    return _mean_point(list(linestring))


def direction_and_bound_midpoints(lanelet):
    """Travel direction (start-to-end, averaged over both bounds) and each bound's midpoint,
    in the map's projected meters. Shared with load_map.py's Phase A sanity check."""
    left = list(lanelet.leftBound)
    right = list(lanelet.rightBound)
    d_left = (left[-1].x - left[0].x, left[-1].y - left[0].y)
    d_right = (right[-1].x - right[0].x, right[-1].y - right[0].y)
    direction = ((d_left[0] + d_right[0]) / 2, (d_left[1] + d_right[1]) / 2)
    left_mid = (sum(p.x for p in left) / len(left), sum(p.y for p in left) / len(left))
    right_mid = (sum(p.x for p in right) / len(right), sum(p.y for p in right) / len(right))
    return direction, left_mid, right_mid


def lanelet_average_width(lanelet, samples=5):
    """Average distance between left and right bound, sampled at even fractions of each
    bound's own length (so it works even when the two bounds have different vertex counts)."""
    left, right = lanelet.leftBound, lanelet.rightBound
    left_len = lanelet2.geometry.length(left)
    right_len = lanelet2.geometry.length(right)
    widths = []
    for i in range(samples):
        t = i / (samples - 1) if samples > 1 else 0.5
        lp = lanelet2.geometry.interpolatedPointAtDistance(left, t * left_len)
        rp = lanelet2.geometry.interpolatedPointAtDistance(right, t * right_len)
        widths.append(lanelet2.geometry.distance(lp, rp))
    return sum(widths) / len(widths)


def road_lanelets(lanelet_map):
    return [ll for ll in lanelet_map.laneletLayer if dict(ll.attributes).get("subtype") == "road"]


def check_unreachable_lanelet(lanelet_map, graph, projector, config):
    """A road lanelet with neither predecessor nor successor in the routing graph.

    A lanelet at the edge of the mapped area is expected to be missing one side (it's a dead
    end because the map stops there) — that's fine. This only flags a lanelet missing BOTH.
    """
    issues = []
    for ll in road_lanelets(lanelet_map):
        has_prev = len(list(graph.previous(ll))) > 0
        has_next = len(list(graph.following(ll))) > 0
        if not has_prev and not has_next:
            issues.append(_issue(
                "unreachable_lanelet", "error", "lanelet", ll.id,
                f"Lanelet {ll.id} has no predecessor or successor in the routing graph.",
                lanelet_point(ll), projector,
            ))
    return issues


def check_connection_gap(lanelet_map, graph, projector, config):
    """Two ways a lane connection can be broken:

    1. Lanelets the routing graph treats as connected, but whose bound endpoints don't actually
       coincide (gap > connection_gap_tolerance_m) — a routing/geometry mismatch.
    2. Lanelets that look connected (end of one within connection_near_miss_m of the start of
       another) but don't share nodes and so the routing graph doesn't link them — usually a
       JOSM duplicate-node mistake instead of a shared one.
    """
    issues = []
    tol = config["connection_gap_tolerance_m"]
    near = config["connection_near_miss_m"]
    lanelets = road_lanelets(lanelet_map)

    connected_pairs = set()
    for ll in lanelets:
        for succ in graph.following(ll):
            connected_pairs.add((ll.id, succ.id))
            left_gap = lanelet2.geometry.distance(ll.leftBound[-1], succ.leftBound[0])
            right_gap = lanelet2.geometry.distance(ll.rightBound[-1], succ.rightBound[0])
            if left_gap > tol or right_gap > tol:
                issues.append(_issue(
                    "connection_gap", "error", "lanelet", ll.id,
                    f"Lanelet {ll.id} end does not coincide with successor {succ.id} start "
                    f"(left gap {left_gap:.2f} m, right gap {right_gap:.2f} m).",
                    ll.rightBound[-1].basicPoint(), projector,
                ))

    for a in lanelets:
        a_end_left, a_end_right = a.leftBound[-1], a.rightBound[-1]
        for b in lanelets:
            if a.id == b.id or (a.id, b.id) in connected_pairs:
                continue
            b_start_left, b_start_right = b.leftBound[0], b.rightBound[0]
            if a_end_left.id == b_start_left.id and a_end_right.id == b_start_right.id:
                continue  # fully connected via shared nodes on both sides, no gap possible
            d_left = lanelet2.geometry.distance(a_end_left, b_start_left)
            d_right = lanelet2.geometry.distance(a_end_right, b_start_right)
            if d_left <= near and d_right <= near:
                issues.append(_issue(
                    "connection_gap", "warning", "lanelet", a.id,
                    f"Lanelet {a.id} end is within {near} m of lanelet {b.id} start but they "
                    f"don't share nodes and aren't connected in the routing graph.",
                    a_end_right.basicPoint(), projector,
                ))
    return issues


def check_traffic_light_missing_stop_line(lanelet_map, graph, projector, config):
    """A traffic_light regulatory element with no ref_line (stop line)."""
    issues = []
    seen = set()
    for ll in lanelet_map.laneletLayer:
        for re in ll.regulatoryElements:
            if re.id in seen or dict(re.attributes).get("subtype") != "traffic_light":
                continue
            seen.add(re.id)
            has_stop_line = "ref_line" in re.parameters and len(list(re.parameters["ref_line"])) > 0
            if not has_stop_line:
                issues.append(_issue(
                    "traffic_light_missing_stop_line", "error", "regulatory_element", re.id,
                    f"Traffic light regulatory element {re.id} (on lanelet {ll.id}) has no ref_line.",
                    lanelet_point(ll), projector,
                ))
    return issues


def check_lanelet_missing_regulatory_element(lanelet_map, graph, projector, config):
    """A lanelet whose end lies within stop_line_search_radius_m of a stop line, but which has
    no regulatory element referencing that stop line."""
    issues = []
    radius = config["stop_line_search_radius_m"]
    stop_lines = [ls for ls in lanelet_map.lineStringLayer if dict(ls.attributes).get("type") == "stop_line"]
    for ll in road_lanelets(lanelet_map):
        end_left, end_right = ll.leftBound[-1], ll.rightBound[-1]
        referenced_ids = {
            p.id
            for re in ll.regulatoryElements
            if "ref_line" in re.parameters
            for p in re.parameters["ref_line"]
        }
        for sl in stop_lines:
            if sl.id in referenced_ids:
                continue
            d = min(lanelet2.geometry.distance(end_left, sl), lanelet2.geometry.distance(end_right, sl))
            if d <= radius:
                issues.append(_issue(
                    "lanelet_missing_regulatory_element", "error", "lanelet", ll.id,
                    f"Lanelet {ll.id} ends within {d:.2f} m of stop line {sl.id} but has no "
                    f"regulatory element referencing it.",
                    end_right.basicPoint(), projector,
                ))
    return issues


def check_crosswalk_untagged(lanelet_map, graph, projector, config):
    """A crosswalk lanelet that no regulatory element refers to. Skips gracefully if there are
    no crosswalks yet."""
    crosswalks = [ll for ll in lanelet_map.laneletLayer if dict(ll.attributes).get("subtype") == "crosswalk"]
    if not crosswalks:
        return []

    referenced_ids = set()
    for re in lanelet_map.regulatoryElementLayer:
        for members in re.parameters.values():
            for member in members:
                if hasattr(member, "id"):
                    referenced_ids.add(member.id)

    issues = []
    for cw in crosswalks:
        if cw.id not in referenced_ids:
            issues.append(_issue(
                "crosswalk_untagged", "warning", "lanelet", cw.id,
                f"Crosswalk lanelet {cw.id} is not referenced by any regulatory element.",
                lanelet_point(cw), projector,
            ))
    return issues


def check_lane_width_outlier(lanelet_map, graph, projector, config):
    """A road lanelet whose average width falls outside [lane_width_min_m, lane_width_max_m]."""
    issues = []
    lo, hi = config["lane_width_min_m"], config["lane_width_max_m"]
    for ll in road_lanelets(lanelet_map):
        width = lanelet_average_width(ll)
        if width < lo or width > hi:
            issues.append(_issue(
                "lane_width_outlier", "warning", "lanelet", ll.id,
                f"Lanelet {ll.id} average width {width:.2f} m is outside the expected "
                f"{lo}-{hi} m range.",
                lanelet_point(ll), projector,
            ))
    return issues


def check_missing_speed_limit(lanelet_map, graph, projector, config):
    """A road lanelet with no speed_limit tag."""
    issues = []
    for ll in road_lanelets(lanelet_map):
        if "speed_limit" not in dict(ll.attributes):
            issues.append(_issue(
                "missing_speed_limit", "error", "lanelet", ll.id,
                f"Lanelet {ll.id} has no speed_limit tag.",
                lanelet_point(ll), projector,
            ))
    return issues


def check_left_right_swapped(lanelet_map, graph, projector, config, osm_path=None):
    """Two symptoms of mixed-up lanelet roles:

    1. After Lanelet2's own bound-direction auto-alignment, the bound tagged "left" is not
       geometrically on the left of the travel direction — J tagged left/right backwards.
    2. The raw lanelet relation has a member role other than left/right/centerline/
       regulatory_element — a typo'd or stray role Lanelet2 silently drops on load, so it has
       to be caught by reading the source file directly.
    """
    issues = []
    for ll in lanelet_map.laneletLayer:
        direction, left_mid, right_mid = direction_and_bound_midpoints(ll)
        v = (left_mid[0] - right_mid[0], left_mid[1] - right_mid[1])
        cross = direction[0] * v[1] - direction[1] * v[0]
        if cross <= 0:
            issues.append(_issue(
                "left_right_swapped", "error", "lanelet", ll.id,
                f"Lanelet {ll.id}'s left bound is not geometrically left of its travel "
                f"direction (left/right roles may be swapped).",
                lanelet_point(ll), projector,
            ))

    if osm_path is not None:
        root = ElementTree.parse(osm_path).getroot()
        for relation in root.findall("relation"):
            tags = {t.get("k"): t.get("v") for t in relation.findall("tag")}
            if tags.get("type") != "lanelet":
                continue
            lanelet_id = int(relation.get("id"))
            roles = {m.get("role") for m in relation.findall("member")}
            unexpected = roles - ALLOWED_LANELET_ROLES
            if unexpected:
                try:
                    point = lanelet_point(lanelet_map.laneletLayer[lanelet_id])
                except KeyError:
                    point = lanelet2.core.BasicPoint3d(0, 0, 0)
                issues.append(_issue(
                    "left_right_swapped", "error", "lanelet", lanelet_id,
                    f"Lanelet relation {lanelet_id} has unexpected member role(s): "
                    f"{sorted(unexpected)}.",
                    point, projector,
                ))
    return issues


ALL_CHECKS = [
    check_unreachable_lanelet,
    check_connection_gap,
    check_traffic_light_missing_stop_line,
    check_lanelet_missing_regulatory_element,
    check_crosswalk_untagged,
    check_lane_width_outlier,
    check_missing_speed_limit,
    check_left_right_swapped,
]


def run_all_checks(lanelet_map, projector, osm_path=None, config=None):
    config = config or DEFAULT_CONFIG
    graph = build_routing_graph(lanelet_map)
    issues = []
    for check in ALL_CHECKS:
        if check is check_left_right_swapped:
            issues.extend(check(lanelet_map, graph, projector, config, osm_path=osm_path))
        else:
            issues.extend(check(lanelet_map, graph, projector, config))
    return issues
