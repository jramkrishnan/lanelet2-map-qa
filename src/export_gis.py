"""Export the map and QA issues to GeoPackage for QGIS and PostGIS.

Run with: python3 src/export_gis.py   (after inject_faults.py, so faulty runs can be included)
Writes:
  outputs/map_qa.gpkg       EPSG:4326 (lat/lon), for viewing
  outputs/map_qa_2272.gpkg  EPSG:2272 (PA South, US survey feet), for measuring

Layers in both files:
  lanelets             polygon per lanelet, with tags, width, length, neighbors
  centerlines          centerline per lanelet, drawn in the travel direction
  boundaries           every linestring (curbs, lane lines, virtual bounds, stop line, light)
  regulatory_elements  each regulatory element as its light + stop line, plus attached lanelets
  issues               QA issues on the clean map (empty while the map is clean)
  faulty_issues        QA issues from every outputs/faulty/trial_XX.osm, with trial_id
"""

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point, Polygon

import lanelet2.geometry

from checks import build_routing_graph, lanelet_average_width, run_all_checks
from load_map import MAP_PATH, load_map

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"
FAULTY_DIR = OUTPUTS_DIR / "faulty"
GPKG_4326 = OUTPUTS_DIR / "map_qa.gpkg"
GPKG_2272 = OUTPUTS_DIR / "map_qa_2272.gpkg"


def to_lonlat(points, projector):
    """Projected Lanelet2 points (meters) -> list of (lon, lat) tuples."""
    coords = []
    for p in points:
        gps = projector.reverse(lanelet2.core.BasicPoint3d(p.x, p.y, p.z))
        coords.append((gps.lon, gps.lat))
    return coords


def ids(items):
    """A list of primitive ids as a comma-separated string (GeoPackage has no list type)."""
    return ",".join(str(item.id) for item in items)


def lanelet_rows(lanelet_map, graph, projector):
    lanelet_polys, centerlines = [], []
    for ll in lanelet_map.laneletLayer:
        tags = dict(ll.attributes)
        # Polygon outline: along the left bound, then back along the right bound.
        ring = to_lonlat(list(ll.leftBound) + list(reversed(list(ll.rightBound))), projector)
        attributes = {
            "lanelet_id": ll.id,
            "subtype": tags.get("subtype"),
            "location": tags.get("location"),
            "speed_limit": tags.get("speed_limit"),
            "width_m": round(lanelet_average_width(ll), 2),
            "length_m": round(lanelet2.geometry.length2d(ll), 2),
            "predecessors": ids(graph.previous(ll)),
            "successors": ids(graph.following(ll)),
            "regulatory_elements": ids(ll.regulatoryElements),
        }
        lanelet_polys.append({**attributes, "geometry": Polygon(ring)})
        centerlines.append({
            "lanelet_id": ll.id,
            "length_m": attributes["length_m"],
            "geometry": LineString(to_lonlat(ll.centerline, projector)),
        })
    return lanelet_polys, centerlines


def boundary_rows(lanelet_map, projector):
    rows = []
    for ls in lanelet_map.lineStringLayer:
        tags = dict(ls.attributes)
        rows.append({
            "linestring_id": ls.id,
            "type": tags.get("type"),
            "subtype": tags.get("subtype"),
            "geometry": LineString(to_lonlat(ls, projector)),
        })
    return rows


def regulatory_element_rows(lanelet_map, projector):
    rows = []
    for re in lanelet_map.regulatoryElementLayer:
        refers = list(re.parameters["refers"]) if "refers" in re.parameters else []
        ref_line = list(re.parameters["ref_line"]) if "ref_line" in re.parameters else []
        lines = [LineString(to_lonlat(ls, projector)) for ls in refers + ref_line]
        attached = [ll for ll in lanelet_map.laneletLayer if re in ll.regulatoryElements]
        rows.append({
            "regulatory_element_id": re.id,
            "subtype": dict(re.attributes).get("subtype"),
            "refers": ids(refers),
            "ref_line": ids(ref_line),
            "lanelets": ids(attached),
            "geometry": MultiLineString(lines) if lines else None,
        })
    return rows


def issue_rows(issues, trial_id=None):
    rows = []
    for issue in issues:
        row = {k: v for k, v in issue.items() if k not in ("lon", "lat")}
        if trial_id is not None:
            row = {"trial_id": trial_id, **row}
        row["geometry"] = Point(issue["lon"], issue["lat"])
        rows.append(row)
    return rows


def faulty_issue_rows():
    """Run the checks on every faulty copy, tagging each issue with its trial number."""
    rows = []
    for osm_path in sorted(FAULTY_DIR.glob("trial_*.osm")):
        trial_id = int(osm_path.stem.split("_")[1])
        lanelet_map, projector = load_map(osm_path)
        rows += issue_rows(run_all_checks(lanelet_map, projector, osm_path=osm_path), trial_id)
    return rows


def to_frame(rows, columns):
    """GeoDataFrame in EPSG:4326. `columns` keeps empty layers (no rows) writable with a schema."""
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    return gpd.GeoDataFrame(columns=columns + ["geometry"], geometry="geometry", crs="EPSG:4326")


def main():
    lanelet_map, projector = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    lanelet_polys, centerlines = lanelet_rows(lanelet_map, graph, projector)
    issue_columns = ["check", "severity", "primitive_type", "primitive_id", "message"]

    layers = {
        "lanelets": to_frame(lanelet_polys, []),
        "centerlines": to_frame(centerlines, []),
        "boundaries": to_frame(boundary_rows(lanelet_map, projector), []),
        "regulatory_elements": to_frame(regulatory_element_rows(lanelet_map, projector), []),
        "issues": to_frame(issue_rows(run_all_checks(lanelet_map, projector, osm_path=MAP_PATH)),
                           issue_columns),
        "faulty_issues": to_frame(faulty_issue_rows(), ["trial_id"] + issue_columns),
    }

    for path in (GPKG_4326, GPKG_2272):
        path.unlink(missing_ok=True)  # start fresh so layers from older runs don't linger
    for name, frame in layers.items():
        frame.to_file(GPKG_4326, layer=name, driver="GPKG")
        frame.to_crs("EPSG:2272").to_file(GPKG_2272, layer=name, driver="GPKG")
        print(f"  {name}: {len(frame)} features")
    print(f"Wrote {GPKG_4326} and {GPKG_2272}")


if __name__ == "__main__":
    main()
