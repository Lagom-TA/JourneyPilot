from __future__ import annotations

import argparse

from .backup import cmd_backup
from .configuration import (
    cmd_config_show,
    cmd_config_validate,
    cmd_config_env,
    cmd_config_docs,
    cmd_configure,
)
from .doctor import cmd_doctor
from .migrate import cmd_migrate
from .restore import cmd_restore
from .schema import cmd_db_write_fingerprint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="journeypilot",
        description="JourneyPilot 维护命令：数据库迁移、备份与恢复、环境诊断。",
    )
    parser.add_argument(
        "--log-level",
        default="warning",
        help="CLI 自身的日志级别（默认 warning：命令输出本身就是结论）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--json", action="store_true", help="输出机器可读 JSON（供 CI 使用）"
        )
        sub.add_argument(
            "--backup-dir",
            default=None,
            help="备份根目录（默认取 config.yaml 的 maintenance.backup_dir）",
        )

    doctor = subparsers.add_parser(
        "doctor", help="体检：数据库、迁移版本、结构、扩展、备份现状"
    )
    add_common(doctor)
    doctor.set_defaults(func=cmd_doctor)

    migrate = subparsers.add_parser(
        "migrate",
        help="执行版本化迁移并建立 checkpoint 表（持锁；非空库先自动备份）。启动 API 之前必须先跑这条",
    )
    add_common(migrate)
    migrate.add_argument(
        "--allow-destructive",
        action="store_true",
        help="授权执行标记为破坏性（会丢数据或不可逆）的迁移",
    )
    migrate.add_argument(
        "--skip-backup",
        action="store_true",
        help="跳过升级前自动备份（危险：迁移失败时没有可恢复的快照）",
    )
    migrate.add_argument(
        "--dry-run", action="store_true", help="只打印判定与待执行迁移，不改数据库"
    )
    migrate.add_argument(
        "--sql",
        action="store_true",
        help="离线输出迁移 SQL 而不执行（不连库、不加锁；不含 langgraph 自己建的 checkpoint 表）",
    )
    migrate.set_defaults(func=cmd_migrate)

    backup = subparsers.add_parser("backup", help="生成一份经过校验的备份")
    add_common(backup)
    backup.add_argument("--label", default="", help="备份标签，写进目录名和 manifest")
    backup.add_argument(
        "--kind",
        choices=("manual", "automatic"),
        default="manual",
        help="manual（默认）永不被保留策略自动删除",
    )
    backup.add_argument("--list", action="store_true", help="列出已有备份")
    backup.add_argument("--verify", metavar="DIR", help="校验一个备份目录的 checksum")
    backup.add_argument(
        "--prune",
        action="store_true",
        help="清理超出保留份数的自动备份（不动手工备份）",
    )
    backup.add_argument(
        "--dry-run", action="store_true", help="配合 --prune：只列出将删除的"
    )
    backup.set_defaults(func=cmd_backup)

    restore = subparsers.add_parser(
        "restore", help="从备份恢复（先恢复到新库并验证，再切换；旧库改名留档）"
    )
    add_common(restore)
    restore.add_argument("directory", nargs="?", help="备份目录")
    restore.add_argument("--yes", action="store_true", help="确认执行恢复")
    restore.add_argument(
        "--terminate-active",
        action="store_true",
        help="切换前强制断开当前数据库上的活动连接",
    )
    restore.add_argument(
        "--list-retained", action="store_true", help="列出恢复留档的旧库"
    )
    restore.add_argument("--drop-retained", metavar="DBNAME", help="删除一个恢复留档库")
    restore.set_defaults(func=cmd_restore)

    config = subparsers.add_parser("config", help="查看、校验与生成配置")
    config_subparsers = config.add_subparsers(dest="config_command", required=True)

    config_show = config_subparsers.add_parser(
        "show", help="当前生效的配置与每个值的来源（密钥脱敏）"
    )
    config_show.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    config_show.add_argument(
        "--effective",
        action="store_true",
        help="保留给可读性：这条命令本来就只报生效值（默认值也在里面，来源写着 config default）",
    )
    config_show.add_argument(
        "--redacted",
        action="store_true",
        help="保留给可读性：密钥一律脱敏，没有不脱敏的模式",
    )
    config_show.set_defaults(func=cmd_config_show)

    config_validate = config_subparsers.add_parser(
        "validate", help="只校验配置，不启动服务"
    )
    config_validate.add_argument(
        "--json", action="store_true", help="输出机器可读 JSON"
    )
    config_validate.set_defaults(func=cmd_config_validate)

    config_env = config_subparsers.add_parser("env", help="列出全部合法环境变量名")
    config_env.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    config_env.set_defaults(func=cmd_config_env)

    config_docs = config_subparsers.add_parser(
        "docs", help="从 schema 生成配置参考文档与 JSON Schema"
    )
    config_docs.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    config_docs.add_argument(
        "--check",
        action="store_true",
        help="只比对不写：生成物与当前 schema 不一致时以 1 退出（CI 门禁）",
    )
    config_docs.set_defaults(func=cmd_config_docs)

    configure = subparsers.add_parser(
        "configure", help="按 provider preset 写好 config.yaml 的模型段（不写 API Key）"
    )
    configure.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    configure.add_argument("--provider", default="", help="preset id（见 --list）")
    configure.add_argument("--list", action="store_true", help="列出可用 preset")
    configure.add_argument("--dry-run", action="store_true", help="只打印将写入的内容")
    configure.set_defaults(func=cmd_configure)

    db = subparsers.add_parser("db", help="开发者子命令")
    db_subparsers = db.add_subparsers(dest="db_command", required=True)

    db_status = db_subparsers.add_parser("status", help="等价于 doctor")
    add_common(db_status)
    db_status.set_defaults(func=cmd_doctor)

    db_fingerprint = db_subparsers.add_parser(
        "write-fingerprint",
        help="把当前库的结构指纹写成某个 revision 的存档（开发者）",
    )
    add_common(db_fingerprint)
    db_fingerprint.add_argument("--revision", required=True, help="目标 revision")
    db_fingerprint.add_argument(
        "--database", default=None, help="从哪个库读（默认 config.yaml 里的那个）"
    )
    db_fingerprint.set_defaults(func=cmd_db_write_fingerprint)

    return parser
