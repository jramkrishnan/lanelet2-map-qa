"""Routing through J's single lane: approach -> intersection -> exit."""

from checks import build_routing_graph
from load_map import MAP_PATH, load_map
from route import plan_route


def test_route_runs_approach_to_exit():
    lanelet_map, _ = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    assert [ll.id for ll in plan_route(lanelet_map, graph)] == [-82, -78, -71]


def test_no_route_backwards():
    lanelet_map, _ = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    assert plan_route(lanelet_map, graph, from_id=-71, to_id=-82) == []
