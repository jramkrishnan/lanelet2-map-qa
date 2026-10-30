"""Plan a route through the map with lanelet2.routing and plot it.

Run with: python3 src/plot_route.py [--from LANELET_ID] [--to LANELET_ID]
Writes outputs/figures/route.png. With no ids, the route runs from the lanelet with no
predecessor (the approach) to the lanelet with no successor (the exit).
"""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write to a file; no display needed
import matplotlib.pyplot as plt

from checks import build_routing_graph
from load_map import MAP_PATH, load_map
from route import plan_route

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGURE_PATH = REPO_ROOT / "outputs" / "figures" / "route.png"

# How each boundary type is drawn: (color, linestyle, linewidth).
LINE_STYLES = {
    "curbstone": ("black", "-", 2.0),
    "line_thin": ("grey", "--", 1.2),
    "virtual": ("lightgrey", ":", 1.0),
    "stop_line": ("red", "-", 3.0),
    "traffic_light": ("orange", "-", 4.0),
}


def plot(lanelet_map, route, out_path):
    fig, ax = plt.subplots(figsize=(7, 8))

    for ll in lanelet_map.laneletLayer:
        outline = list(ll.leftBound) + list(reversed(list(ll.rightBound)))
        color = "tab:blue" if ll in route else "lightgrey"
        ax.fill([p.x for p in outline], [p.y for p in outline], color=color, alpha=0.25)
        center = list(ll.centerline)
        ax.annotate(str(ll.id), (center[len(center) // 2].x, center[len(center) // 2].y),
                    fontsize=8, ha="center")

    for ls in lanelet_map.lineStringLayer:
        color, style, width = LINE_STYLES.get(dict(ls.attributes).get("type"), ("purple", "-", 1.0))
        ax.plot([p.x for p in ls], [p.y for p in ls], color=color, linestyle=style, linewidth=width)

    # Route: one arrow per lanelet, along its centerline, in the travel direction.
    for ll in route:
        center = list(ll.centerline)
        ax.plot([p.x for p in center], [p.y for p in center], color="tab:blue", linewidth=2)
        ax.annotate("", xy=(center[-1].x, center[-1].y), xytext=(center[-2].x, center[-2].y),
                    arrowprops={"arrowstyle": "-|>", "color": "tab:blue", "lw": 2})

    route_text = " -> ".join(str(ll.id) for ll in route) or "no route found"
    ax.set_title(f"Route via lanelet2.routing: {route_text}", fontsize=10)
    ax.set_xlabel("meters east of map centroid")
    ax.set_ylabel("meters north of map centroid")
    ax.set_aspect("equal")
    ax.grid(alpha=0.3)
    handles = [plt.Line2D([], [], color=c, linestyle=s, linewidth=w, label=t)
               for t, (c, s, w) in LINE_STYLES.items()]
    handles.append(plt.Line2D([], [], color="tab:blue", linewidth=2, label="planned route"))
    ax.legend(handles=handles, loc="lower left", fontsize=8)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="from_id", type=int)
    parser.add_argument("--to", dest="to_id", type=int)
    args = parser.parse_args()

    lanelet_map, _projector = load_map(MAP_PATH)
    graph = build_routing_graph(lanelet_map)
    route = plan_route(lanelet_map, graph, args.from_id, args.to_id)
    print("Route:", " -> ".join(str(ll.id) for ll in route) or "none")
    plot(lanelet_map, route, FIGURE_PATH)
    print(f"Wrote {FIGURE_PATH}")


if __name__ == "__main__":
    main()
