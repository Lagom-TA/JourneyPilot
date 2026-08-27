"""``default_mcp_servers()`` 的逐字段基线。

这份基线是 MCP 默认声明外置 YAML 那次改动的唯一验收依据：改动前生成并提交，改动后
必须逐字段完全一致。11 个 server 的 name / command / args / env / description /
required_env 全部落盘。

两条分支各一份：``<repo>/node_modules/.bin`` 里有本地 bin 时走本地绝对路径，没有时
回落 ``npx -y <package>``。这两条不是等价写法——镜像构建期 ``npm ci`` 到
``<repo>/node_modules``，运行层不带 npm（npx 根本不存在），所以只测一条等于把生产
镜像那条放过去。

落盘前做两件归一化，否则这份东西既不可提交也不可比：

- ``sys.executable`` 与 ``_REPO_ROOT`` 换成占位符——它们逐机器不同
- 环境变量先被设成确定的占位值——真值是 API Key，不能进仓
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from travel_agent.config.mcp_defaults import default_mcp_servers

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "mcp"

_PYTHON_TOKEN = "<PYTHON>"
_REPO_ROOT_TOKEN = "<REPO_ROOT>"

# 六个带 required_env 的 server 用到的 Key。测试里一律设成 ``env-<NAME>``：
# 真值是 API Key，落进 fixture 就等于把它提交了。
_ENV_KEYS = (
    "TAVILY_API_KEY",
    "BRAVE_API_KEY",
    "FIRECRAWL_API_KEY",
    "BAIDU_MAP_API_KEY",
    "AMAP_MAPS_API_KEY",
    "DUFFEL_API_KEY_LIVE",
)

_BRANCHES = ("local_bin", "npx_fallback")


def _normalize(value: str) -> str:
    """把逐机器不同的前缀换成占位符。先换 repo root，它更长。"""

    return value.replace(str(_REPO_ROOT), _REPO_ROOT_TOKEN).replace(
        sys.executable, _PYTHON_TOKEN
    )


def _force_local_bins(monkeypatch: pytest.MonkeyPatch, *, present: bool) -> None:
    """让 ``node_modules/.bin`` 下的探测一律命中或一律不命中。

    只改这个目录下的判断，别的路径（比如 YAML 声明文件本身）走真实 ``exists``。
    """

    bin_dir = _REPO_ROOT / "node_modules" / ".bin"
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self.parent == bin_dir:
            return present
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)


def _snapshot(monkeypatch: pytest.MonkeyPatch, *, branch: str) -> str:
    """当前 ``default_mcp_servers()`` 的可比对序列化。"""

    for key in _ENV_KEYS:
        monkeypatch.setenv(key, f"env-{key}")
    _force_local_bins(monkeypatch, present=branch == "local_bin")

    payload = {}
    for name, item in default_mcp_servers().items():
        dumped = item.model_dump()
        dumped["command"] = (
            _normalize(dumped["command"]) if dumped["command"] else dumped["command"]
        )
        dumped["args"] = (
            [_normalize(arg) for arg in dumped["args"]]
            if dumped["args"] is not None
            else None
        )
        payload[name] = dumped
    # server 的键序有意义（它是声明顺序），所以按插入序落盘；字段名排序只为可读。
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


@pytest.mark.parametrize("branch", _BRANCHES)
def test_default_mcp_servers_match_the_committed_baseline(monkeypatch, branch):
    """11 个 server 的每一个字段都必须与提交进仓的基线一致。

    这条不是"提示词改了要看见"那类快照，它是等价性证明：MCP 声明从 Python 搬进 YAML
    的那次改动，唯一可接受的结果是这份输出一个字节都没变。
    """

    path = _FIXTURE_DIR / f"servers.{branch}.json"
    expected = _snapshot(monkeypatch, branch=branch)
    # 故意没有"一键重生成"的按钮。这份东西是等价性证明，不是快照：需要它变的时候，
    # 变的是 11 个 server 的声明本身，那要单独立票并在 review 里逐字段看。
    assert path.exists(), f"{path.relative_to(_REPO_ROOT)} 缺失"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(expected), (
        f"{path.relative_to(_REPO_ROOT)} 与 default_mcp_servers() 不一致。"
        "改 MCP 默认声明本身是行为改动，要单独立票；重构不该动这份输出。"
    )


def test_the_two_branches_really_differ_on_the_node_servers(monkeypatch):
    """两条分支必须真的不同，否则上面那两条里有一条是白测的。

    六个走 npm 的 server 在 local_bin 分支下是 ``<REPO_ROOT>/node_modules/.bin/*``
    加空 args，在回落分支下是 ``npx -y <package>``。五个走 sys.executable 的不受影响。
    """

    with pytest.MonkeyPatch.context() as local:
        local_bin = json.loads(_snapshot(local, branch="local_bin"))
    with pytest.MonkeyPatch.context() as fallback:
        npx = json.loads(_snapshot(fallback, branch="npx_fallback"))

    differing = {name for name in local_bin if local_bin[name] != npx[name]}
    assert differing == {
        "tavily-search",
        "brave-search",
        "firecrawl",
        "baidu-maps",
        "amap-maps",
        "open-meteo",
    }
    for name in differing:
        assert npx[name]["command"] == "npx"
        assert npx[name]["args"][0] == "-y"
        assert local_bin[name]["args"] == []
        assert local_bin[name]["command"].startswith(
            f"{_REPO_ROOT_TOKEN}/node_modules/.bin/"
        )


def test_env_is_derived_from_required_env_and_read_per_call(monkeypatch):
    """``env`` 只装 ``required_env`` 里那些 Key，而且是每次调用现读。

    现读这件事必须留在 Python：``_mcp_servers()`` 是 pydantic 的默认工厂，每次构造
    ``Settings`` 调一次，环境变量的读取就发生在那一次里。把最终 server dict 缓存
    起来，会让所有 monkeypatch 环境变量再重建 Settings 的用例变红。
    """

    _force_local_bins(monkeypatch, present=False)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    unset = default_mcp_servers()
    for name, item in unset.items():
        if item.required_env:
            # 声明了 required_env 的 server：Key 没配时是空 dict，不是 None——
            # MCPManager 靠 required_env 跳过它，env 的空与无在这里不等价。
            assert item.env == {}, name
        else:
            assert item.env is None, name

    monkeypatch.setenv("TAVILY_API_KEY", "set-later")
    # 同一个进程里再调一次，必须看见新值：说明没有把结果缓存住。
    assert default_mcp_servers()["tavily-search"].env == {"TAVILY_API_KEY": "set-later"}
    assert unset["tavily-search"].env == {}

    for item in default_mcp_servers().values():
        assert set(item.env or {}) <= set(item.required_env), (
            "env 的 Key 必须从 required_env 派生，不许各写一份"
        )
