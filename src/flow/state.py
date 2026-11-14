"""守卫式驱动器：状态 + 转移规则。"""

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union

from src.flow.flow import run_step
from src.flow.steps import FlowConfigError, FlowFailed, Guard, Step

DEFAULT_MAX_TRANSITIONS = 50

Action = Union[Callable[[Any], Any], Step, Sequence[Step], None]


@dataclass
class State:
    """状态机的一个状态。

    Attributes:
      name: 状态名，转移目标用它引用。
      goto: 进入状态前先导航到的页面 id。
      do: 进入状态后执行的动作：函数、单个 ``Step`` 或 ``Step`` 列表。
      transitions: ``(guard, target)`` 序列，按顺序取第一个为真的分支。
    """

    name: str
    goto: Optional[str] = None
    do: Action = None
    transitions: Sequence[Guard] = field(default_factory=tuple)

    def __post_init__(self):
        if not str(self.name or '').strip():
            raise FlowConfigError('State 需要非空的 name')
        self.transitions = tuple(self.transitions or ())


class StateMachine:
    """带守卫转移的状态机。

    Attributes:
      states: 状态名到状态的映射。
      start: 起始状态名，缺省取第一个状态。
      max_transitions: 允许的最大转移次数，防止死循环。
    """

    def __init__(self, states: Mapping[str, State], *, start: Optional[str] = None,
                 max_transitions: int = DEFAULT_MAX_TRANSITIONS):
        if not states:
            raise FlowConfigError('StateMachine 至少需要一个状态')
        self.states = dict(states)
        self.start = start or next(iter(self.states))
        self.max_transitions = int(max_transitions)
        if self.start not in self.states:
            raise FlowConfigError(f'起始状态不存在: {self.start}')
        if self.max_transitions <= 0:
            raise FlowConfigError('max_transitions 必须为正')
        for state in self.states.values():
            for _, target in state.transitions:
                if target not in self.states:
                    raise FlowConfigError(
                        f'状态 {state.name} 转移到未知状态 {target}')

    def run(self, task: Any) -> str:
        """驱动状态机直到没有守卫命中。

        Args:
          task: 任务实例。

        Returns:
          结束时所处的状态名。

        Raises:
          FlowFailed: 转移次数超过 ``max_transitions``。
        """
        current = self.start
        transitions = 0
        snapshot = _snapshot(task)
        while True:
            state = self.states[current]
            self._enter(task, state)
            target = self._next_state(task, state)
            if target is None:
                task.log_info(f'flow: 状态机结束于 {current}')
                return current
            transitions += 1
            if transitions > self.max_transitions:
                raise FlowFailed(
                    f'状态机超过 {self.max_transitions} 次转移，最后停在 {current}')
            current_snapshot = _snapshot(task)
            if target == current and current_snapshot == snapshot:
                task.log_warning(f'flow: {current} 没有进展，仍在原地转移')
            snapshot = current_snapshot
            current = target

    def _enter(self, task: Any, state: State) -> None:
        if state.goto:
            task.ensure_page(state.goto)
        self._run_do(task, state)

    def _run_do(self, task: Any, state: State) -> None:
        action = state.do
        if action is None:
            return
        if isinstance(action, Step):
            run_step(task, action)
        elif isinstance(action, (list, tuple)):
            for step in action:
                if not isinstance(step, Step):
                    raise FlowConfigError(f'状态 {state.name} 的 do 只接受 Step')
                run_step(task, step)
        elif callable(action):
            result = action(task)
            if result is not None:
                task.data[state.name] = result
        else:
            raise FlowConfigError(f'状态 {state.name} 的 do 类型不受支持')

    def _next_state(self, task: Any, state: State) -> Optional[str]:
        for guard, target in state.transitions:
            if guard(task):
                return target
        return None


def _snapshot(task: Any) -> str:
    """任务数据的粗略快照，用于发现原地打转。"""
    data = getattr(task, 'data', None) or {}
    return repr(sorted((key, repr(value)) for key, value in data.items()))
