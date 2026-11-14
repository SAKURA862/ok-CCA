"""页面图导航：模型校验（T1）、定位（T2）、寻路（T3）的离线测试。

运行：``python tests/test_nav.py``
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.nav.actions import ActionError, ActionExecutor  # noqa: E402
from src.nav.locator import Located, Locator  # noqa: E402
from src.nav.model import (  # noqa: E402
    ACTION_CLICK_POINT,
    ACTION_CLICK_TEMPLATE,
    ACTION_KEY,
    Action,
    NavConfigError,
    NavError,
    NavGraph,
    NavUnknownPage,
    load_graph,
)
from src.nav import registry  # noqa: E402
from src.nav.navigator import NavCache, NavStepFailed, Navigator  # noqa: E402
from src.nav.router import NavUnreachable, edge_cost, find_path  # noqa: E402
from src.tasks.MyBaseTask import MyBaseTask  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name, func):
    try:
        func()
    except AssertionError as exc:
        results.append((name, False, str(exc)))
    except Exception as exc:  # noqa: BLE001
        results.append((name, False, f'{type(exc).__name__}: {exc}'))
    else:
        results.append((name, True, ''))


def expect_error(func, needle, error_type=NavConfigError):
    try:
        func()
    except error_type as exc:
        text = str(exc)
        assert needle in text, f'错误信息里没有 {needle!r}: {text}'
        return text
    raise AssertionError(f'应当抛出 {error_type.__name__}，但没有')


# --------------------------------------------------------------------------- 夹具

def base_graph(**overrides):
    data = {
        'pages': [
            {'id': 'home', 'name': '大厅', 'anchors': ['nav_home_tab_home'], 'is_home': True},
            {'id': 'arena', 'name': '镜像竞技', 'anchors': ['nav_arena_title'], 'tags': ['pvp']},
        ],
        'edges': [
            {'from': 'home', 'to': 'arena',
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'nav_home_arena_button',
                        'roi': [0.1, 0.2, 0.5, 0.6]}},
            {'from': 'arena', 'to': 'home',
             'action': {'type': ACTION_KEY, 'key': 'esc'}, 'timeout': 3.0, 'cost': 2.0},
        ],
    }
    data.update(overrides)
    return data


def chain_graph(costs, *, pages=None):
    """构造 home -> p1 -> p2 ... -> goal 的链，返回 (graph, 边 key 列表)。"""
    ids = pages or ['home'] + [f'p{index}' for index in range(1, len(costs))] + ['goal']
    pages_data = [{'id': ids[0], 'name': ids[0], 'anchors': [f'{ids[0]}_a'], 'is_home': True}]
    pages_data += [{'id': page_id, 'name': page_id, 'anchors': [f'{page_id}_a']} for page_id in ids[1:]]
    edges = []
    keys = []
    for index, cost in enumerate(costs):
        source, target = ids[index], ids[index + 1]
        edges.append({'from': source, 'to': target, 'cost': cost,
                      'action': {'type': ACTION_CLICK_POINT, 'point': [0.5, 0.5]}})
        keys.append(f'{source}>{target}')
    return NavGraph.from_dict({'pages': pages_data, 'edges': edges}, profile='p'), keys


# --------------------------------------------------------------------------- T1 模型

def test_load_minimal():
    graph = NavGraph.from_dict(base_graph(), profile='crosscore', source='test.json')
    assert graph.profile == 'crosscore'
    assert graph.page_ids == ('home', 'arena')
    assert graph.home.id == 'home'
    assert graph.page('arena').tags == ('pvp',)
    assert graph.has('home') and not graph.has('nope')

    edge = graph.edge_between('home', 'arena')
    assert edge is not None, '缺少 home>arena 的边'
    assert edge.action.type == ACTION_CLICK_TEMPLATE
    assert edge.action.template == 'nav_home_arena_button'
    assert edge.action.roi == (0.1, 0.2, 0.5, 0.6)
    assert edge.timeout == 8.0 and edge.retries == 1 and edge.cost == 1.0
    assert edge.key == 'home>arena'
    assert [e.target for e in graph.edges_from('home')] == ['arena']

    back = graph.edge_between('arena', 'home')
    assert back.action.type == ACTION_KEY and back.action.key == 'esc'
    assert back.timeout == 3.0 and back.cost == 2.0


def test_page_lookup_error():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    text = expect_error(lambda: graph.page('shop'), 'shop', NavUnknownPage)
    assert 'home' in text


def test_to_dict_roundtrip():
    graph = NavGraph.from_dict(base_graph(), profile='crosscore')
    again = NavGraph.from_dict(json.loads(json.dumps(graph.to_dict())), profile='crosscore')
    assert again.to_dict() == graph.to_dict()


def test_single_page_auto_home():
    graph = NavGraph.from_dict({'pages': [{'id': 'only', 'name': '唯一页', 'anchors': ['a']}]},
                               profile='p')
    assert graph.home.id == 'only', '单页图应自动把唯一页面当作家页'


def test_load_from_file():
    directory = ROOT / '.tmp'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'tiny_nav.json'
    path.write_text(json.dumps({'pages': [{'id': 'home', 'name': 'H', 'anchors': ['x']}]},
                               ensure_ascii=False), encoding='utf-8')
    graph = load_graph(path)
    assert graph.profile == 'tiny_nav', f'profile 应取文件名，实际 {graph.profile}'
    assert graph.home.id == 'home'
    path.unlink(missing_ok=True)


def test_duplicate_page_id():
    text = expect_error(
        lambda: NavGraph.from_dict({'pages': [
            {'id': 'home', 'name': 'A', 'anchors': ['a'], 'is_home': True},
            {'id': 'home', 'name': 'B', 'anchors': ['b']},
        ]}, profile='p'), 'id 重复')
    assert 'page[home]' in text


def test_missing_home():
    expect_error(lambda: NavGraph.from_dict({'pages': [
        {'id': 'a', 'name': 'A', 'anchors': ['a']},
        {'id': 'b', 'name': 'B', 'anchors': ['b']},
    ]}, profile='p'), 'is_home')


def test_two_homes():
    expect_error(lambda: NavGraph.from_dict({'pages': [
        {'id': 'a', 'name': 'A', 'anchors': ['a'], 'is_home': True},
        {'id': 'b', 'name': 'B', 'anchors': ['b'], 'is_home': True},
    ]}, profile='p'), '只能有一个 is_home')


def test_dangling_edge():
    data = base_graph()
    data['edges'][0]['to'] = 'shop'
    text = expect_error(lambda: NavGraph.from_dict(data, profile='p'), '不存在的页面')
    assert 'shop' in text


def test_duplicate_edge():
    data = base_graph()
    data['edges'].append(dict(data['edges'][0]))
    expect_error(lambda: NavGraph.from_dict(data, profile='p'), '重复定义')


def test_self_loop():
    data = base_graph()
    data['edges'][0]['to'] = 'home'
    expect_error(lambda: NavGraph.from_dict(data, profile='p'), '自环')


def test_unknown_action():
    data = base_graph()
    data['edges'][0]['action'] = {'type': 'swipe_left'}
    text = expect_error(lambda: NavGraph.from_dict(data, profile='p'), 'type 必须是')
    assert 'swipe_left' in text


def test_bad_roi():
    data = base_graph()
    data['edges'][0]['action']['roi'] = [0.5, 0.2, 0.1, 0.6]
    expect_error(lambda: NavGraph.from_dict(data, profile='p'), 'x1 < x2')

    data = base_graph()
    data['edges'][0]['action']['roi'] = [0.1, 0.2, 1.5, 0.6]
    expect_error(lambda: NavGraph.from_dict(data, profile='p'), '0-1')


def test_action_variants():
    point = Action.from_dict({'type': ACTION_CLICK_POINT, 'point': [0.25, 0.75]})
    assert point.point == (0.25, 0.75)
    assert point.to_dict() == {'type': ACTION_CLICK_POINT, 'point': [0.25, 0.75]}

    key = Action.from_dict({'type': ACTION_KEY, 'key': 'esc'})
    assert key.to_dict() == {'type': ACTION_KEY, 'key': 'esc'}

    template = Action.from_dict({'type': ACTION_CLICK_TEMPLATE, 'template': 'x'})
    assert template.roi is None
    assert template.to_dict() == {'type': ACTION_CLICK_TEMPLATE, 'template': 'x'}
    assert 'click_template(x)' in template.describe()


def test_bad_json_file():
    directory = ROOT / '.tmp'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'broken_nav.json'
    path.write_text('{"pages": [', encoding='utf-8')
    text = expect_error(lambda: load_graph(path), 'JSON 解析失败')
    assert '行' in text
    path.unlink(missing_ok=True)


def test_empty_pages():
    expect_error(lambda: NavGraph.from_dict({'pages': []}, profile='p'), '至少要有一个页面')


# --------------------------------------------------------------------------- T2 定位

def make_locator(graph, hits):
    calls: list[str] = []
    warnings: list[str] = []

    def find(template):
        calls.append(template)
        value = hits.get(template)
        if isinstance(value, Exception):
            raise value
        return value

    locator = Locator(graph, find, warn=warnings.append)
    return locator, calls, warnings


def test_locate_last_page_hit():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    locator, calls, _warn = make_locator(graph, {'nav_arena_title': 'BOX'})
    found = locator.locate(last_page='arena')
    assert found.page_id == 'arena'
    assert found.anchor == 'nav_arena_title'
    assert found.box == 'BOX'
    assert found.full_scan is False, 'last_page 命中时不应全量扫描'
    assert calls == ['nav_arena_title'], f'不应多扫，实际 {calls}'


def test_locate_falls_back_to_full_scan():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    locator, calls, _warn = make_locator(graph, {'nav_home_tab_home': 'HOME_BOX'})
    found = locator.locate(last_page='arena')
    assert found.page_id == 'home'
    assert found.full_scan is True
    # 先试 arena 的锚点，没中；再全量扫描，home 最后扫也要能扫到
    assert calls[0] == 'nav_arena_title'
    assert 'nav_home_tab_home' in calls


def test_locate_unknown_page():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    locator, _calls, _warn = make_locator(graph, {})
    text = expect_error(lambda: locator.locate(last_page='arena'), '认不出当前页面', NavUnknownPage)
    assert 'nav_arena_title' in text, '错误信息要列出试过的锚点'


def test_locate_find_error_is_miss():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    locator, _calls, warnings = make_locator(graph, {
        'nav_arena_title': RuntimeError('adb 挂了'),
        'nav_home_tab_home': 'HOME_BOX',
    })
    found = locator.locate(last_page='arena')
    assert found.page_id == 'home'
    assert warnings and 'adb 挂了' in warnings[0], f'异常应当被记录，实际 {warnings}'


def test_is_page():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    locator, calls, _warn = make_locator(graph, {'nav_arena_title': 'BOX'})
    assert locator.is_page('arena') is True
    assert locator.is_page('home') is False
    assert calls == ['nav_arena_title', 'nav_home_tab_home'], 'is_page 只验这一页'


# --------------------------------------------------------------------------- T3 寻路

def test_route_direct():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    path = find_path(graph, 'home', 'arena')
    assert path.page_ids == ('home', 'arena')
    assert len(path) == 1
    assert abs(path.cost - 1.0) < 1e-9


def test_route_same_page():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    path = find_path(graph, 'home', 'home')
    assert len(path) == 0 and path.cost == 0.0


def test_route_prefers_cheaper_multi_hop():
    graph, keys = chain_graph([5.0, 1.0, 1.0, 1.0])  # home->p1->p2->goal? 见下方边表
    # chain_graph 只有一条链，改成显式构造两条竞争路径
    graph = NavGraph.from_dict({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['h'], 'is_home': True},
            {'id': 'mid', 'name': 'M', 'anchors': ['m']},
            {'id': 'goal', 'name': 'G', 'anchors': ['g']},
        ],
        'edges': [
            {'from': 'home', 'to': 'goal', 'cost': 5.0,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'home', 'to': 'mid', 'cost': 1.0,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'mid', 'to': 'goal', 'cost': 1.0,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
        ],
    }, profile='p')
    path = find_path(graph, 'home', 'goal')
    assert path.page_ids == ('home', 'mid', 'goal'), f'应走两跳便宜路线，实际 {path.page_ids}'


def test_route_downweights_failing_edge():
    graph = NavGraph.from_dict({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['h'], 'is_home': True},
            {'id': 'mid', 'name': 'M', 'anchors': ['m']},
            {'id': 'goal', 'name': 'G', 'anchors': ['g']},
        ],
        'edges': [
            {'from': 'home', 'to': 'goal', 'cost': 1.0,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'home', 'to': 'mid', 'cost': 1.0,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'mid', 'to': 'goal', 'cost': 1.2,
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
        ],
    }, profile='p')
    assert find_path(graph, 'home', 'goal').page_ids == ('home', 'goal')

    # 直连边失败 3 次：1.0 * (1 + 0.5*3) = 2.5，两跳 2.2 更便宜
    path = find_path(graph, 'home', 'goal', fails={'home>goal': 3})
    assert path.page_ids == ('home', 'mid', 'goal'), f'失败边应被降权，实际 {path.page_ids}'
    assert edge_cost(graph.edge_between('home', 'goal'), 3) == 2.5


def test_route_disabled_edge():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    path = find_path(graph, 'arena', 'home')  # 只有 arena>home
    assert path.page_ids == ('arena', 'home')
    expect_error(lambda: find_path(graph, 'arena', 'home', disabled={'arena>home'}),
                 '找不到', NavUnreachable)


def test_route_max_hops():
    graph, _keys = chain_graph([1.0, 1.0, 1.0, 1.0, 1.0, 1.0])  # home->p1..p5->goal 共 6 跳
    path = find_path(graph, 'home', 'goal', max_hops=6)
    assert len(path) == 6
    expect_error(lambda: find_path(graph, 'home', 'goal', max_hops=3), 'max_hops=3', NavUnreachable)


def test_route_tie_break_by_hits():
    graph = NavGraph.from_dict({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['h'], 'is_home': True},
            {'id': 'left', 'name': 'L', 'anchors': ['l']},
            {'id': 'right', 'name': 'R', 'anchors': ['r']},
            {'id': 'goal', 'name': 'G', 'anchors': ['g']},
        ],
        'edges': [
            {'from': 'home', 'to': 'left', 'cost': 1.0, 'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'left', 'to': 'goal', 'cost': 1.0, 'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'home', 'to': 'right', 'cost': 1.0, 'action': {'type': ACTION_KEY, 'key': 'esc'}},
            {'from': 'right', 'to': 'goal', 'cost': 1.0, 'action': {'type': ACTION_KEY, 'key': 'esc'}},
        ],
    }, profile='p')
    default = find_path(graph, 'home', 'goal')
    assert default.page_ids in (('home', 'left', 'goal'), ('home', 'right', 'goal'))
    warm = find_path(graph, 'home', 'goal', hits={'home>right': 5, 'right>goal': 5})
    assert warm.page_ids == ('home', 'right', 'goal'), f'常走的边应胜出，实际 {warm.page_ids}'


# --------------------------------------------------------------------------- T4 动作与执行

def make_actions(clicks=None, keys=None):
    clicks = clicks if clicks is not None else []
    keys = keys if keys is not None else []
    return ActionExecutor(
        click_template=lambda template, roi: clicks.append(template) is None,
        click_point=lambda x, y: clicks.append((x, y)) is None,
        press_key=lambda key: keys.append(key) is None,
    )


def test_action_dispatch():
    clicks: list = []
    keys: list = []
    executor = make_actions(clicks, keys)

    executor.run(Action.from_dict({'type': ACTION_CLICK_TEMPLATE, 'template': 'go'}))
    executor.run(Action.from_dict({'type': ACTION_CLICK_POINT, 'point': [0.2, 0.4]}))
    executor.run(Action.from_dict({'type': ACTION_CLICK_POINT, 'point': [0.2, 0.4]}),
                 point=(0.8, 0.9))
    executor.run(Action.from_dict({'type': ACTION_KEY, 'key': 'esc'}))

    assert clicks == ['go', (0.2, 0.4), (0.8, 0.9)], f'动作序列不对: {clicks}'
    assert keys == ['esc']


def test_action_template_missing():
    executor = ActionExecutor(
        click_template=lambda template, roi: False,
        click_point=lambda x, y: None,
        press_key=lambda key: None,
    )
    expect_error(lambda: executor.run(Action.from_dict(
        {'type': ACTION_CLICK_TEMPLATE, 'template': 'missing'})), '未匹配到', ActionError)


def make_navigator(graph, *, page='home', clicks=None, keys=None, waiting=None,
                   cache=None, shots=None, reach=None):
    """构造一个用内存状态驱动的 Navigator。"""
    state = {'page': page, 'wait_ok': waiting if waiting is not None else (lambda pid: True)}
    clicks = clicks if clicks is not None else []
    keys = keys if keys is not None else []
    shots = shots if shots is not None else []

    def locate():
        return Located(page=graph.page(state['page']), anchor=graph.page(state['page']).anchors[0])

    def wait_page(page_id, timeout):
        ok = state['wait_ok'](page_id)
        if ok:
            state['page'] = page_id
        return ok

    navigator = Navigator(
        graph,
        locate=locate,
        wait_page=wait_page,
        actions=make_actions(clicks, keys),
        cache=cache or NavCache(),
        screenshot=shots.append,
    )
    return navigator, state, clicks, shots


def test_navigator_single_hop():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    navigator, state, clicks, _shots = make_navigator(graph)
    path = navigator.goto('arena')
    assert path.page_ids == ('home', 'arena')
    assert navigator.last_page == 'arena'
    assert state['page'] == 'arena'
    assert clicks == ['nav_home_arena_button']
    assert navigator.history == ('home', 'arena'), \
        f'历史应含起点与到达页，实际 {navigator.history}'


def test_navigator_already_there():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    navigator, _state, clicks, _shots = make_navigator(graph)
    path = navigator.goto('home')
    assert len(path) == 0 and clicks == [], '已在目标页时不应点击'
    assert navigator.last_page == 'home'


def test_navigator_retry_then_success():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    attempts = {'count': 0}

    def waiting(page_id):
        attempts['count'] += 1
        return attempts['count'] >= 2

    navigator, _state, clicks, shots = make_navigator(graph, waiting=waiting)
    path = navigator.goto('arena')
    assert path.page_ids == ('home', 'arena')
    assert attempts['count'] == 2, '默认 retries=1，应尝试两次'
    assert len(clicks) == 2 and shots == [], f'重试成功后不应截图: {shots}'


def test_navigator_failure_records_evidence():
    graph = NavGraph.from_dict(base_graph(), profile='p')
    cache = NavCache()
    navigator, _state, _clicks, shots = make_navigator(
        graph, waiting=lambda page_id: False, cache=cache)
    expect_error(lambda: navigator.goto('arena'), '跳转失败', NavStepFailed)
    assert cache.fails('home>arena') == 1
    assert shots == ['nav_step_failed_home_arena'], f'失败截图名不对: {shots}'


def test_navigator_disables_dead_edge():
    graph = NavGraph.from_dict({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['h'], 'is_home': True},
            {'id': 'mid', 'name': 'M', 'anchors': ['m']},
            {'id': 'goal', 'name': 'G', 'anchors': ['g']},
        ],
        'edges': [
            {'from': 'home', 'to': 'goal', 'retries': 0,
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'direct'}},
            {'from': 'home', 'to': 'mid',
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'mid'}},
            {'from': 'mid', 'to': 'goal',
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'finish'}},
        ],
    }, profile='p')
    clicked: list[str] = []

    def click_template(template, roi):
        clicked.append(template)
        return True

    state = {'page': 'home'}

    def locate():
        return Located(page=graph.page(state['page']), anchor=graph.page(state['page']).anchors[0])

    def wait_page(page_id, timeout):
        if page_id == 'goal' and 'mid' not in clicked:
            return False
        state['page'] = page_id
        return True

    navigator = Navigator(
        graph,
        locate=locate,
        wait_page=wait_page,
        actions=ActionExecutor(click_template=click_template,
                               click_point=lambda x, y: None,
                               press_key=lambda key: None),
        screenshot=lambda name: None,
    )

    for _ in range(2):
        try:
            navigator.goto('goal', start='home')
        except NavStepFailed:
            pass
    assert navigator.goto('goal', start='home').page_ids == ('home', 'mid', 'goal'), \
        '连续失败两次后应改走备用路径'


def test_navigator_back():
    graph = NavGraph.from_dict({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['h'], 'is_home': True},
            {'id': 'arena', 'name': 'A', 'anchors': ['a']},
        ],
        'edges': [
            {'from': 'home', 'to': 'arena',
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'go'}},
            {'from': 'arena', 'to': 'home',
             'action': {'type': ACTION_KEY, 'key': 'esc'}},
        ],
    }, profile='p')
    navigator, state, clicks, _shots = make_navigator(graph)
    navigator.goto('arena')
    assert navigator.back() == 'home'
    assert navigator.last_page == 'home' and state['page'] == 'home'
    assert navigator.back() is None, '历史为空时应返回 None'


def test_cache_roundtrip():
    directory = ROOT / '.tmp'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'nav_cache_test.json'
    cache = NavCache.load(path)
    cache.record('home>arena', True, '2026-01-01 00:00:00')
    cache.record('home>arena', False, '2026-01-01 00:01:00')
    cache.save()

    again = NavCache.load(path)
    assert again.hits('home>arena') == 1 and again.fails('home>arena') == 1
    assert again.hits_map() == {'home>arena': 1}
    path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- T5 任务接入

class FakeExecutor:
    """最小执行器替身：提供任务初始化与等待所需的两项。

    Attributes:
        config: 配置字典，供任务读取 `nav` 段。
        scene: 场景占位，`BaseTask.__init__` 会复制它。
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.scene = None

    def wait_condition(self, condition, time_out=0, *args, **kwargs):
        for _ in range(3):
            value = condition()
            if value:
                return value
        return False


