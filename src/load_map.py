"""Load map/annotations.osm, project it to local meters, and report a sanity summary.

Run with: python3 src/load_map.py
"""

from pathlib import Path
from xml.etree import ElementTree

import lanelet2
import lanelet2.io
import lanelet2.projection
import lanelet2.routing
import lanelet2.traffic_rules

MAP_PATH = Path(__file__).resolve().parent.parent / "map" / "annotations.osm"

# Lanelet2's own convention for linestring "type" tags (lanelet2_core/Attribute.h).
# Used only to flag likely typos; it is not an exhaustive or enforced list.
KNOWN_LINESTRING_TYPES = {
    "line_thin",
    "line_thick",
    "curbstone",
    "virtual",
    "stop_line",
    "traffic_light",
    "traffic_sign",
    "road_border",
    "guard_rail",
    "wall",
    "fence",
    "zebra_marking",
}


def compute_origin(osm_path):
    """Centroid of every node's lat/lon in the raw OSM file; used as the UTM projector origin."""
    root = ElementTree.parse(osm_path).getroot()
    lats, lons = [], []
    for node in root.findall("node"):
        lats.append(float(node.get("lat")))
        lons.append(float(node.get("lon")))
    return sum(lats) / len(lats), sum(lons) / len(lons)


def compute_bbox(osm_path):
    """Lat/lon bounding box of every node in the raw OSM file."""
    root = ElementTree.parse(osm_path).getroot()
    lats, lons = [], []
    for node in root.findall("node"):
        lats.append(float(node.get("lat")))
        lons.append(float(node.get("lon")))
    return min(lats), max(lats), min(lons), max(lons)


def load_map(osm_path=MAP_PATH):
    """Load the map with a UtmProjector centered on the map's own node centroid."""
    lat, lon = compute_origin(osm_path)
    origin = lanelet2.io.Origin(lat, lon)
    projector = lanelet2.projection.UtmProjector(origin)
    lanelet_map = lanelet2.io.load(str(osm_path), projector)
    return lanelet_map, projector


def summarize(lanelet_map, osm_path=MAP_PATH):
    """Count primitives by their tags and report the map's bounding box."""
    by_subtype = {}
    for ll in lanelet_map.laneletLayer:
        subtype = dict(ll.attributes).get("subtype", "untagged")
        by_subtype[subtype] = by_subtype.get(subtype, 0) + 1

    line_by_type = {}
    for ls in lanelet_map.lineStringLayer:
        t = dict(ls.attributes).get("type", "untagged")
        line_by_type[t] = line_by_type.get(t, 0) + 1

    regelem_by_subtype = {}
    for re in lanelet_map.regulatoryElementLayer:
        subtype = dict(re.attributes).get("subtype", "untagged")
        regelem_by_subtype[subtype] = regelem_by_subtype.get(subtype, 0) + 1

    lat_min, lat_max, lon_min, lon_max = compute_bbox(osm_path)

    print("Lanelets by subtype:")
    for k, v in sorted(by_subtype.items()):
        print(f"  {k}: {v}")

    print("Linestrings by type:")
    for k, v in sorted(line_by_type.items()):
        print(f"  {k}: {v}")

    print("Regulatory elements by subtype:")
    for k, v in sorted(regelem_by_subtype.items()):
        print(f"  {k}: {v}")

    print(
        f"Bounding box: lat [{lat_min:.6f}, {lat_max:.6f}], "
        f"lon [{lon_min:.6f}, {lon_max:.6f}]"
    )


def check_tag_conventions(lanelet_map):
    """Flag linestring 'type' tags that don't match Lanelet2's naming convention (catches typos)."""
    flagged = []
    for ls in lanelet_map.lineStringLayer:
        t = dict(ls.attributes).get("type")
        if t and t not in KNOWN_LINESTRING_TYPES:
            flagged.append((ls.id, t))
    return flagged


