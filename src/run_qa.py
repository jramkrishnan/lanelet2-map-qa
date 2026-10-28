"""CLI: run all QA checks on a Lanelet2 map and write the results.

Run with: python3 src/run_qa.py [path/to/map.osm]
Writes outputs/issues.geojson (WGS84) and outputs/issues.csv, and prints counts by
check and severity.
"""

import csv
import json
import sys
from pathlib import Path

from checks import run_all_checks
from load_map import MAP_PATH, load_map

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = REPO_ROOT / "outputs"


def issues_to_geojson(issues):
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [issue["lon"], issue["lat"]]},
                "properties": {k: v for k, v in issue.items() if k not in ("lon", "lat")},
            }
            for issue in issues
        ],
    }


def write_outputs(issues, outputs_dir=OUTPUTS_DIR):
    outputs_dir.mkdir(parents=True, exist_ok=True)

    with open(outputs_dir / "issues.geojson", "w") as f:
        json.dump(issues_to_geojson(issues), f, indent=2)

    fieldnames = ["check", "severity", "primitive_type", "primitive_id", "message", "lon", "lat"]
    with open(outputs_dir / "issues.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(issues)


def print_counts(issues):
    by_check = {}
    by_severity = {}
    for issue in issues:
        by_check[issue["check"]] = by_check.get(issue["check"], 0) + 1
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1

    print(f"Total issues: {len(issues)}")
    print("By check:")
    for k, v in sorted(by_check.items()):
        print(f"  {k}: {v}")
    print("By severity:")
    for k, v in sorted(by_severity.items()):
        print(f"  {k}: {v}")


def main():
    osm_path = Path(sys.argv[1]) if len(sys.argv) > 1 else MAP_PATH
    lanelet_map, projector = load_map(osm_path)
    issues = run_all_checks(lanelet_map, projector, osm_path=osm_path)
    write_outputs(issues)
    print_counts(issues)


if __name__ == "__main__":
    main()
