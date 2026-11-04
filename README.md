<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-lockup-night.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/logo-lockup-day.png">
  <img src="docs/assets/logo-lockup-day.png" alt="JourneyPilot" width="620">
</picture>

<h1>JourneyPilot</h1>

<p>A travel plan you can explore, discuss, and refine.</p>

[![License: MIT](https://img.shields.io/badge/license-MIT-8f6736?style=flat-square)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-8f6736?style=flat-square)](https://www.python.org/)
[![Node 22](https://img.shields.io/badge/node-22-8f6736?style=flat-square)](https://nodejs.org/)

**English** · [简体中文](README.zh-CN.md)

</div>

JourneyPilot is an open-source, self-hosted AI travel planning workspace. Give it a destination, dates,
travel companions, and preferences. It researches the trip, builds a day-by-day itinerary, and brings
that itinerary together with a map and reading view in one workspace.

The current product interface is in Simplified Chinese.

## Plan a trip

Describe a trip in your own words or enter the destination, dates, and preferences in the form. For a
full plan, JourneyPilot reviews the request, verifies places and asks follow-up questions when needed,
then presents a research plan for approval before researching places, stays, transport, and weather.
If research is interrupted, completed results are retained and retries use the original plan's time limits.
Disconnecting interrupts the current execution. Reopening restores saved state and content; resumable
plans continue only when you choose to resume them.
Different sessions can run at the same time; switching sessions leaves their ongoing runs active.
When a run budget is enabled, model calls are checked against an estimate; incomplete pricing or usage
means the cost limit cannot be guaranteed precisely.

Once a plan is ready, you can:

- Explore daily stops, meals, stays, and transport alongside a map.
- Read the report, inspect available sources, or export a PDF.
- Continue the conversation to request changes and clarify them over several turns, including adjustments suggested by a weather update.
- Save travel styles and your own reference material for later planning.

Sources, prices, and live information depend on the services used. Prices are shown for individual items
without a combined total, and the PDF identifies items that remain unplanned. Some local routes may be estimates,
and availability can change. JourneyPilot does not make bookings or process payments.

## Quick start

You will need [uv](https://docs.astral.sh/uv/), Python 3.11, Node.js 22 (minimum 20.19) and npm,
Docker Desktop or Docker Engine with Compose, and credentials for a model service.

```bash
git clone https://github.com/Lagom-TA/JourneyPilot.git
cd JourneyPilot
cp backend/config.example.yaml config.yaml
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
```

Choose a model configuration preset. This example uses DeepSeek; `--list` shows the available presets.
Set the keys for your own provider:

```bash
uv run --project backend python backend/journeypilot.py configure --list
uv run --project backend python backend/journeypilot.py configure --provider deepseek
export JOURNEYPILOT_PRIMARY_MODEL__API_KEY="your-api-key"
export JOURNEYPILOT_FAST_MODEL__API_KEY="your-api-key"
```

Start the app from the repository root:

```bash
JOURNEYPILOT_DATABASE__PORT=55433 JOURNEYPILOT_REDIS__PORT=16379 ./run.sh start
```

On first start, the script installs dependencies, starts PostgreSQL and Redis with Compose, runs database
migrations, and launches the API and web app. The default local embedding model downloads on first use.

| Service | URL |
| --- | --- |
| Web app | <http://localhost:8080> |
| API documentation | <http://localhost:8001/docs> |
| Readiness check | <http://localhost:8001/api/health/ready> |

`run.sh` supervises the services in the foreground. Use another terminal to inspect or stop them:

```bash
./run.sh status
./run.sh logs backend       # Frontend logs: ./run.sh logs frontend
./run.sh check
./run.sh stop
```

The database and Redis ports above match the included Compose configuration. Pass those environment
variables again when using `./run.sh restart`, or set the ports in `config.yaml`. On shutdown, the API
stops background work and MCP sessions, flushes usage, and closes database and Redis connections. See
[local development troubleshooting](docs/local-development-troubleshooting.md) if startup fails.

## Run with Docker Compose

You can also run the web app and API together in containers. Prepare `config.yaml` as above, then create
`.env` in the repository root with the model and data-service credentials you need, for example:

```dotenv
JOURNEYPILOT_PRIMARY_MODEL__API_KEY=your-api-key
JOURNEYPILOT_FAST_MODEL__API_KEY=your-api-key
```

```bash
docker compose -f infra/compose.yml up -d --build
docker compose -f infra/compose.yml logs -f api
```

The web app and API are both available at <http://localhost:8001>. Compose reads the root `.env` file;
model keys exported only in the host shell are not automatically passed to the API container. PostgreSQL
and Redis also publish host ports `55433` and `16379` respectively.

JourneyPilot is designed for self-hosted, single-user use and has no built-in accounts or authentication.
Run it on a trusted network; before exposing it to an untrusted network, configure access controls and
check the API, database, and Redis listening addresses. See the [security policy](SECURITY.md).

## Configuration and data

Settings come from built-in defaults, `config.yaml`, and environment variables, in that order. Common
scalar settings can be overridden with `JOURNEYPILOT_<SECTION>__<FIELD>`, for example
`JOURNEYPILOT_DATABASE__PORT`. The [configuration reference](docs/configuration.md) lists the fields,
defaults, and environment variables.

```bash
uv run --project backend python backend/journeypilot.py config validate
uv run --project backend python backend/journeypilot.py config show
uv run --project backend python backend/scripts/check_mcp.py
```

Built-in tools include web search, OpenStreetMap/Nominatim, China Railway 12306, Open-Meteo, and exchange
rates. Amap, Baidu, Tavily, Brave, Duffel, and other providers can be configured as needed. On tool-name
collisions, the registered owner is retained; MCP servers register in configuration order. Coverage and
results depend on each service; routes within mainland China require an Amap key. Model and provider
calls may incur charges.

The knowledge base uses a local Qwen3 ONNX embedding model by default; a compatible remote embedding
service can also be configured. Incomplete embedding results fail indexing and leave the existing document intact.
The repository includes a [small factory corpus](backend/data/corpus/factory/README.md)
that can be imported using its instructions. The optional local binary seed is not included.

The startup script and container entrypoint run database migrations before starting the API. To inspect
the database or create a backup:

```bash
uv run --project backend python backend/journeypilot.py doctor
uv run --project backend python backend/journeypilot.py backup
```

## Development

```bash
# Run from the repository root
uv sync --project backend --locked --group local-embedding --group dev
uv run --project backend ruff check --config backend/pyproject.toml backend/travel_agent/ backend/tests/ backend/scripts/
uv run --project backend pytest -c backend/pyproject.toml backend/tests/ --ignore=backend/tests/db -q
npm --prefix frontend ci
npm --prefix frontend run check
```

Database integration tests require a reachable PostgreSQL instance. For browser tests and real-provider
planning tests, see the [end-to-end test guide](frontend/e2e/README.md).

- [Documentation index](docs/README.md) · [Architecture](docs/architecture/overview.md) · [Configuration](docs/configuration.md)
- [Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md)

## License

[MIT License](LICENSE). Third-party data, fonts, and assets are listed in [NOTICE](NOTICE).
