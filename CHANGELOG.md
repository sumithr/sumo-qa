# Changelog

## [0.9.1](https://github.com/sumithr/sumo-qa/compare/v0.9.0...v0.9.1) (2026-05-22)


### Bug Fixes

* **ci:** keep stdin open until tools/list received [regression-first] ([#141](https://github.com/sumithr/sumo-qa/issues/141)) ([4df0afa](https://github.com/sumithr/sumo-qa/commit/4df0afa2625c2c8a4f984234cba46df1b6c8520e))

## [0.9.0](https://github.com/sumithr/sumo-qa/compare/v0.8.0...v0.9.0) (2026-05-22)


### Features

* **ci:** add markdown drift gate + clarify plugin install in README ([#139](https://github.com/sumithr/sumo-qa/issues/139)) ([5abc428](https://github.com/sumithr/sumo-qa/commit/5abc428c84c22e11ffcbfca893f03523d8a06031))

## [0.8.0](https://github.com/sumithr/sumo-qa/compare/v0.7.1...v0.8.0) (2026-05-21)


### Features

* **doctor:** add sumo-qa-doctor read-only diagnostics CLI ([#135](https://github.com/sumithr/sumo-qa/issues/135)) ([20c7d2a](https://github.com/sumithr/sumo-qa/commit/20c7d2a9e25df0e26da1b4bda2cd45a3f0661102))

## [0.7.1](https://github.com/sumithr/sumo-qa/compare/v0.7.0...v0.7.1) (2026-05-21)


### Bug Fixes

* **ci:** guard fromJSON against empty release-please output ([#131](https://github.com/sumithr/sumo-qa/issues/131)) ([4bd7919](https://github.com/sumithr/sumo-qa/commit/4bd791908e10b82b55c96a2da088c16c664336d8))

## [0.7.0](https://github.com/sumithr/sumo-qa/compare/v0.6.5...v0.7.0) (2026-05-21)


### Features

* **packaging:** host-neutral plugin folders from canonical pyproject source ([#128](https://github.com/sumithr/sumo-qa/issues/128)) ([c75fb2e](https://github.com/sumithr/sumo-qa/commit/c75fb2edb2a4fc409c5af4b50e6bf7af65e0eceb))


### Bug Fixes

* **ci:** use actions/checkout for release-please branch regen ([#130](https://github.com/sumithr/sumo-qa/issues/130)) ([fa6d726](https://github.com/sumithr/sumo-qa/commit/fa6d72668614eb71228cd94e4a5a485d437ea56d))

## [0.6.5](https://github.com/sumithr/sumo-qa/compare/v0.6.4...v0.6.5) (2026-05-20)


### Documentation

* add support-specific issue templates ([f40b5e5](https://github.com/sumithr/sumo-qa/commit/f40b5e5c1fc4755a940d2c7c87d9f391134bae47))
* **issue-templates:** use real sumo-qa tool names in placeholders ([38628ff](https://github.com/sumithr/sumo-qa/commit/38628ff098c8c58fc7cd4e459a2f26a6a53aa440))

## [0.6.4](https://github.com/sumithr/sumo-qa/compare/v0.6.3...v0.6.4) (2026-05-20)


### Bug Fixes

* clean pytest warning noise ([255ba06](https://github.com/sumithr/sumo-qa/commit/255ba06fde26d634e92eb01297677af014bb1a35))

## [0.6.3](https://github.com/sumithr/sumo-qa/compare/v0.6.2...v0.6.3) (2026-05-20)


### Continuous Integration

* expand install smoke host coverage ([3bd2f95](https://github.com/sumithr/sumo-qa/commit/3bd2f957b2c359ef2ebf1fc0a22c1035f89e03f3))
* **install-smoke:** assert Claude Code host wiring with temp HOME ([4c95f64](https://github.com/sumithr/sumo-qa/commit/4c95f64c62d7d8d39dd99c52ad11700e01dba75c))

## [0.6.2](https://github.com/sumithr/sumo-qa/compare/v0.6.1...v0.6.2) (2026-05-20)


### Tests

* pin tools/list snapshot to catch contract drift ([#121](https://github.com/sumithr/sumo-qa/issues/121)) ([b36e887](https://github.com/sumithr/sumo-qa/commit/b36e8877fba4d6e08a97ac8f7f8e681245eac422))

## [0.6.1](https://github.com/sumithr/sumo-qa/compare/v0.6.0...v0.6.1) (2026-05-20)


### Bug Fixes

* **installer:** JSON-RPC + tools/list verification ([#76](https://github.com/sumithr/sumo-qa/issues/76)) ([#114](https://github.com/sumithr/sumo-qa/issues/114)) ([35d28b7](https://github.com/sumithr/sumo-qa/commit/35d28b7d7549e8325cd496620f91e9eff02747a4))

## [0.6.0](https://github.com/sumithr/sumo-qa/compare/v0.5.8...v0.6.0) (2026-05-20)


### Features

* add outputSchema to 8 structured MCP tools ([#112](https://github.com/sumithr/sumo-qa/issues/112)) ([44d770c](https://github.com/sumithr/sumo-qa/commit/44d770c0222ba09472902ebece8252eb329467c8))

## [0.5.8](https://github.com/sumithr/sumo-qa/compare/v0.5.7...v0.5.8) (2026-05-20)


### Tests

* **installer:** close idempotency gaps for Claude Desktop and VS Code ([#113](https://github.com/sumithr/sumo-qa/issues/113)) ([d28be6a](https://github.com/sumithr/sumo-qa/commit/d28be6a5341892c0ddb9b1e2c3324e8d3813b67a))

## [0.5.7](https://github.com/sumithr/sumo-qa/compare/v0.5.6...v0.5.7) (2026-05-20)


### Bug Fixes

* **ci:** use mutmut console-script wrapper to avoid trampoline double-import ([#117](https://github.com/sumithr/sumo-qa/issues/117)) ([888b3df](https://github.com/sumithr/sumo-qa/commit/888b3df1aeeaf2d4f7b20a962c99ea93e435002f))

## [0.5.6](https://github.com/sumithr/sumo-qa/compare/v0.5.5...v0.5.6) (2026-05-20)


### Bug Fixes

* **mutation:** restore gate; close 5/19 survivors; add pre-push hook ([#115](https://github.com/sumithr/sumo-qa/issues/115)) ([8e098ea](https://github.com/sumithr/sumo-qa/commit/8e098eaf3874e457017daa32a8cf244dee81d7d8))

## [0.5.5](https://github.com/sumithr/sumo-qa/compare/v0.5.4...v0.5.5) (2026-05-20)


### Continuous Integration

* **mutation:** pin to Python 3.12 to dodge mutmut+3.13 crash ([#109](https://github.com/sumithr/sumo-qa/issues/109)) ([e1ccf85](https://github.com/sumithr/sumo-qa/commit/e1ccf85cf7e4e23741b10491a2e88955f36e9068))

## [0.5.4](https://github.com/sumithr/sumo-qa/compare/v0.5.3...v0.5.4) (2026-05-20)


### Continuous Integration

* align workflows with the documented pip install path ([#105](https://github.com/sumithr/sumo-qa/issues/105)) ([91dadb1](https://github.com/sumithr/sumo-qa/commit/91dadb1c8ed226e1ba2d2ef36f0e8b624fee1331))

## [0.5.3](https://github.com/sumithr/sumo-qa/compare/v0.5.2...v0.5.3) (2026-05-19)


### Miscellaneous Chores

* add Claude Code config for project-shared QA automations ([#100](https://github.com/sumithr/sumo-qa/issues/100)) ([d353e41](https://github.com/sumithr/sumo-qa/commit/d353e4145fba0ce792919ad1403d1669fb90c5a2))

## [0.5.2](https://github.com/sumithr/sumo-qa/compare/v0.5.1...v0.5.2) (2026-05-18)


### Documentation

* add GitHub issue templates ([2b9339d](https://github.com/sumithr/sumo-qa/commit/2b9339d5d6c48e1ea558e0b5ddb4040182f71085))

## [0.5.1](https://github.com/sumithr/sumo-qa/compare/v0.5.0...v0.5.1) (2026-05-18)


### Documentation

* add Mermaid diagrams across user-facing docs ([#73](https://github.com/sumithr/sumo-qa/issues/73)) ([151fe63](https://github.com/sumithr/sumo-qa/commit/151fe63004e20085c2f707ee1b31b3ad6bd18bdb))

## [0.5.0](https://github.com/sumithr/sumo-qa/compare/v0.4.3...v0.5.0) (2026-05-18)


### Features

* removability gate in deciding-approach router ([#71](https://github.com/sumithr/sumo-qa/issues/71)) ([51f9e85](https://github.com/sumithr/sumo-qa/commit/51f9e85778fdf4c05ff1613e0d4d613410f91962))

## [0.4.3](https://github.com/sumithr/sumo-qa/compare/v0.4.2...v0.4.3) (2026-05-18)


### Build System

* **deps:** bump googleapis/release-please-action from 4 to 5 ([#65](https://github.com/sumithr/sumo-qa/issues/65)) ([bf118ae](https://github.com/sumithr/sumo-qa/commit/bf118aeea79013bb716f127ccb9a786fbe9873de))

## [0.4.2](https://github.com/sumithr/sumo-qa/compare/v0.4.1...v0.4.2) (2026-05-18)


### Miscellaneous Chores

* add install-smoke + shellcheck; remove orphan install.sh ([#68](https://github.com/sumithr/sumo-qa/issues/68)) ([76852f2](https://github.com/sumithr/sumo-qa/commit/76852f2024f07d46a5b463422b281e13d6eb23f5))

## [0.4.1](https://github.com/sumithr/sumo-qa/compare/v0.4.0...v0.4.1) (2026-05-18)


### Miscellaneous Chores

* align README lede with repo description ([#66](https://github.com/sumithr/sumo-qa/issues/66)) ([af3f509](https://github.com/sumithr/sumo-qa/commit/af3f509d07114451168ccda926499e52ff14405d))

## [0.4.0](https://github.com/sumithr/sumo-qa/compare/v0.3.5...v0.4.0) (2026-05-18)


### Features

* sumo-qa-validate + install-from-clone docs ([#63](https://github.com/sumithr/sumo-qa/issues/63)) ([8b7fcf5](https://github.com/sumithr/sumo-qa/commit/8b7fcf544db279cc6f7ad708e7a16ce87793afe6))

## [0.3.5](https://github.com/sumithr/sumo-qa/compare/v0.3.4...v0.3.5) (2026-05-18)


### Miscellaneous Chores

* gitignore uv.lock and remove dead release-please config ([#61](https://github.com/sumithr/sumo-qa/issues/61)) ([a23ad38](https://github.com/sumithr/sumo-qa/commit/a23ad3899dee0df953be8fa17d6b28a64498c4a2))

## [0.3.4](https://github.com/sumithr/sumo-qa/compare/v0.3.3...v0.3.4) (2026-05-18)


### Miscellaneous Chores

* have release-please sync uv.lock on version bump ([#58](https://github.com/sumithr/sumo-qa/issues/58)) ([c4d2ada](https://github.com/sumithr/sumo-qa/commit/c4d2adac42636da2ecf9dc469a0b6cd577338da5))

## [0.3.3](https://github.com/sumithr/sumo-qa/compare/v0.3.2...v0.3.3) (2026-05-18)


### Bug Fixes

* route external skill lifecycle through MCP with fluid CLI flow ([#57](https://github.com/sumithr/sumo-qa/issues/57)) ([b9ed4ca](https://github.com/sumithr/sumo-qa/commit/b9ed4ca8769606a86b84135f8b612e3e80063489))

## [0.3.2](https://github.com/sumithr/sumo-qa/compare/v0.3.1...v0.3.2) (2026-05-18)


### Bug Fixes

* load rules for canonical classifications ([#55](https://github.com/sumithr/sumo-qa/issues/55)) ([a7e5035](https://github.com/sumithr/sumo-qa/commit/a7e503539ba2c9c45c8e7a82d2547ccb86ee36a8))

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
