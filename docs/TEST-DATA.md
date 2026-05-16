# Test Data

The local known-good test-data catalogue: shape, validation, registration. Source: [`src/sumo_qa/tdm_models.py`](../src/sumo_qa/tdm_models.py), [`src/sumo_qa/tdm_catalogue.py`](../src/sumo_qa/tdm_catalogue.py), [`src/sumo_qa/tdm_validation.py`](../src/sumo_qa/tdm_validation.py), [`src/sumo_qa/tdm_service.py`](../src/sumo_qa/tdm_service.py).

The Test Data Assistant is intentionally lightweight. It helps teams discover and validate usable integration data without an enterprise provisioning workflow.

## Catalogue structure

Catalogue entries are organised by **domain folder** — pick whatever names match your team's surfaces (auth, billing, payments, search, inventory, scheduling, etc.). The catalogue starts empty on a fresh install; you populate it with your own known-good entries via `sumo_qa_register_known_good_test_data` (or hand-authored YAML).

```text
knowledge/test_data/
  <your-domain>/
    <your-fixtures>.yaml       # add as needed; .gitignore local team data if not for upstream
```

A shape-only reference set (auth / billing) lives at [`tests/fixtures/test_data/`](../tests/fixtures/test_data/) in the source tree — those are internal test fixtures used by the package's own test suite, not catalogue defaults. They are deliberately excluded from the wheel so a `pip install sumo-qa` user does not see them surface as results from `sumo_qa_find_test_data`.

Catalogue entries are version-controlled YAML and include:

- `id` — stable, unique
- `environment`
- `domain` — your team's chosen folder name
- `scenario_tags`
- `known_valid_for`
- `constraints`
- `owner`
- `last_validated_at`
- `confidence`
- `source`
- `notes`
- `product_id`, `sku` — *optional, for product-style domains*

`product_id` / `sku` are illustrative optional identifier fields for retail-style domains. Non-retail domains (auth, billing, infrastructure, ML, etc.) leave them blank.

Override the path via `QA_TEST_DATA_PATH` (see [docs/CONFIGURATION.md](CONFIGURATION.md)).

## Discovery and ranking

Every TDM response includes confidence, validation reason, freshness, and validation source. Fresh entries rank higher than stale entries; results explain why they are suitable.

`sumo_qa_find_test_data` paginates via `limit` / `offset` and returns `total_count` / `has_more` / `next_offset`.

## Validation

Current validation is local and deterministic:

- schema validation through typed models
- required ownership and scenario metadata checks
- freshness scoring from `last_validated_at`
- no downstream API calls

`sumo_qa_validate_test_data` flags future timestamps and high-confidence-but-never-validated entries.

The pluggable `TestDataValidator` abstraction is ready for live validators / downstream API checks / ownership reservations / environment-aware governance later, without replacing the MCP tool contracts.

## Registration

`sumo_qa_register_known_good_test_data` writes to `knowledge/test_data/<domain>/known_good.yaml`, updates timestamps when needed, and avoids duplicate entries with the same environment, domain, optional identifier (`product_id` / `sku`), and overlapping scenario use.

The operation is additive (never deletes), so it carries `destructiveHint=false` despite not being read-only.
