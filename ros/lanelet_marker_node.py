"""ROS 2 node: publish the Lanelet2 map and a planned route as a MarkerArray for RViz2.

Run (with ROS 2 Jazzy sourced): python3 ros/lanelet_marker_node.py
Topic: /lanelet_markers (visualization_msgs/MarkerArray), frame "map", in meters from the
map's centroid. In RViz2: set Fixed Frame to "map", then Add -> By topic -> /lanelet_markers.
"""

import sys
from pathlib import Path

import rclpy
from geometry_msgs.msg import Point
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from checks import build_routing_graph  # noqa: E402
from load_map import MAP_PATH, load_map  # noqa: E402
from route import plan_route  # noqa: E402

# Color (r, g, b) and line width in meters for each boundary type; same scheme as the plot.
LINE_STYLES = {
    "curbstone": ((1.0, 1.0, 1.0), 0.25),
    "line_thin": ((0.7, 0.7, 0.7), 0.15),
    "virtual": ((0.4, 0.4, 0.4), 0.05),
    "stop_line": ((1.0, 0.0, 0.0), 0.4),
    "traffic_light": ((1.0, 0.6, 0.0), 0.5),
}
ROUTE_STYLE = ((0.1, 0.5, 1.0), 0.6)


def line_marker(marker_id, namespace, points, rgb, width):
    """A LINE_STRIP marker through the given Lanelet2 points."""
    marker = Marker()
    marker.header.frame_id = "map"
    marker.ns = namespace
    marker.id = marker_id
    marker.type = Marker.LINE_STRIP
    marker.action = Marker.ADD
    marker.pose.orientation.w = 1.0
    marker.scale.x = width
    marker.color = ColorRGBA(r=rgb[0], g=rgb[1], b=rgb[2], a=1.0)
    marker.points = [Point(x=p.x, y=p.y, z=0.0) for p in points]
    return marker


def build_markers(lanelet_map, route):
    markers = MarkerArray()
    for i, ls in enumerate(lanelet_map.lineStringLayer):
        rgb, width = LINE_STYLES.get(dict(ls.attributes).get("type"), ((1.0, 0.0, 1.0), 0.1))
        markers.markers.append(line_marker(i, "boundaries", list(ls), rgb, width))
    # The route is one continuous line through every route lanelet's centerline.
    route_points = [p for ll in route for p in ll.centerline]
    if route_points:
        markers.markers.append(line_marker(0, "route", route_points, *ROUTE_STYLE))
    return markers


class LaneletMarkerNode(Node):
    def __init__(self):
        super().__init__("lanelet_marker_node")
        lanelet_map, _projector = load_map(MAP_PATH)
        graph = build_routing_graph(lanelet_map)
        route = plan_route(lanelet_map, graph)
        self.get_logger().info("Route: " + " -> ".join(str(ll.id) for ll in route))
        self.markers = build_markers(lanelet_map, route)

        # Transient-local ("latched"): RViz gets the markers even if it starts after this node.
        qos = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.publisher = self.create_publisher(MarkerArray, "lanelet_markers", qos)
        self.create_timer(1.0, self.publish)

    def publish(self):
        stamp = self.get_clock().now().to_msg()
        for marker in self.markers.markers:
            marker.header.stamp = stamp
        self.publisher.publish(self.markers)


def main():
    rclpy.init()
    rclpy.spin(LaneletMarkerNode())


if __name__ == "__main__":
    main()
