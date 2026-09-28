from __future__ import annotations

import pytest
from player_core import wave_stack
from player_core.robot_hand import RobotHandState

from origenerator import motion_engine
from origenerator.motion_engine import Motion


def _cruising_held_down() -> Motion:
    motion = Motion(state=RobotHandState(playing=True, amplitude=100, speed=90, max_intensity=30))
    motion_engine.enable_cruise_control(motion)
    motion_engine.tick_cruise_control(motion, 1.0)
    motion_engine.tick_cruise_control(motion, 1.05)
    return motion


def test_a_cruising_motion_held_down_by_its_max_intensity_is_sent_the_stack_it_leaves():
    motion = _cruising_held_down()

    assert motion_engine.position(motion) == pytest.approx(
        wave_stack.position(motion.cruise.stack, motion.clock, max_intensity=30))
    assert motion_engine.position_ahead(motion, 0.04) == pytest.approx(
        wave_stack.position_ahead(motion.cruise.stack, motion.clock, 0.04, max_intensity=30))


def test_a_cruising_motion_held_down_by_its_max_intensity_is_drawn_as_the_stack_it_leaves():
    motion = _cruising_held_down()

    assert motion_engine.trace_window(motion, 80, 12.0) == wave_stack.trace_window(
        motion.cruise.stack, motion.clock, 80, 12.0, max_intensity=30)

