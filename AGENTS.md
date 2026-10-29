# 本地开发

在仓库根目录启动（依赖与首次配置见 [README](README.zh-CN.md#快速开始)）：

```bash
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

- 前端：http://localhost:8080；API 文档：http://localhost:8001/docs。
- 管理：`./run.sh status`、`./run.sh restart`、`./run.sh stop`；重启沿用启动时的环境变量。
- 前端支持热更新；`run.sh` 启动的后端需重启才能应用 Python 改动。
- 启动失败、端口冲突或服务异常时，按需查阅 [本地启动排障](docs/local-development-troubleshooting.md)。
