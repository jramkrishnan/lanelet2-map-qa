"""The clean map should load, pass every check, and measure sensibly."""

from checks import lanelet_average_width, run_all_checks
from load_map import MAP_PATH, load_map


def test_clean_map_has_no_issues():
    lanelet_map, projector = load_map(MAP_PATH)
    assert run_all_checks(lanelet_map, projector, osm_path=MAP_PATH) == []


def test_map_has_expected_content():
    lanelet_map, _ = load_map(MAP_PATH)
    assert len(lanelet_map.laneletLayer) == 3
    assert len(lanelet_map.regulatoryElementLayer) == 1


def test_width_is_perpendicular_not_diagonal():
    """Regression test for the bug fault injection found. On the approach lanelet the curb
    starts ~4 m before the painted line; the old diagonal method read 3.47 m here."""
    lanelet_map, _ = load_map(MAP_PATH)
    width = lanelet_average_width(lanelet_map.laneletLayer[-82])
    assert 3.0 < width < 3.3
