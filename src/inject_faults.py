"""Make corrupted copies of the clean map, ONE fault per copy, plus a ground truth file.

Run with: python3 src/inject_faults.py --trials 30 --seed 42
Writes outputs/faulty/trial_XX.osm and outputs/ground_truth.csv.

The original map/annotations.osm is only read, never written. Each fault is applied by
editing the OSM XML of a fresh copy. Lanelet2 is used only to find valid targets (which
lanelet has a successor, which nodes they share) and to convert meters to lat/lon.
"""

import argparse
import copy
import csv
import math
import random
from pathlib import Path
from xml.etree import ElementTree

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

import lanelet2.core

from checks import build_routing_graph
from load_map import MAP_PATH, load_map

REPO_ROOT = Path(__file__).resolve().parent.parent
FAULTY_DIR = REPO_ROOT / "outputs" / "faulty"
GROUND_TRUTH_PATH = REPO_ROOT / "outputs" / "ground_truth.csv"

NARROW_WIDTH_M = 2.0
SHIFT_MIN_M = 0.5
SHIFT_MAX_M = 2.0

# Fault type -> the check that is supposed to catch it.
FAULT_TYPES = {
    "remove_stop_line_ref": "traffic_light_missing_stop_line",
    "shift_endpoint": "connection_gap",
    "remove_speed_limit": "missing_speed_limit",
    "swap_left_right": "left_right_swapped",
    "narrow_lanelet": "lane_width_outlier",
    "detach_regulatory_element": "lanelet_missing_regulatory_element",
    "detach_successor": "connection_gap",
}


# ---------- small XML helpers ----------

def find_relation(root, relation_id):
    for rel in root.findall("relation"):
        if int(rel.get("id")) == relation_id:
            return rel
    raise KeyError(relation_id)


def find_way(root, way_id):
    for way in root.findall("way"):
        if int(way.get("id")) == way_id:
            return way
    raise KeyError(way_id)


def find_node(root, node_id):
    for node in root.findall("node"):
        if int(node.get("id")) == node_id:
            return node
    raise KeyError(node_id)


def bound_way_id(root, lanelet_id, role):
    """The way id that plays `role` ('left' or 'right') in a lanelet relation."""
    for member in find_relation(root, lanelet_id).findall("member"):
        if member.get("role") == role:
            return int(member.get("ref"))
    raise KeyError((lanelet_id, role))


def add_node_copy(root, node_id, lat, lon):
    """Add a new node at (lat, lon), JOSM-style with the next unused negative id. Returns its id."""
    new_id = min(int(n.get("id")) for n in root.findall("node")) - 1
    new_node = copy.deepcopy(find_node(root, node_id))
    new_node.set("id", str(new_id))
    new_node.set("lat", f"{lat:.11f}")
    new_node.set("lon", f"{lon:.11f}")
    root.insert(list(root).index(root.findall("node")[-1]) + 1, new_node)
    return new_id


def replace_node_in_way(root, way_id, old_node_id, new_node_id):
    for nd in find_way(root, way_id).findall("nd"):
        if int(nd.get("ref")) == old_node_id:
            nd.set("ref", str(new_node_id))


def set_node_position(root, node_id, lat, lon):
    node = find_node(root, node_id)
    node.set("lat", f"{lat:.11f}")
    node.set("lon", f"{lon:.11f}")


def to_latlon(projector, x, y):
    gps = projector.reverse(lanelet2.core.BasicPoint3d(x, y, 0))
    return gps.lat, gps.lon


# ---------- one function per fault type ----------
# Each takes (root, lanelet_map, graph, projector, rng), edits root in place, and returns
# (primitive_type, primitive_id, detail) describing exactly what was broken.

def fault_remove_stop_line_ref(root, lanelet_map, graph, projector, rng):
    """Delete the ref_line (stop line) member from a traffic_light regulatory element."""
    candidates = [
        re for re in lanelet_map.regulatoryElementLayer
        if dict(re.attributes).get("subtype") == "traffic_light" and "ref_line" in re.parameters
    ]
    re = rng.choice(candidates)
    relation = find_relation(root, re.id)
    for member in relation.findall("member"):
        if member.get("role") == "ref_line":
            relation.remove(member)
    return "regulatory_element", re.id, "removed ref_line member"


def successor_pairs(lanelet_map, graph):
    return [(ll, succ) for ll in lanelet_map.laneletLayer for succ in graph.following(ll)]


def fault_shift_endpoint(root, lanelet_map, graph, projector, rng):
    """Move one end node of a lanelet 0.5-2 m in a random direction so it no longer meets its
    successor. The successor keeps the original node, so the two no longer share it."""
    ll, succ = rng.choice(successor_pairs(lanelet_map, graph))
    side = rng.choice(["left", "right"])
    end_point = ll.leftBound[-1] if side == "left" else ll.rightBound[-1]
    distance = rng.uniform(SHIFT_MIN_M, SHIFT_MAX_M)
    angle = rng.uniform(0, 2 * math.pi)
    lat, lon = to_latlon(
        projector,
        end_point.x + distance * math.cos(angle),
        end_point.y + distance * math.sin(angle),
    )
    new_id = add_node_copy(root, end_point.id, lat, lon)
    replace_node_in_way(root, bound_way_id(root, ll.id, side), end_point.id, new_id)
    return "lanelet", ll.id, f"{side} end shifted {distance:.2f} m away from successor {succ.id}"


