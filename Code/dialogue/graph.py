def load_graph(data, source="graph"):
    """Validate a dialogue graph and return it. Nodes are data, not classes."""
    if not isinstance(data, dict):
        raise ValueError(f"{source}: graph must be an object")
    graph_id = data.get("id")
    if not isinstance(graph_id, str) or not graph_id:
        raise ValueError(f"{source}: id must be a non-empty string")
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        raise ValueError(f"{source}: nodes must be a non-empty object")
    start = data.get("start")
    if start not in nodes:
        raise ValueError(f"{source}: start {start!r} is not a node")
    for node_id, node in nodes.items():
        _validate_node(source, node_id, node, nodes)
    return data


def _validate_node(source, node_id, node, nodes):
    if not isinstance(node, dict):
        raise ValueError(f"{source}: node {node_id} must be an object")
    if node.get("end") is True:
        return
    if "choices" in node:
        choices = node["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError(f"{source}: node {node_id} choices must be a non-empty list")
        for index, choice in enumerate(choices):
            if not isinstance(choice, dict) or not isinstance(choice.get("text"), str) or not choice["text"]:
                raise ValueError(f"{source}: node {node_id} choice {index} needs text")
            _check_next(source, node_id, choice.get("next"), nodes)
        _check_next(source, node_id, node.get("next"), nodes)
        return
    if not isinstance(node.get("text"), str):
        raise ValueError(f"{source}: node {node_id} needs text")
    _check_next(source, node_id, node.get("next"), nodes)


def _check_next(source, node_id, nxt, nodes):
    if nxt is not None and nxt not in nodes:
        raise ValueError(f"{source}: node {node_id} points at missing node {nxt!r}")