class FakeApp:
    pass


class NavProbe(MyBaseTask):
    """导航测试用任务：不启动游戏，只暴露导航接口。"""

    SKIP_GAME_BOOTSTRAP = True
    game_profile = 'probe'

    def run(self):
        return 'ran'


def write_probe_graph(directory):
    path = Path(directory) / 'probe.json'
    path.write_text(json.dumps({
        'pages': [
            {'id': 'home', 'name': 'H', 'anchors': ['probe_home'], 'is_home': True},
            {'id': 'arena', 'name': 'A', 'anchors': ['probe_arena']},
        ],
        'edges': [
            {'from': 'home', 'to': 'arena',
             'action': {'type': ACTION_CLICK_TEMPLATE, 'template': 'probe_go_arena'}},
        ],
    }, ensure_ascii=False), encoding='utf-8')
    return path


def make_nav_task(directory):
    path = write_probe_graph(directory)
    registry.reset()
    task = NavProbe(FakeExecutor({'nav': {'graph_file': str(path)},
                                  'config_folder': str(directory)}), FakeApp())
    task.clicks = []
    task.page = 'home'
    task.anchors = {'home': 'probe_home', 'arena': 'probe_arena'}

    def find_one(template, **_kwargs):
        if template == 'probe_go_arena':
            return 'GO'
        return template.upper() if template == task.anchors[task.page] else None

    def click(box=None, *_args, **_kwargs):
        task.clicks.append(box)
        if box == 'GO':
            task.page = 'arena'

    task.find_one = find_one
    task.click = click
    return task, path


