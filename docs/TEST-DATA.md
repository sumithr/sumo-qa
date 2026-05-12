# Test Data

The local known-good test-data catalogue: shape, validation, registration. Source: [`src/sumo_qa/tdm_models.py`](../src/sumo_qa/tdm_models.py), [`src/sumo_qa/tdm_catalogue.py`](../src/sumo_qa/tdm_catalogue.py), [`src/sumo_qa/tdm_validation.py`](../src/sumo_qa/tdm_validation.py), [`src/sumo_qa/tdm_service.py`](../src/sumo_qa/tdm_service.py).

The Test Data Assistant is intentionally lightweight. It helps teams discover and validate usable integration data without an enterprise provisioning workflow.

## Catalogue structure

Catalogue entries are organised by **domain folder** — pick whatever names match your team's surfaces (auth, billing, payments, search, inventory, scheduling, etc.). The repo ships two domain-neutral sample folders to show the shape; replace or supplement with your own.

```text
knowledge/test_data/
  auth/
    sample_accounts.yaml       # ships in-repo: neutral sample for the shape
  billing/
    sample_invoices.yaml       # ships in-repo: neutral sample for the shape
  <your-domain>/
    <your-fixtures>.yaml       # add as needed; .gitignore your local team data if not for upstream
```

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