def fault_remove_speed_limit(root, lanelet_map, graph, projector, rng):
    """Delete the speed_limit tag from one lanelet."""
    ll = rng.choice([ll for ll in lanelet_map.laneletLayer if "speed_limit" in dict(ll.attributes)])
    relation = find_relation(root, ll.id)
    for tag in relation.findall("tag"):
        if tag.get("k") == "speed_limit":
            relation.remove(tag)
    return "lanelet", ll.id, "removed speed_limit tag"


def fault_swap_left_right(root, lanelet_map, graph, projector, rng):
    """Swap the 'left' and 'right' roles in one lanelet relation."""
    ll = rng.choice(list(lanelet_map.laneletLayer))
    for member in find_relation(root, ll.id).findall("member"):
        if member.get("role") == "left":
            member.set("role", "right")
        elif member.get("role") == "right":
            member.set("role", "left")
    return "lanelet", ll.id, "swapped left/right member roles"


def fault_narrow_lanelet(root, lanelet_map, graph, projector, rng):
    """Move every node of a lanelet's left (painted) bound toward the right (curb) bound so the
    lane is NARROW_WIDTH_M wide. End nodes are shared with neighbors, so they move too."""
    ll = rng.choice(list(lanelet_map.laneletLayer))
    right_line = LineString([(p.x, p.y) for p in ll.rightBound])
    for p in ll.leftBound:
        nearest = nearest_points(right_line, Point(p.x, p.y))[0]
        dx, dy = p.x - nearest.x, p.y - nearest.y
        current = math.hypot(dx, dy)
        scale = NARROW_WIDTH_M / current
        lat, lon = to_latlon(projector, nearest.x + dx * scale, nearest.y + dy * scale)
        set_node_position(root, p.id, lat, lon)
    return "lanelet", ll.id, f"left bound moved to {NARROW_WIDTH_M} m from right bound"


def fault_detach_regulatory_element(root, lanelet_map, graph, projector, rng):
    """Remove the regulatory_element member from a lanelet (the regulatory element still exists,
    but no lanelet points to it)."""
    ll = rng.choice([ll for ll in lanelet_map.laneletLayer if len(ll.regulatoryElements) > 0])
    relation = find_relation(root, ll.id)
    for member in relation.findall("member"):
        if member.get("role") == "regulatory_element":
            relation.remove(member)
    return "lanelet", ll.id, "removed regulatory_element member"


def fault_detach_successor(root, lanelet_map, graph, projector, rng):
    """Give a lanelet's two end nodes duplicates at the exact same position, so it no longer
    shares nodes with its successor. This is the classic JOSM 'looks connected but isn't' error."""
    ll, succ = rng.choice(successor_pairs(lanelet_map, graph))
    for side, end_point in (("left", ll.leftBound[-1]), ("right", ll.rightBound[-1])):
        node = find_node(root, end_point.id)
        new_id = add_node_copy(root, end_point.id, float(node.get("lat")), float(node.get("lon")))
        replace_node_in_way(root, bound_way_id(root, ll.id, side), end_point.id, new_id)
    return "lanelet", ll.id, f"end nodes duplicated, no longer shared with successor {succ.id}"


FAULT_FUNCTIONS = {
    "remove_stop_line_ref": fault_remove_stop_line_ref,
    "shift_endpoint": fault_shift_endpoint,
    "remove_speed_limit": fault_remove_speed_limit,
    "swap_left_right": fault_swap_left_right,
    "narrow_lanelet": fault_narrow_lanelet,
    "detach_regulatory_element": fault_detach_regulatory_element,
    "detach_successor": fault_detach_successor,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    lanelet_map, projector = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    FAULTY_DIR.mkdir(parents=True, exist_ok=True)

    fault_names = list(FAULT_FUNCTIONS)
    rows = []
    for trial in range(1, args.trials + 1):
        # Cycle through fault types so each gets a near-equal share of trials; the random
        # part is which primitive is hit and by how much.
        fault_type = fault_names[(trial - 1) % len(fault_names)]
        tree = ElementTree.parse(MAP_PATH)
        primitive_type, primitive_id, detail = FAULT_FUNCTIONS[fault_type](
            tree.getroot(), lanelet_map, graph, projector, rng
        )
        out_path = FAULTY_DIR / f"trial_{trial:02d}.osm"
        tree.write(out_path, encoding="UTF-8", xml_declaration=True)
        rows.append({
            "trial_id": trial,
            "fault_type": fault_type,
            "primitive_type": primitive_type,
            "primitive_id": primitive_id,
            "expected_check": FAULT_TYPES[fault_type],
            "detail": detail,
        })

    with open(GROUND_TRUTH_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} faulty maps to {FAULTY_DIR} and {GROUND_TRUTH_PATH}")


if __name__ == "__main__":
    main()