def test_task_nav_graph_missing_profile():
    class NoProfile(MyBaseTask):
        SKIP_GAME_BOOTSTRAP = True

        def run(self):
            return None

    task = NoProfile(FakeExecutor({}), FakeApp())
    expect_error(lambda: task.nav_graph, '未配置', NavError)


def test_task_goto_end_to_end():
    directory = ROOT / '.tmp'
    directory.mkdir(parents=True, exist_ok=True)
    task, path = make_nav_task(directory)

    assert task.ensure_page('home') is not None
    result = task.goto('arena')
    assert result.page_ids == ('home', 'arena')
    assert task.clicks == ['GO'], f'应点一次跳转按钮，实际 {task.clicks}'
    assert task.navigator.last_page == 'arena'
    assert task.current_page() == 'arena'

    cache_file = directory / 'nav_cache.json'
    assert cache_file.exists(), '导航缓存应落盘'
    path.unlink(missing_ok=True)
    cache_file.unlink(missing_ok=True)
    registry.reset()


def test_task_on_page_context():
    directory = ROOT / '.tmp'
    directory.mkdir(parents=True, exist_ok=True)
    task, path = make_nav_task(directory)
    seen: list[str] = []
    with task.on_page('arena') as inner:
        seen.append(inner.current_page())
    assert seen == ['arena'], f'上下文内应已在 arena，实际 {seen}'
    path.unlink(missing_ok=True)
    registry.reset()


