"""编排层：``Flow`` 线性步骤、``StateMachine`` 守卫状态机与输入动作。"""

from src.flow.actions import (DoubleTap, Drag, KeyCombo, KeyPress, LongPress,
                              RightTap, Swipe, Tap, TextInput)
from src.flow.flow import DEFAULT_WAIT_TIMEOUT, Flow, run_step
from src.flow.state import DEFAULT_MAX_TRANSITIONS, State, StateMachine
from src.flow.steps import (FlowConfigError, FlowError, FlowFailed, Step,
                            Transition)

__all__ = [
    'DEFAULT_MAX_TRANSITIONS',
    'DEFAULT_WAIT_TIMEOUT',
    'DoubleTap',
    'Drag',
    'Flow',
    'FlowConfigError',
    'FlowError',
    'FlowFailed',
    'KeyCombo',
    'KeyPress',
    'LongPress',
    'RightTap',
    'State',
    'StateMachine',
    'Step',
    'Swipe',
    'Tap',
    'TextInput',
    'Transition',
    'run_step',
]
