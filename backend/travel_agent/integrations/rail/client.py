"""12306 余票与中转查询的 HTTP 客户端。"""

from __future__ import annotations

from travel_agent.integrations.rail.errors import QueryRefusedError
from typing import Any
from typing import Mapping
from typing import Optional
import httpx
import re


API_BASE = "https://kyfw.12306.cn"


LEFT_TICKET_INIT_URL = f"{API_BASE}/otn/leftTicket/init"


LCQUERY_INIT_URL = f"{API_BASE}/otn/lcQuery/init"


_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,zh-TW;q=0.8,zh-HK;q=0.7,en-US;q=0.6,en;q=0.5"


_BROWSER_HEADERS = {
    "User-Agent": _DESKTOP_USER_AGENT,
    "Accept-Language": _ACCEPT_LANGUAGE,
}


_LEFT_TICKET_PATH_RE = re.compile(r"CLeftTicketUrl = '(.+?)'")


_LC_SEARCH_PATH_RE = re.compile(r"lc_search_url = '(.+?)'")


DEFAULT_TIMEOUT_SECONDS = 20.0


def extract_left_ticket_path(html: str) -> str:
    """读取 12306 在 init 页面发布的实时余票查询路径。"""

    match = _LEFT_TICKET_PATH_RE.search(html or "")
    if match is None:
        raise QueryRefusedError(
            "12306 /otn/leftTicket/init did not publish CLeftTicketUrl"
        )
    return match.group(1).strip()


def extract_lc_query_path(html: str) -> str:
    """读取 12306 在 lcQuery init 页面发布的实时中转查询路径。"""

    match = _LC_SEARCH_PATH_RE.search(html or "")
    if match is None:
        raise QueryRefusedError("12306 /otn/lcQuery/init did not publish lc_search_url")
    return match.group(1).strip()


class Rail12306Client:
    """每次查询使用一个 12306 会话：先 init 获取 cookie 与实时路径，再查询。"""

    def __init__(
        self,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._transport = transport
        self._timeout = timeout

    def _new_client(self, *, follow_redirects: bool) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout,
            follow_redirects=follow_redirects,
            headers=dict(_BROWSER_HEADERS),
        )

    async def _open_session(self, client: httpx.AsyncClient) -> str:
        """请求 init 页面：它同时设置会话 cookie 并给出查询路径。"""

        response = await client.get(LEFT_TICKET_INIT_URL)
        if response.status_code != 200:
            raise QueryRefusedError(
                f"12306 /otn/leftTicket/init returned HTTP {response.status_code}"
            )
        return extract_left_ticket_path(response.text)

    async def fetch_left_tickets(
        self, *, date: str, from_code: str, to_code: str
    ) -> tuple[list[str], dict[str, str]]:
        """返回某一对车站的 ``(data.result 行, data.map)``。"""

        params = {
            "leftTicketDTO.train_date": date,
            "leftTicketDTO.from_station": from_code,
            "leftTicketDTO.to_station": to_code,
            "purpose_codes": "ADULT",
        }
        async with self._new_client(follow_redirects=False) as client:
            path = await self._open_session(client)
            response = await self._query_left_ticket(client, path, params)
            if response.status_code == 404:
                path = await self._open_session(client)
                response = await self._query_left_ticket(client, path, params)
            if response.status_code == 302:
                raise QueryRefusedError(
                    "12306 refused the remaining-ticket query (HTTP 302 -> "
                    f"{response.headers.get('location', '')}): the date is "
                    "outside the live inventory window or the session was "
                    "rejected"
                )
            if response.status_code != 200:
                raise QueryRefusedError(
                    "12306 remaining-ticket query returned HTTP "
                    f"{response.status_code} for path {path!r}"
                )
            payload = self._decode_json(response)
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise QueryRefusedError(
                f"12306 查询有误: {payload.get('messages') or data!r}"
            )
        rows = [str(row) for row in (data.get("result") or ())]
        names = {str(key): str(value) for key, value in (data.get("map") or {}).items()}
        return rows, names

    async def _query_left_ticket(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: Mapping[str, str],
    ) -> httpx.Response:
        return await client.get(
            f"{API_BASE}/otn/{path.lstrip('/')}",
            params=dict(params),
            headers={"Referer": LEFT_TICKET_INIT_URL},
        )

    async def fetch_interline(
        self,
        *,
        date: str,
        from_code: str,
        to_code: str,
        middle_code: str = "",
    ) -> list[dict[str, Any]]:
        """返回 12306 为该车站对提供的全部 ``middleList`` 行程。"""

        async with self._new_client(follow_redirects=True) as discovery:
            response = await discovery.get(LCQUERY_INIT_URL)
            if response.status_code != 200:
                raise QueryRefusedError(
                    f"12306 /otn/lcQuery/init returned HTTP {response.status_code}"
                )
            lc_path = extract_lc_query_path(response.text)

        params = {
            "train_date": date,
            "from_station_telecode": from_code,
            "to_station_telecode": to_code,
            "middle_station": middle_code,
            "result_index": "0",
            "can_query": "Y",
            "isShowWZ": "N",
            "purpose_codes": "00",
            "channel": "E",
        }
        itineraries: list[dict[str, Any]] = []

        async with self._new_client(follow_redirects=False) as client:
            while True:
                response = await client.get(
                    f"{API_BASE}/{lc_path.lstrip('/')}",
                    params=dict(params),
                    headers={"Referer": LCQUERY_INIT_URL},
                )
                if response.status_code != 200:
                    raise QueryRefusedError(
                        "12306 interline query returned HTTP "
                        f"{response.status_code} for path {lc_path!r}"
                    )
                payload = self._decode_json(response)
                data = payload.get("data")
                if not isinstance(data, Mapping):
                    raise QueryRefusedError(
                        f"12306 中转查询有误: {payload.get('errorMsg') or data!r}"
                    )
                itineraries.extend(
                    item
                    for item in (data.get("middleList") or ())
                    if isinstance(item, Mapping)
                )
                if str(data.get("can_query")) != "Y":
                    break
                params["result_index"] = str(data.get("result_index"))
        return itineraries

    @staticmethod
    def _decode_json(response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as error:
            raise QueryRefusedError(
                f"12306 返回了非 JSON 响应: {response.text[:200]!r}"
            ) from error
        if not isinstance(payload, Mapping):
            raise QueryRefusedError(f"12306 返回了非对象响应: {payload!r}")
        return payload
