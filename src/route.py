"""Route planning with lanelet2.routing. Kept free of plotting imports so the ROS 2 node can
use it without matplotlib."""

from checks import road_lanelets


def plan_route(lanelet_map, graph, from_id=None, to_id=None):
    """Shortest path between two lanelets, as a list of lanelets (empty if there is none).
    Defaults: start at a lanelet with no predecessor, end at one with no successor."""
    lanelets = road_lanelets(lanelet_map)
    start = lanelet_map.laneletLayer[from_id] if from_id else next(
        ll for ll in lanelets if len(graph.previous(ll)) == 0)
    end = lanelet_map.laneletLayer[to_id] if to_id else next(
        ll for ll in lanelets if len(graph.following(ll)) == 0)
    path = graph.shortestPath(start, end)
    return list(path) if path else []
