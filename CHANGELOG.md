# Changelog

## [0.3.1](https://github.com/sumithr/sumo-qa/compare/v0.3.0...v0.3.1) (2026-05-18)


### Documentation

* rewrite README and DEMO for clarity ([#53](https://github.com/sumithr/sumo-qa/issues/53)) ([f5fa1a5](https://github.com/sumithr/sumo-qa/commit/f5fa1a536818114472af57cf753961a949422d1b))

## [0.3.0](https://github.com/sumithr/sumo-qa/compare/v0.2.3...v0.3.0) (2026-05-18)


### Features

* **qa-eval:** A/B value-measurement harness + Tier 1 skill improvements ([#51](https://github.com/sumithr/sumo-qa/issues/51)) ([da8056b](https://github.com/sumithr/sumo-qa/commit/da8056bcb91383de080846d5a34e1fddef0609f3))

## [0.2.3](https://github.com/sumithr/sumo-qa/compare/v0.2.2...v0.2.3) (2026-05-17)


### Continuous Integration

* **release-please:** bump README badge cache-buster on release ([#49](https://github.com/sumithr/sumo-qa/issues/49)) ([970d20e](https://github.com/sumithr/sumo-qa/commit/970d20eaeab2b92d30c540d55f63b7dad865ba67))

## [0.2.2](https://github.com/sumithr/sumo-qa/compare/v0.2.1...v0.2.2) (2026-05-17)


### Miscellaneous Chores

* **security:** add npm-audit + pip-audit pre-commit hooks ([#47](https://github.com/sumithr/sumo-qa/issues/47)) ([e254ef0](https://github.com/sumithr/sumo-qa/commit/e254ef07dcce9a2ca308805fea489afd5eea9889))

## [0.2.1](https://github.com/sumithr/sumo-qa/compare/v0.2.0...v0.2.1) (2026-05-17)


### Bug Fixes

* **deps:** patch 6 Dependabot protobufjs CVEs via scoped override ([#45](https://github.com/sumithr/sumo-qa/issues/45)) ([c2f126e](https://github.com/sumithr/sumo-qa/commit/c2f126ece2742b754ec1415258cd080211dc3053))

## [0.2.0](https://github.com/sumithr/sumo-qa/compare/v0.1.5...v0.2.0) (2026-05-17)


### Features

* **qa-eval:** drive all 14 sumo-qa skills to 100% PASS on promptfoo ([#40](https://github.com/sumithr/sumo-qa/issues/40)) ([b272e6f](https://github.com/sumithr/sumo-qa/commit/b272e6faf252e6b8f2ea0fd59a2763debc48ce9a))
* **qa-eval:** promptfoo skill-eval harness + repo hygiene + rubric calibration ([aacad73](https://github.com/sumithr/sumo-qa/commit/aacad734f0a943eb88d4e22d64d36a29c65fac69))
* **qa:** design LLM eval scenarios for all 14 skills + 24 MCP tools ([#34](https://github.com/sumithr/sumo-qa/issues/34)) ([13edaf0](https://github.com/sumithr/sumo-qa/commit/13edaf0be85ec7735424496fa6d9d7142d1f6b6b))
* **qa:** drop specialty_tools catalogue; tool picks via pure discovery ([#32](https://github.com/sumithr/sumo-qa/issues/32)) ([923564a](https://github.com/sumithr/sumo-qa/commit/923564a260f05fee7c7e802b62636801be39180c))
* **qa:** implement LLM eval harness with Codex as adversarial judge ([#36](https://github.com/sumithr/sumo-qa/issues/36)) ([71d748c](https://github.com/sumithr/sumo-qa/commit/71d748c6faddcc02c43ca33f3ab9f085b94b027f))
* **qa:** Phase 1 quality baseline — purge dead code, lift coverage to 100%, harden CI ([#21](https://github.com/sumithr/sumo-qa/issues/21)) ([35f99d8](https://github.com/sumithr/sumo-qa/commit/35f99d835ebe21034656ac2705ce1003ac4ff4b3))
* **qa:** Phase 2 — drift guards + parser robustness via Hypothesis (fixes 2 real defects) ([#25](https://github.com/sumithr/sumo-qa/issues/25)) ([6e7819f](https://github.com/sumithr/sumo-qa/commit/6e7819f2354be85359b88c52294af41ac9464119))
* **qa:** Phase 3 — mutation testing baseline + 100%-killed drive + TDM freshness ([#26](https://github.com/sumithr/sumo-qa/issues/26)) ([3fb168e](https://github.com/sumithr/sumo-qa/commit/3fb168e435e89eaad2d9d8e7ff4c9f026b73349c))
* **qa:** Phase 4 — hardening + Claude Desktop host + effectiveness summary ([#28](https://github.com/sumithr/sumo-qa/issues/28)) ([627b4d8](https://github.com/sumithr/sumo-qa/commit/627b4d837cb22121d42a2347de8c00122eeca019))
* **qa:** Phase 4.2 — kill 26 real mutation survivors, suppress 7 equivalents ([#33](https://github.com/sumithr/sumo-qa/issues/33)) ([eae5d34](https://github.com/sumithr/sumo-qa/commit/eae5d342f11abbe67fd76e532a26c23e44c8fe54))


### Bug Fixes

* **deps:** bump pytest to 9.0.3 (CVE-2025-71176) ([#24](https://github.com/sumithr/sumo-qa/issues/24)) ([4b8d276](https://github.com/sumithr/sumo-qa/commit/4b8d276130fe0daa486369fa764ca5bd513b95fe))
* **qa:** move assess_freshness pragma to the Call line ([#35](https://github.com/sumithr/sumo-qa/issues/35)) ([035d60f](https://github.com/sumithr/sumo-qa/commit/035d60f09d8ab030dcbfe57974a53fafd64a9280))
* untrack plugin manifests carrying author personal info ([#31](https://github.com/sumithr/sumo-qa/issues/31)) ([d738d77](https://github.com/sumithr/sumo-qa/commit/d738d7785f2afe0ca02aad0a49c8831682e004bf))


### Documentation

* align README + docs with what sumo-qa actually does ([#23](https://github.com/sumithr/sumo-qa/issues/23)) ([66c22ca](https://github.com/sumithr/sumo-qa/commit/66c22ca904ba3321fecc88a10cb29684cf8cf861))
* drop redundant Python-version enumeration ([#20](https://github.com/sumithr/sumo-qa/issues/20)) ([cd639b0](https://github.com/sumithr/sumo-qa/commit/cd639b0e79ee47a38f72fbc5305d59f871c1a6e8))


### Miscellaneous Chores

* pre-commit hooks for ruff + pytest ([#22](https://github.com/sumithr/sumo-qa/issues/22)) ([33dc70d](https://github.com/sumithr/sumo-qa/commit/33dc70d28483f88ff0d6181bf115c251c4cbcec1))
* **qa:** baseline eval run results (6/25 PASS = 24%) + rubric calibration ([#37](https://github.com/sumithr/sumo-qa/issues/37)) ([017be21](https://github.com/sumithr/sumo-qa/commit/017be2123a8640d325769f20978094529272bd73))
* **qa:** eval iteration to 13/25 (52%) — multi-turn architecture is the gap ([#38](https://github.com/sumithr/sumo-qa/issues/38)) ([f34adb6](https://github.com/sumithr/sumo-qa/commit/f34adb61013aab01d17f3adfeb9c47f4616e09a4))


### Continuous Integration

* **release:** use PAT + enable auto-merge on release-please PRs ([#43](https://github.com/sumithr/sumo-qa/issues/43)) ([2ad4ac5](https://github.com/sumithr/sumo-qa/commit/2ad4ac5ceaa0cb00efa57dd9f7943493f1a2f16a))
* wire up release-please for auto-versioning, changelog + PyPI deploy ([#41](https://github.com/sumithr/sumo-qa/issues/41)) ([4eba76c](https://github.com/sumithr/sumo-qa/commit/4eba76c466084be48fb81120ae67b46c2787b8a0))
