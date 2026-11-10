from __future__ import annotations

_VIDEO_STEP_SECONDS_PER_FRAME = 0.5
_AUDIO_STEP_SECONDS_PER_SECOND = 0.03
_IMAGE_STEP_SECONDS = 0.5
_DETAIL_STEP_SECONDS = 0.15

_VIDEO_LATENT_SHAPE = ("length", "width", "height", "batch_size")


def _ksampler_steps(inputs: dict) -> int:
    return int(inputs.get("steps", 0))


def _ksampler_advanced_steps(inputs: dict) -> int:
    steps = int(inputs.get("steps", 0))
    start = int(inputs.get("start_at_step", 0))
    end = int(inputs.get("end_at_step", steps))
    return max(0, min(end, steps) - start)


def _detailer_steps(inputs: dict) -> int:
    return int(inputs.get("steps", 0)) * max(1, int(inputs.get("cycle", 1)))


_SAMPLER_STEPS = {
    "KSampler": _ksampler_steps,
    "KSamplerAdvanced": _ksampler_advanced_steps,
    "HunyuanFoleySampler": _ksampler_steps,
    "DetailerForEach": _detailer_steps,
}


def _literal(value, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) else fallback


def _video_latent_frames(payload: dict) -> int:
    frames = 0
    for node in payload.values():
        inputs = node.get("inputs", {})
        if all(key in inputs for key in _VIDEO_LATENT_SHAPE):
            frames = max(frames, int(_literal(inputs["length"], 0)))
    return frames


def _step_seconds(class_type: str, inputs: dict, frames: int) -> float:
    if class_type == "HunyuanFoleySampler":
        return _AUDIO_STEP_SECONDS_PER_SECOND * max(1.0, _literal(inputs.get("duration"), 1.0))
    if class_type == "DetailerForEach":
        return _DETAIL_STEP_SECONDS
    if frames:
        return _VIDEO_STEP_SECONDS_PER_FRAME * frames
    return _IMAGE_STEP_SECONDS


_STAGE_NAMES = {
    "CLIPLoader": "Loading models",
    "DualCLIPLoader": "Loading models",
    "CLIPVisionLoader": "Loading models",
    "VAELoader": "Loading models",
    "UNETLoader": "Loading models",
    "UnetLoaderGGUF": "Loading models",
    "CheckpointLoaderSimple": "Loading models",
    "ControlNetLoader": "Loading models",
    "UpscaleModelLoader": "Loading models",
    "LoraLoaderModelOnly": "Loading models",
    "HunyuanModelLoader": "Loading models",
    "HunyuanDependenciesLoader": "Loading models",
    "DownloadAndLoadDepthAnythingV2Model": "Loading models",
    "UltralyticsDetectorProvider": "Loading models",
    "CLIPTextEncode": "Reading the prompt",
    "LoadImage": "Loading the image",
    "CLIPVisionEncode": "Reading the image",
    "DepthAnything_V2": "Reading the depth",
    "BboxDetectorSEGS": "Finding the parts",
    "WanImageToVideo": "Preparing the clip",
    "WanFirstLastFrameToVideo": "Preparing the clip",
    "EmptyHunyuanLatentVideo": "Preparing the clip",
    "VAEEncode": "Preparing",
    "ImageUpscaleWithModel": "Upscaling",
    "VAEDecode": "Decoding frames",
    "RIFE VFI": "Smoothing the motion",
    "VHS_VideoCombine": "Writing the video",
    "SaveImage": "Saving the image",
}


def _sampler_stage(class_type: str, inputs: dict, title: str = "") -> str:
    if class_type == "HunyuanFoleySampler":
        return "Audio"
    if class_type == "DetailerForEach":
        return title or "Detail fix"
    if class_type == "KSamplerAdvanced":
        return "First pass" if inputs.get("add_noise") == "enable" else "Second pass"
    return "Enhance" if _literal(inputs.get("denoise"), 1.0) < 1.0 else "Render"


def stage_names(payload: dict) -> dict[str, str]:
    names = {}
    for node_id, node in payload.items():
        class_type = node.get("class_type")
        if class_type in _SAMPLER_STEPS:
            names[str(node_id)] = _sampler_stage(class_type, node.get("inputs", {}),
                                                 node.get("_meta", {}).get("title", ""))
        elif class_type in _STAGE_NAMES:
            names[str(node_id)] = _STAGE_NAMES[class_type]
    return names


