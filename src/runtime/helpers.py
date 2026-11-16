"""被调用任务的注册表与实例化入口。

辅助任务只实例化、不进入 GUI/MCP 的任务列表，调用方按名字取用。
"""

import importlib
from typing import Any, Dict, Optional, Type

# name -> class
_CLASSES: Dict[str, Type] = {}
# name -> instance
_INSTANCES: Dict[str, Any] = {}


def _split(target: str) -> str:
    return target.split(':')[0]


def resolve(target: str, *, sources=None) -> Type:
    """按名字或 ``module:Class`` 找到任务类。

    Args:
      target: 已在注册表里的名字，或 ``module:Class`` 字符串。
      sources: 可选的候选字符串列表，缺省读 ``config['helper_tasks']``。

    Returns:
      任务类。

    Raises:
      LookupError: 名字不在注册表，也没有对应的配置项。
    """
    if target in _CLASSES:
        return _CLASSES[target]
    for entry in sources or ():
        module_name, _, class_name = entry.partition(':')
        if class_name and (class_name == target or entry == target):
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
            _CLASSES[class_name] = cls
            return cls
    raise LookupError(f'未注册的辅助任务 {target!r}，可用 {sorted(_CLASSES)}')


def register(name: str, cls: Type) -> None:
    """把任务类登记到注册表。

    Args:
      name: 调用时使用的名字。
      cls: 任务类。
    """
    _CLASSES[name] = cls


def instance(name: str, task) -> Any:
    """按名字取得（或创建并缓存）任务实例。

    Args:
      name: 注册表里的名字。
      task: 调用方任务，用于取得 executor/app。

    Returns:
      任务实例。
    """
    if name in _INSTANCES:
        return _INSTANCES[name]
    cls = resolve(name, sources=getattr(task, 'helper_sources', None))
    created = cls(executor=task.executor, app=task.app)
    _INSTANCES[name] = created
    return created


def reset() -> None:
    """清空注册表与实例缓存（测试用）。"""
    _CLASSES.clear()
    _INSTANCES.clear()
