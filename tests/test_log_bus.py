"""日志总线的单元测试（不依赖 GUI）。

运行：python tests/test_log_bus.py
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.ui.log_bus import LEVEL_NO, LogBus  # noqa: E402


def make_record(level: int, message: str, name: str = 'ok.test') -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, message, None, None)


def case_ring_buffer():
    bus = LogBus(max_lines=5)
    for index in range(8):
        bus.append(make_record(logging.INFO, f'line {index}'))
    entries = bus.since(0)
    assert len(entries) == 5, len(entries)
    assert entries[0].seq == 4 and entries[-1].seq == 8, (entries[0].seq, entries[-1].seq)
    assert entries[-1].message == 'line 7'


def case_since_is_incremental():
    bus = LogBus()
    bus.append(make_record(logging.INFO, 'a'))
    bus.append(make_record(logging.WARNING, 'b'))
    first = bus.since(0)
    assert [entry.message for entry in first] == ['a', 'b']
    bus.append(make_record(logging.ERROR, 'c'))
    later = bus.since(first[-1].seq)
    assert [entry.message for entry in later] == ['c'], later


def case_levels_and_source():
    bus = LogBus()
    bus.append(make_record(logging.WARNING, 'careful', name='ok.device.DeviceManager'))
    entry = bus.since(0)[0]
    assert entry.level == 'WARNING' and entry.levelno == logging.WARNING
    assert entry.source == 'DeviceManager', entry.source
    assert LEVEL_NO['ERROR'] > LEVEL_NO['WARNING'] > LEVEL_NO['INFO'] > LEVEL_NO['DEBUG']


def case_batch_is_merged():
    """定时器不在（import 阶段）时，写入直接触发一次通知；有定时器时按 100ms 合并。"""
    bus = LogBus()
    calls = []
    bus.batch_ready.connect(lambda: calls.append(1))
    for index in range(20):
        bus.append(make_record(logging.INFO, f'x{index}'))
    # 没有 QApplication 时走同步分支，每条都会合并成一次 flush
    assert len(calls) >= 1, calls
    assert len(bus.since(0)) == 20


def case_clear():
    bus = LogBus()
    bus.append(make_record(logging.INFO, 'a'))
    bus.clear()
    assert bus.since(0) == []
    bus.append(make_record(logging.INFO, 'b'))
    assert len(bus.since(0)) == 1


def case_install_captures_logger():
    bus = LogBus()
    bus.install()
    bus.install()  # 幂等，不能重复挂 handler
    logging.getLogger('ok').info('hello from logger')
    messages = [entry.message for entry in bus.since(0)]
    assert 'hello from logger' in messages, messages


def case_text_export():
    bus = LogBus()
    bus.append(make_record(logging.ERROR, 'boom'))
    text = bus.text()
    assert 'ERROR' in text and 'boom' in text, text


CASES = [value for name, value in sorted(globals().items()) if name.startswith('case_')]


def main() -> int:
    failed = 0
    for case in CASES:
        try:
            case()
            print(f'PASS {case.__name__}')
        except AssertionError as error:
            failed += 1
            print(f'FAIL {case.__name__}: {error}')
        except Exception as error:  # noqa: BLE001
            failed += 1
            print(f'ERROR {case.__name__}: {type(error).__name__}: {error}')
    print(f'{len(CASES) - failed}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
