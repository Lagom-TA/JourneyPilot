"""数据库连接 URL 的组件转义。"""

from urllib.parse import quote

from sqlalchemy.engine import URL


def _host(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def postgres_url(*, user: str, password: str, host: str, port: int, database: str) -> str:
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{_host(host)}:{port}/{quote(database, safe='')}"
    )


def sqlalchemy_postgres_url(*, user: str, password: str, host: str, port: int, database: str, driver: str) -> URL:
    return URL.create(
        f"postgresql+{driver}", username=user, password=password,
        host=host.strip("[]"), port=port, database=database,
    )


def redis_url(*, password: str, host: str, port: int, database: int) -> str:
    auth = f":{quote(password, safe='')}@" if password else ""
    return f"redis://{auth}{_host(host)}:{port}/{database}"