def main():
    for name, func in [
        ('model.load_minimal', test_load_minimal),
        ('model.page_lookup_error', test_page_lookup_error),
        ('model.to_dict_roundtrip', test_to_dict_roundtrip),
        ('model.single_page_auto_home', test_single_page_auto_home),
        ('model.load_from_file', test_load_from_file),
        ('model.duplicate_page_id', test_duplicate_page_id),
        ('model.missing_home', test_missing_home),
        ('model.two_homes', test_two_homes),
        ('model.dangling_edge', test_dangling_edge),
        ('model.duplicate_edge', test_duplicate_edge),
        ('model.self_loop', test_self_loop),
        ('model.unknown_action', test_unknown_action),
        ('model.bad_roi', test_bad_roi),
        ('model.action_variants', test_action_variants),
        ('model.bad_json_file', test_bad_json_file),
        ('model.empty_pages', test_empty_pages),
        ('locator.last_page_hit', test_locate_last_page_hit),
        ('locator.full_scan_fallback', test_locate_falls_back_to_full_scan),
        ('locator.unknown_page', test_locate_unknown_page),
        ('locator.find_error_is_miss', test_locate_find_error_is_miss),
        ('locator.is_page', test_is_page),
        ('router.direct', test_route_direct),
        ('router.same_page', test_route_same_page),
        ('router.prefers_cheaper', test_route_prefers_cheaper_multi_hop),
        ('router.failing_edge', test_route_downweights_failing_edge),
        ('router.disabled_edge', test_route_disabled_edge),
        ('router.max_hops', test_route_max_hops),
        ('router.tie_break_hits', test_route_tie_break_by_hits),
        ('action.dispatch', test_action_dispatch),
        ('action.template_missing', test_action_template_missing),
        ('navigator.single_hop', test_navigator_single_hop),
        ('navigator.already_there', test_navigator_already_there),
        ('navigator.retry_then_success', test_navigator_retry_then_success),
        ('navigator.failure_evidence', test_navigator_failure_records_evidence),
        ('navigator.disables_dead_edge', test_navigator_disables_dead_edge),
        ('navigator.back', test_navigator_back),
        ('cache.roundtrip', test_cache_roundtrip),
        ('task.missing_profile', test_task_nav_graph_missing_profile),
        ('task.goto_end_to_end', test_task_goto_end_to_end),
        ('task.on_page_context', test_task_on_page_context),
    ]:
        check(name, func)

    failed = 0
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f'  -> {detail}' if detail else ''))
        failed += 0 if ok else 1
    print(f'\n{len(results) - failed}/{len(results)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
