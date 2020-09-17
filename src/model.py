from typing import List, Tuple
from collections import namedtuple
from ortools.constraint_solver import pywrapcp, routing_enums_pb2
import plotly.graph_objects as go


def get_dropped_nodes(
    model: "Ortools Routing Model", assignment: "Ortools Routing Assignment"
) -> List[int]:
    dropped = []
    for idx in range(model.Size()):
        if assignment.Value(model.NextVar(idx)) == idx:
            dropped.append(idx)

    return dropped


def get_solution_str(solution: "Solution") -> str:
    _str = ""

    for i, r in enumerate(solution):
        _str += f"Route(idx={i})\n"
        s = "\n".join("{}: {}".format(*k) for k in enumerate(r))
        _str += s + "\n\n"

    return _str


def solve(
    nodes: List[Tuple[float, float, int]],
    distance_matrix: List[List[int]],
    demand: List[int],
    depot_index: int = 0,
    vehicle_cap: int = 26,
    num_vehicles: int = None,
    distance_constraint_int: int = 100000,
    soft_distance_constrint_int: int = None,
    soft_distance_penalty: int = 100000,
    max_search_seconds: int = 5,
) -> "Solution":
    """
    high level implementation of an ortools capacitated vehicle routing model.

    :distance_matrix:               [[int, int, int, ...], [...] ...] distance matrix of origin
                                    at node 0 and demand nodes at 1 -> len(matrix) - 1 processed
                                    at a known precision
    :demand_quantities:             [int, int, ... len(demand nodes) - 1]
    :max_vehicle_capacity_units:    int for vehicle capacity constraint (in demand units)
    :num_vehicles:                  int for number of vehicle allowance
    :distance_constraint_int:       int (processed for distance matrix precision) to use as
                                    distance upper bound
    :soft_distance_constrint_int:   soft upper bound constraint for vehicle distances
    :soft_distance_penalty:         soft upper bound penalty for exceeding distance constraint

    TODO:
        - update with namedtuple usage
        - use nodes list to handle as much as possible
        - handle integer precision entirely
        - refactor into smaller functions
        - refactor with less arg complexity (better arg and config management)
        - add solution type

    """
    NODES = nodes
    DISTANCE_MATRIX = distance_matrix
    NUM_NODES = len(distance_matrix)

    if len(distance_matrix) - 1 == len(demand):
        DEMAND = [0] + list(demand)
    else:
        DEMAND = demand

    DEPOT_INDEX = depot_index
    VEHICLE_CAP = vehicle_cap

    if not num_vehicles:
        NUM_VEHICLES = len(DEMAND[1:])
    else:
        NUM_VEHICLES = num_vehicles

    VEHICLES = [vehicle_cap for i in range(NUM_VEHICLES)]
    DISTANCE_CONSTRAINT = distance_constraint_int

    if not soft_distance_constrint_int:
        SOFT_DISTANCE_CONSTRAINT = int(DISTANCE_CONSTRAINT * 0.75)
    else:
        SOFT_DISTANCE_CONSTRAINT = distance_constraint_int

    SOFT_DISTANCE_PENALTY = soft_distance_penalty
    MAX_SEARCH_SECONDS = max_search_seconds

    manager = pywrapcp.RoutingIndexManager(NUM_NODES, NUM_VEHICLES, depot_index)

    def matrix_callback(i: int, j: int):
        """index of from (i) and to (j)"""
        node_i = manager.IndexToNode(i)
        node_j = manager.IndexToNode(j)
        distance = DISTANCE_MATRIX[node_i][node_j]

        return distance

    def demand_callback(i: int):
        """capacity constraint"""
        demand = DEMAND[manager.IndexToNode(i)]

        return demand

    model = pywrapcp.RoutingModel(manager)

    # distance constraints
    callback_id = model.RegisterTransitCallback(matrix_callback)
    model.SetArcCostEvaluatorOfAllVehicles(callback_id)
    model.AddDimensionWithVehicleCapacity(
        callback_id,
        0,  # 0 slack
        [distance_constraint_int for i in range(NUM_VEHICLES)],
        True,  # start to zero
        "Distance",
    )

    # demand constraint setup
    model.AddDimensionWithVehicleCapacity(
        # function which return the load at each location (cf. cvrp.py example)
        model.RegisterUnaryTransitCallback(demand_callback),
        0,  # null capacity slack
        [cap for cap in VEHICLES],  # vehicle maximum capacity
        True,  # start cumul to zero
        "Capacity",
    )

    dst_dim = model.GetDimensionOrDie("Distance")
    for i in range(manager.GetNumberOfVehicles()):
        end_idx = model.End(i)
        dst_dim.SetCumulVarSoftUpperBound(
            end_idx, SOFT_DISTANCE_CONSTRAINT, SOFT_DISTANCE_PENALTY
        )

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    search_parameters.time_limit.seconds = MAX_SEARCH_SECONDS

    assignment = model.SolveWithParameters(search_parameters)

    if assignment:

        STOP_TYPE = Tuple[int, float, float, int, float]
        STOP = namedtuple("Stop", ["idx", "lat", "lon", "demand", "dist"])

        solution = []
        for _route_number in range(model.vehicles()):
            route = []
            idx = model.Start(_route_number)

            if model.IsEnd(assignment.Value(model.NextVar(idx))):
                continue

            else:
                prev_node_index = manager.IndexToNode(idx)

                while True:

                    # TODO: time_var = time_dimension.CumulVar(order)
                    node_index = manager.IndexToNode(idx)
                    lat = NODES[node_index].lat
                    lon = NODES[node_index].lon

                    demand = DEMAND[node_index]
                    dist = DISTANCE_MATRIX[prev_node_index][node_index]

                    route.append(STOP(node_index, lat, lon, demand, dist))

                    if model.IsEnd(idx):
                        break

                    prev_node = node_index
                    idx = assignment.Value(model.NextVar(idx))

            solution.append(route)

        return solution


def visualize_solution(solution: "Solution") -> None:
    # base
    lats = []
    lons = []
    text = []

    # lines
    lat_paths = []
    lon_paths = []
    for i, r in enumerate(solution):
        for j, s in enumerate(r):
            lats.append(s.lat)
            lons.append(s.lon)
            text.append(f"demand: {r[j].demand}")

            if j < len(r) - 1:
                lat_paths.append([s.lat, r[j + 1].lat])
                lon_paths.append([s.lon, r[j + 1].lon])

    fig = go.Figure()

    fig.add_trace(
        go.Scattergeo(
            locationmode="USA-states",
            lat=lats,
            lon=lons,
            hoverinfo="text",
            text=text,
            mode="markers",
            marker=dict(
                size=5,
                color="rgb(255, 0, 0)",
                line=dict(width=3, color="rgba(68, 68, 68, 0)"),
            ),
        )
    )

    for i in range(len(lat_paths)):
        fig.add_trace(
            go.Scattergeo(
                locationmode="USA-states",
                lat=[lat_paths[i][0], lat_paths[i][1]],
                lon=[lon_paths[i][0], lon_paths[i][1]],
                mode="lines",
                line=dict(width=1, color="red"),
                # opacity = float(df_flight_paths['cnt'][i]) / float(df_flight_paths['cnt'].max()),
            )
        )

    fig.update_layout(
        title_text="",
        showlegend=False,
        template="plotly_dark",
        geo=dict(
            scope="north america",
            projection_type="azimuthal equal area",
            showland=True,
            landcolor="rgb(243, 243, 243)",
            countrycolor="rgb(204, 204, 204)",
        ),
    )

    fig.show()