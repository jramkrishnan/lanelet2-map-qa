"""Inject one fault into a temporary copy of the map and check that the QA checks catch it."""

import random
from xml.etree import ElementTree

import pytest

import inject_faults
from checks import build_routing_graph, run_all_checks
from load_map import MAP_PATH, load_map


def apply_fault(fault_type, tmp_path, seed=0):
    """Write a copy of the map with one fault to tmp_path. Returns (path, faulted primitive id)."""
    lanelet_map, projector = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    tree = ElementTree.parse(MAP_PATH)
    _, primitive_id, _ = inject_faults.FAULT_FUNCTIONS[fault_type](
        tree.getroot(), lanelet_map, graph, projector, random.Random(seed)
    )
    out_path = tmp_path / f"{fault_type}.osm"
    tree.write(out_path, encoding="UTF-8", xml_declaration=True)
    return out_path, primitive_id


def checks_flagging(osm_path, primitive_id):
    lanelet_map, projector = load_map(osm_path)
    issues = run_all_checks(lanelet_map, projector, osm_path=osm_path)
    return {i["check"] for i in issues if i["primitive_id"] == primitive_id}


@pytest.mark.parametrize("fault_type", [
    "remove_stop_line_ref",
    "remove_speed_limit",
    "narrow_lanelet",
    "detach_regulatory_element",
    "detach_successor",
])
def test_fault_caught_by_expected_check(fault_type, tmp_path):
    osm_path, primitive_id = apply_fault(fault_type, tmp_path)
    assert inject_faults.FAULT_TYPES[fault_type] in checks_flagging(osm_path, primitive_id)


def test_small_endpoint_shift_is_caught(tmp_path, monkeypatch):
    """A shift under the 1 m near-miss radius is a connection_gap."""
    monkeypatch.setattr(inject_faults, "SHIFT_MIN_M", 0.6)
    monkeypatch.setattr(inject_faults, "SHIFT_MAX_M", 0.6)
    osm_path, primitive_id = apply_fault("shift_endpoint", tmp_path)
    assert "connection_gap" in checks_flagging(osm_path, primitive_id)


def test_swap_left_right_surfaces_as_unreachable(tmp_path):
    """Known behavior (see outputs/eval.md): Lanelet2 reverses the swapped lanelet on load, so
    the swap is caught by unreachable_lanelet, not left_right_swapped."""
    osm_path, primitive_id = apply_fault("swap_left_right", tmp_path)
    flagged = checks_flagging(osm_path, primitive_id)
    assert "unreachable_lanelet" in flagged
    assert "left_right_swapped" not in flagged


def test_fault_injection_leaves_original_map_untouched(tmp_path):
    before = MAP_PATH.read_bytes()
    for fault_type in inject_faults.FAULT_FUNCTIONS:
        apply_fault(fault_type, tmp_path)
    assert MAP_PATH.read_bytes() == before
