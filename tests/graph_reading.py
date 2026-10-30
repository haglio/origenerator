from __future__ import annotations


def read_in_order(payload: dict, node_id: str) -> list[str]:
    node = payload[node_id]
    if node["class_type"] == "CLIPTextEncode":
        return [node["inputs"]["text"]]
    return (read_in_order(payload, node["inputs"]["conditioning_to"][0])
            + read_in_order(payload, node["inputs"]["conditioning_from"][0]))
