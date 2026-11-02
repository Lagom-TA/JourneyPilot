"""当前结构里，每个 `user_id` 列的默认值都是固定本地身份。"""

from __future__ import annotations

import pytest

from travel_agent.storage.maintenance import migrate
from travel_agent.storage.maintenance.connection import connect
from travel_agent.runtime.local_identity import LOCAL_USER_ID

pytestmark = pytest.mark.postgres


def test_user_id_columns_default_to_local(temp_database):
    migrate.upgrade(temp_database)

    with connect(temp_database) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'user_id'"
            )
            defaults = dict(cur.fetchall())

    assert defaults, "没有任何 user_id 列，合同变了就要改这条测试"
    for table, default in defaults.items():
        assert default == f"'{LOCAL_USER_ID}'::text", f"{table}.user_id 默认值是 {default!r}"
