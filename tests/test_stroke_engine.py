"""The stroke engine — speed mapping, knob clamps, phase advance, positions."""

import pytest

from origenerator import stroke_engine
from origenerator.stroke_engine import StrokeShape, StrokeState


def test_speed_maps_exponentially_between_the_bpm_endpoints():
    assert stroke_engine.bpm_for_speed(stroke_engine.MIN_SPEED) == pytest.approx(
        stroke_engine.MIN_BPM)
    assert stroke_engine.bpm_for_speed(stroke_engine.MAX_SPEED) == pytest.approx(
        stroke_engine.MAX_BPM)
    # Exponential, not linear: the midpoint sits at the geometric mean.
    mid = stroke_engine.bpm_for_speed((stroke_engine.MIN_SPEED + stroke_engine.MAX_SPEED) // 2)
    assert mid == pytest.approx(
        (stroke_engine.MIN_BPM * stroke_engine.MAX_BPM) ** 0.5, rel=0.05)


def test_speed_adjustments_clamp_to_the_dial():
    state = StrokeState(speed=95)
    stroke_engine.adjust_speed(state, 50)
    assert state.speed == stroke_engine.MAX_SPEED
    stroke_engine.adjust_speed(state, -500)
    assert state.speed == stroke_engine.MIN_SPEED


def test_amplitude_clamps_to_the_axis():
    state = StrokeState()
    stroke_engine.adjust_amplitude(state, 50)
    assert state.amplitude == 100
    stroke_engine.adjust_amplitude(state, -150)
    assert state.amplitude == 0


def test_the_effective_center_is_pulled_in_so_the_sweep_fits():
    # A full-length stroke can only pivot around the middle...
    assert StrokeState(amplitude=100, intended_center=90).center == 50
    # ...while a half-length one can sit anywhere its half-range allows.
    assert StrokeState(amplitude=50, intended_center=90).center == 75
    assert StrokeState(amplitude=50, intended_center=50).center == 50


def test_center_nudges_stop_at_the_reachable_edge():
    state = StrokeState(amplitude=50, intended_center=70)
    stroke_engine.adjust_center(state, 20)   # would overshoot: lands on the limit
    assert state.intended_center == 75
    stroke_engine.adjust_center(state, 5)    # already at the limit: stays put
    assert state.intended_center == 75
    stroke_engine.adjust_center(state, -5)   # stepping back in is always allowed
    assert state.intended_center == 70


def test_shapes_cycle_through_all_and_wrap():
    state = StrokeState()
    seen = [state.shape]
    for _ in range(len(StrokeShape)):
        stroke_engine.cycle_shape(state)
        seen.append(state.shape)
    assert seen[-1] == seen[0]                      # wrapped home
    assert set(seen) == set(StrokeShape)            # visited every shape


def test_advance_moves_the_phase_by_time_at_the_current_speed():
    state = StrokeState(speed=50)
    stroke_engine.advance(state, 0.1)
    assert state.phase == pytest.approx(0.1 * state.bpm / 60.0)


def test_advance_wraps_and_never_slingshots_after_a_stall():
    state = StrokeState()
    stroke_engine.advance(state, 60.0)  # a whole stalled minute...
    capped = StrokeState()
    stroke_engine.advance(capped, 0.1)  # ...advances no further than one tick's cap
    assert state.phase == pytest.approx(capped.phase)
    assert 0.0 <= state.phase < 1.0


def test_positions_sweep_the_amplitude_around_the_center():
    state = StrokeState(amplitude=50, intended_center=50)
    state.phase = 0.0
    assert stroke_engine.position(state) == pytest.approx(25.0)   # bottom of the sweep
    state.phase = 0.5
    assert stroke_engine.position(state) == pytest.approx(75.0)   # top of the sweep


def test_every_shape_stays_within_its_sweep():
    for shape in StrokeShape:
        state = StrokeState(amplitude=60, intended_center=30, shape=shape)
        for i in range(20):
            state.phase = i / 20
            low = state.center - 30
            high = state.center + 30
            assert low - 1e-6 <= stroke_engine.position(state) <= high + 1e-6


def test_the_sawtooth_peaks_early_then_draws_back_down():
    state = StrokeState(shape=StrokeShape.SAWTOOTH)
    state.phase = 0.3
    assert stroke_engine.position(state) == pytest.approx(100.0)  # quick rise tops out
    state.phase = 0.65  # halfway down the long draw
    assert stroke_engine.position(state) == pytest.approx(50.0)