def sampler_costs(payload: dict) -> dict[str, tuple[int, float]]:
    frames = _video_latent_frames(payload)
    costs = {}
    for node_id, node in payload.items():
        sizer = _SAMPLER_STEPS.get(node.get("class_type"))
        if sizer is None:
            continue
        inputs = node.get("inputs", {})
        costs[str(node_id)] = (
            sizer(inputs), _step_seconds(node["class_type"], inputs, frames),
        )
    return costs


def expected_sampling_seconds(payload: dict) -> int:
    return round(sum(steps * cost for steps, cost in sampler_costs(payload).values()))


def expected_pass_count(payload: dict) -> int:
    return len(sampler_costs(payload))


SAME_PASS_AS_BEFORE = None


class ProgressTracker:
    @classmethod
    def for_payload(cls, payload: dict) -> ProgressTracker:
        return cls(
            expected_sampling_seconds(payload),
            expected_pass_count(payload),
            {node_id: cost for node_id, (_, cost) in sampler_costs(payload).items()},
        )

    def __init__(self, total_seconds: float, passes: int = 1,
                 step_seconds: dict[str, float] | None = None):
        self._total = float(total_seconds)
        self._passes = max(1, passes)
        self._step_seconds = dict(step_seconds or {})
        self._unbudgeted = min(self._step_seconds.values(), default=1.0)
        self._banked = 0.0
        self._stage_max = 0
        self._stage_seconds = self._unbudgeted
        self._last_value = None
        self._node = None
        self._pass_index = 0

    def snapshot(self) -> dict:
        return {
            "total": self._total,
            "banked": self._banked,
            "stage_max": self._stage_max,
            "stage_seconds": self._stage_seconds,
            "last_value": self._last_value,
            "node": self._node,
            "passes": self._passes,
            "pass_index": self._pass_index,
        }

    def restore(self, snapshot: dict) -> None:
        if "stage_seconds" not in snapshot:
            return
        self._total = float(snapshot.get("total", self._total))
        self._banked = float(snapshot.get("banked", 0.0))
        self._stage_max = int(snapshot.get("stage_max", 0))
        self._stage_seconds = float(snapshot.get("stage_seconds", self._unbudgeted))
        last_value = snapshot.get("last_value")
        self._last_value = None if last_value is None else int(last_value)
        self._node = snapshot.get("node")
        self._passes = max(1, int(snapshot.get("passes", self._passes)))
        began = 2 if self._banked else (1 if self._last_value is not None else 0)
        self._pass_index = int(snapshot.get("pass_index", began))

    def current(self) -> tuple[int, int]:
        if self._total <= 0:
            return 0, 0
        return self._reading(self._last_value or 0)

    def current_pass(self) -> tuple[int, int] | None:
        if self._total <= 0 or self._pass_index == 0:
            return None
        if self._passes <= 1 and self._pass_index <= 1:
            return None
        return min(self._last_value or 0, self._stage_max), self._stage_max

    def update(self, value: int, max_val: int,
               node: str | None = SAME_PASS_AS_BEFORE) -> tuple[int, int]:
        if self._total <= 0:
            return value, max_val
        if self._last_value is None:
            self._pass_index = 1
            self._begin_pass(node)
        elif self._is_new_pass(value, node):
            self._banked += self._stage_max * self._stage_seconds
            self._stage_max = 0
            self._pass_index += 1
            self._begin_pass(node)
        self._last_value = value
        self._stage_max = max(self._stage_max, max_val)
        self._total = max(self._total,
                          self._banked + self._stage_max * self._stage_seconds)
        return self._reading(value)

    def _is_new_pass(self, value: int, node: str | None) -> bool:
        if node is not SAME_PASS_AS_BEFORE and self._node is not None and node != self._node:
            return True
        return value < self._last_value

    def _begin_pass(self, node: str | None) -> None:
        self._node = node
        self._stage_seconds = self._step_seconds.get(node, self._unbudgeted)

    def _reading(self, value: int) -> tuple[int, int]:
        done = min(self._banked + value * self._stage_seconds, self._total)
        return round(done), max(1, round(self._total))