def _direction_and_bound_midpoints(lanelet):
    """Travel direction (start-to-end, averaged over both bounds) and each bound's midpoint, in projected meters."""
    left = list(lanelet.leftBound)
    right = list(lanelet.rightBound)
    d_left = (left[-1].x - left[0].x, left[-1].y - left[0].y)
    d_right = (right[-1].x - right[0].x, right[-1].y - right[0].y)
    direction = ((d_left[0] + d_right[0]) / 2, (d_left[1] + d_right[1]) / 2)
    left_mid = (sum(p.x for p in left) / len(left), sum(p.y for p in left) / len(left))
    right_mid = (sum(p.x for p in right) / len(right), sum(p.y for p in right) / len(right))
    return direction, left_mid, right_mid


def check_bound_sides_and_direction(lanelet_map):
    """For each lanelet: is the tagged left bound geometrically left of travel, and does travel run northwest?

    "Left of travel" uses the standard 2D cross product: with x=east, y=north, the left
    bound's midpoint minus the right bound's midpoint should turn counterclockwise from
    the travel direction, i.e. cross(direction, left_mid - right_mid) > 0.
    """
    results = {}
    for ll in lanelet_map.laneletLayer:
        direction, left_mid, right_mid = _direction_and_bound_midpoints(ll)
        v = (left_mid[0] - right_mid[0], left_mid[1] - right_mid[1])
        cross = direction[0] * v[1] - direction[1] * v[0]
        results[ll.id] = {
            "left_is_left": cross > 0,
            "heads_northwest": direction[0] < 0 and direction[1] > 0,
        }
    return results


def check_routing_chain(lanelet_map):
    """Report each lanelet's predecessors/successors using Lanelet2's default (German) vehicle traffic rules."""
    rules = lanelet2.traffic_rules.create(
        lanelet2.traffic_rules.Locations.Germany, lanelet2.traffic_rules.Participants.Vehicle
    )
    graph = lanelet2.routing.RoutingGraph(lanelet_map, rules)
    chain = {}
    for ll in lanelet_map.laneletLayer:
        chain[ll.id] = {
            "previous": [p.id for p in graph.previous(ll)],
            "following": [f.id for f in graph.following(ll)],
        }
    return chain


def check_regulatory_elements(lanelet_map):
    """For each lanelet with a traffic_light regulatory element, confirm it has both a light (refers) and a stop line (ref_line)."""
    results = {}
    for ll in lanelet_map.laneletLayer:
        for re in ll.regulatoryElements:
            if dict(re.attributes).get("subtype") == "traffic_light":
                params = re.parameters
                results[ll.id] = {
                    "regelem_id": re.id,
                    "has_light": "refers" in params and len(list(params["refers"])) > 0,
                    "has_stop_line": "ref_line" in params and len(list(params["ref_line"])) > 0,
                }
    return results


def main():
    lanelet_map, _projector = load_map()
    print(f"Loaded {MAP_PATH.name} with {len(lanelet_map.laneletLayer)} lanelets, "
          f"{len(lanelet_map.lineStringLayer)} linestrings, "
          f"{len(lanelet_map.regulatoryElementLayer)} regulatory elements.\n")

    summarize(lanelet_map)

    print("\nTag convention check:")
    flagged = check_tag_conventions(lanelet_map)
    if flagged:
        for lid, t in flagged:
            print(f"  linestring {lid}: type='{t}' does not match Lanelet2's naming convention")
    else:
        print("  all linestring types match convention")

    print("\nBound direction check (left bound left-of-travel, travel heads northwest):")
    for lid, r in check_bound_sides_and_direction(lanelet_map).items():
        status = "OK" if r["left_is_left"] and r["heads_northwest"] else "CHECK"
        print(f"  lanelet {lid}: left_is_left={r['left_is_left']} heads_northwest={r['heads_northwest']} [{status}]")

    print("\nRouting graph connectivity:")
    for lid, r in check_routing_chain(lanelet_map).items():
        print(f"  lanelet {lid}: previous={r['previous']} following={r['following']}")

    print("\nRegulatory element check (traffic_light lanelets need both a light and a stop line):")
    reg_results = check_regulatory_elements(lanelet_map)
    if reg_results:
        for lid, r in reg_results.items():
            print(f"  lanelet {lid}: regelem {r['regelem_id']} has_light={r['has_light']} has_stop_line={r['has_stop_line']}")
    else:
        print("  no lanelet has a traffic_light regulatory element")


if __name__ == "__main__":
    main()
