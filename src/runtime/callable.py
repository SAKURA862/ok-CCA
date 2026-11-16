"""任务调用任务：让一个任务同步调用另一个任务并拿到返回值。

被调用的任务继承 :class:`CallableTask`，实现 ``execute(**kwargs)``；
基类的 ``run()`` 负责参数绑定、缺参报错与结果保存，因此它既能被
``call_task`` 调用，也能单独放进 GUI 里跑（无参调用）。
"""

import inspect
from typing import Any, Callable, Dict, Optional

from src.tasks.MyBaseTask import MyBaseTask

MAX_CALL_DEPTH = 3


class TaskCallError(RuntimeError):
    """任务调用失败：参数不匹配、重入过深或内层任务抛错。"""


class CallableTask(MyBaseTask):
    """可被其它任务调用的任务。

    Attributes:
      result: ``execute`` 的返回值，供调用方读取。
      call_params: ``run()`` 时使用的关键字参数，由 ``call_task`` 注入。
    """

    # 内层任务不重复走启动层，由外层负责
    SKIP_GAME_BOOTSTRAP = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.result = None
        self.call_params: Dict[str, Any] = {}

    def execute(self, **kwargs):
        """子类实现的实际逻辑。

        Args:
          **kwargs: 调用方传入的参数。

        Returns:
          任意结果，会保存到 ``self.result`` 并返回给调用方。
        """
        raise NotImplementedError(f'{type(self).__name__} 需要实现 execute()')

    def run(self):
        """绑定参数后执行 ``execute``，结果写入 ``self.result``。"""
        self.ensure_game_ready()
        params = self.bind_params(self.call_params)
        self.result = self.execute(**params)
        return self.result

    def bind_params(self, values: Dict[str, Any]) -> Dict[str, Any]:
        """按 ``execute`` 的签名检查并裁剪参数。

        Args:
          values: 调用方给的关键字参数。

        Returns:
          可直接传给 ``execute`` 的参数字典。

        Raises:
          TaskCallError: 缺少必填参数或出现未知参数。
        """
        signature = inspect.signature(self.execute)
        accepted = {name for name, param in signature.parameters.items()
                    if param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)}
        unknown = sorted(set(values) - accepted)
        if unknown:
            raise TaskCallError(
                f'{type(self).__name__}.execute() 不接受参数 {unknown}，'
                f'可用参数 {sorted(accepted)}')
        missing = [name for name, param in signature.parameters.items()
                   if name in accepted and param.default is param.empty
                   and name not in values]
        if missing:
            raise TaskCallError(
                f'{type(self).__name__}.execute() 缺少参数 {missing}')
        return {name: value for name, value in values.items() if name in accepted}


def callable_task(func: Optional[Callable] = None, *, name: Optional[str] = None):
    """把普通函数包装成 ``CallableTask`` 子类。

    Args:
      func: 被包装的函数，第一个参数是任务实例。
      name: 任务类名，缺省由函数名生成。

    Returns:
      任务类；也可以作为不带参数的装饰器使用。
    """
    def wrap(target: Callable) -> type:
        class GeneratedTask(CallableTask):
            def execute(self, **kwargs):
                return target(self, **kwargs)

        # 让参数校验看到原函数的签名（绑定方法会自动去掉第一个参数）
        GeneratedTask.execute.__signature__ = inspect.signature(target)

        GeneratedTask.__name__ = name or ''.join(
            part.capitalize() for part in target.__name__.split('_')) + 'Task'
        GeneratedTask.__qualname__ = GeneratedTask.__name__
        GeneratedTask.__doc__ = target.__doc__
        return GeneratedTask

    return wrap(func) if func is not None else wrap
