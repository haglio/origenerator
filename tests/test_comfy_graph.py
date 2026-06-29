from origenerator.comfy_graph import clip_prompt_nodes, conditioning_node, follow


def test_follow_resolves_link_else_none():
    graph = {"2": {"class_type": "CLIPTextEncode", "inputs": {"text": "hi"}}}
    assert follow(graph, ["2", 0])["inputs"]["text"] == "hi"
    assert follow(graph, None) is None
    assert follow(graph, "2") is None  # not a link


def test_conditioning_node_finds_wan_node():
    graph = {
        "1": {"class_type": "CLIPTextEncode", "inputs": {}},
        "2": {"class_type": "WanFirstLastFrameToVideo", "inputs": {}},
    }
    assert conditioning_node(graph) is graph["2"]
    assert conditioning_node({"1": {"class_type": "KSampler", "inputs": {}}}) is None


def test_clip_prompt_nodes_structural_via_conditioning():
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"}},
        "5": {"class_type": "WanImageToVideo",
              "inputs": {"positive": ["2", 0], "negative": ["3", 0]}},
    }
    pos, neg = clip_prompt_nodes(graph)
    assert pos["inputs"]["text"] == "pos"
    assert neg["inputs"]["text"] == "neg"


def test_clip_prompt_nodes_falls_back_to_titles():
    graph = {
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "pos"},
              "_meta": {"title": "CLIP Text Encode (Positive Prompt)"}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "neg"},
              "_meta": {"title": "CLIP Text Encode (Negative Prompt)"}},
    }
    pos, neg = clip_prompt_nodes(graph)
    assert pos["inputs"]["text"] == "pos"
    assert neg["inputs"]["text"] == "neg"
