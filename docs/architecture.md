# Architecture

Ridgeline is a batch pipeline with a thin read-only web layer on top. Each stage writes files
the next stage reads, so any stage can be re-run, inspected or tested on its own.

## Data flow

```mermaid
flowchart LR
    subgraph sources["External sources (fetched once)"]
        OEDI["NREL ComStock on OEDI S3<br/>metadata, 15-min loads,<br/>weather, PUMA map"]
        URDB["OpenEI URDB record<br/>(committed JSON)"]
        ATB["NREL ATB 2024<br/>(cited in assumptions.yaml)"]
    end

    subgraph fetch["ridgeline fetch-data"]
        SEL["data/comstock.py<br/>select 40 sites"]
        LOC["data/locations.py<br/>PUMA centroids"]
    end

    subgraph simulate["dispatch + billing (M3)"]
        TAR["data/tariffs.py<br/>parse + match + proxy"]
        BAT["battery/<br/>threshold controller,<br/>LP bound, bills"]
    end

    subgraph rank["ridgeline rank (M4)"]
        MC["scenarios/<br/>15-yr cash flow,<br/>Monte Carlo"]
        RK["ranking/<br/>P10 rank, tornado,<br/>sweeps, sentences"]
    end

    subgraph serve["ridgeline serve (M5)"]
        API["api/<br/>FastAPI"]
        WEB["web/<br/>Leaflet page"]
    end

    OEDI --> SEL --> SITES[("data/sites.csv")]
    SEL --> LOADS[("data/cache/comstock/")]
    SEL --> LOC --> LOCS[("data/site_locations.csv")]
    URDB --> TAR
    SITES --> TAR --> BAT
    LOADS --> BAT --> SAV[("results/savings_FINGERPRINT.csv")]
    ATB --> ASM[("assumptions.yaml")] --> MC
    SAV --> MC --> RK --> RES[("results/ranking.csv,<br/>fan.csv, tornado.csv, ...")]
    RES --> REP["scripts/report_ranking.py"] --> DOCS[("docs/m4/")]
    RES --> API
    LOCS --> API
    LOADS --> API
    API --> WEB

    subgraph agent["ridgeline evals / extract-tariff / explain (M6)"]
        LLM["agent/<br/>LLM client (Anthropic or mock)"]
        VAL["agent/validators.py<br/>reject ungrounded output"]
    end
    TXT[("tariff text")] --> LLM
    RES --> LLM
    LLM --> VAL
```

`results/` is `data/cache/results/` (gitignored). `docs/m4/` holds a committed copy for readers.

## Module dependencies

```mermaid
flowchart TB
    cli["cli.py"] --> data & battery & ranking & api & agent
    agent["agent/"] --> ranking
    api["api/"] --> data
    ranking["ranking/"] --> scenarios
    scenarios["scenarios/"] --> assumptions
    battery["battery/"] --> data
    gaps["gaps/"] --> data
    data["data/<br/>schemas, comstock, tariffs,<br/>weather, sites, locations"] --> config & assumptions
    results["results.py"] --> config
    config["config.py"]
    assumptions["assumptions.py"]
```

Arrows point from a module to what it imports. Nothing imports `cli.py`, `api/` or `agent/`;
`agent/` imports the Anthropic SDK only inside `AnthropicClient`. The core
(`battery/`, `scenarios/`, `ranking/`) is pure functions over numpy and pandas plus pydantic models:
no network and no file I/O. I/O lives in `data/`, `results.py`, `api/data.py` and `cli.py`.

## Boundaries and contracts

| Boundary | Contract | Where it is enforced |
|---|---|---|
| Raw data → everything | `Site`, `LoadProfile`, `Tariff`, `BatterySpec` pydantic models | `data/schemas.py` |
| Numbers → code | Every value has a source URL or `ASSUMPTION`; ranges bracket the value | `assumptions.py`, `tests/unit/test_config_and_assumptions.py` |
| Timestamps | UTC interval-start internally; tariffs in America/New_York | `data/timestamps.py` (ADR-003) |
| Simulation → Monte Carlo | Savings table, cached under a fingerprint of all its inputs | `results.py` |
| Monte Carlo → web | CSV and JSON files written by `rank`; API never recomputes | `api/data.py` |
| API → page | Pydantic response models | `api/models.py` |
| LLM → anything shown | Structured output schema; every value quoted from the source, every number from the facts | `agent/validators.py` (ADR-014) |
