# Changelog

## [0.55.0](https://github.com/sumithr/sumo-qa/compare/v0.54.0...v0.55.0) (2026-07-13)


### Features

* **repo-map:** add C/C++ include resolver to the import-edge layer ([#359](https://github.com/sumithr/sumo-qa/issues/359)) ([#468](https://github.com/sumithr/sumo-qa/issues/468)) ([3034810](https://github.com/sumithr/sumo-qa/commit/30348101c4df4fda787ccaa5093ae0ebcaee2979))
* **repo-map:** add Rust import-edge resolver ([#358](https://github.com/sumithr/sumo-qa/issues/358)) ([#482](https://github.com/sumithr/sumo-qa/issues/482)) ([7a27120](https://github.com/sumithr/sumo-qa/commit/7a27120c889365be8c78b17e918da2c65cf70c9c))

## [0.54.0](https://github.com/sumithr/sumo-qa/compare/v0.53.0...v0.54.0) (2026-07-13)


### Features

* **repo-map:** add C# import-edge resolver ([#362](https://github.com/sumithr/sumo-qa/issues/362)) ([#480](https://github.com/sumithr/sumo-qa/issues/480)) ([c78f398](https://github.com/sumithr/sumo-qa/commit/c78f398c336ba33a1b2df1ba6df111ecd2cfeda4))
* **repo-map:** add PHP import-edge resolver ([#361](https://github.com/sumithr/sumo-qa/issues/361)) ([#479](https://github.com/sumithr/sumo-qa/issues/479)) ([bfb63e9](https://github.com/sumithr/sumo-qa/commit/bfb63e96d3abe9ac3bae4bae456231f8bb6e7159))

## [0.53.0](https://github.com/sumithr/sumo-qa/compare/v0.52.0...v0.53.0) (2026-07-13)


### Features

* **repo-map:** add Go import-edge resolver ([#356](https://github.com/sumithr/sumo-qa/issues/356)) ([#478](https://github.com/sumithr/sumo-qa/issues/478)) ([64eb922](https://github.com/sumithr/sumo-qa/commit/64eb922f20840e7df002f7e5218fbaca156f3f86))
* **repo-map:** add Ruby import-edge resolver ([#360](https://github.com/sumithr/sumo-qa/issues/360)) ([#477](https://github.com/sumithr/sumo-qa/issues/477)) ([24364ec](https://github.com/sumithr/sumo-qa/commit/24364ece06447b97214a93dfdd7b81196084fcca))

## [0.52.0](https://github.com/sumithr/sumo-qa/compare/v0.51.3...v0.52.0) (2026-07-13)


### Features

* **analysis:** add semantic code analysis adapters for QA recommendations ([#212](https://github.com/sumithr/sumo-qa/issues/212)) ([#490](https://github.com/sumithr/sumo-qa/issues/490)) ([24b3abc](https://github.com/sumithr/sumo-qa/commit/24b3abc7814e4216004f27d21c6e7ccbcddbb362))
* **conformance:** add cross-model conformance checks for QA routing and outputs ([#214](https://github.com/sumithr/sumo-qa/issues/214)) ([#476](https://github.com/sumithr/sumo-qa/issues/476)) ([895cde1](https://github.com/sumithr/sumo-qa/commit/895cde10f54bb0d94f181a5f7e9948b03e4840e6))
* **gate-evidence:** add evidence-backed gate reporting for QA workflow claims ([#213](https://github.com/sumithr/sumo-qa/issues/213)) ([#486](https://github.com/sumithr/sumo-qa/issues/486)) ([05a676d](https://github.com/sumithr/sumo-qa/commit/05a676dd6f6131bbf781389a0a753f7cdfab9573))
* **repo-map:** add Java import-edge resolver ([#357](https://github.com/sumithr/sumo-qa/issues/357)) ([#469](https://github.com/sumithr/sumo-qa/issues/469)) ([9583754](https://github.com/sumithr/sumo-qa/commit/95837549573c8716d6173ea6d92ec64ee015690d))
* **repo-map:** add TypeScript/JavaScript import resolver ([#355](https://github.com/sumithr/sumo-qa/issues/355)) ([#481](https://github.com/sumithr/sumo-qa/issues/481)) ([568eb38](https://github.com/sumithr/sumo-qa/commit/568eb3875f1a6f1e571813e3c1081235c51b09c1))
* **repo-map:** rank affected nodes by connecting-edge confidence in diff-impact ([#363](https://github.com/sumithr/sumo-qa/issues/363)) ([#475](https://github.com/sumithr/sumo-qa/issues/475)) ([9e6e426](https://github.com/sumithr/sumo-qa/commit/9e6e4268ceb59d169ced7583e2f48fd3eaf39718))
* **skill-serving:** add configurable output verbosity/strictness profiles ([#215](https://github.com/sumithr/sumo-qa/issues/215)) ([#471](https://github.com/sumithr/sumo-qa/issues/471)) ([577527e](https://github.com/sumithr/sumo-qa/commit/577527e78f869d22a7c8a754e8d60d3b2b355605))

## [0.51.3](https://github.com/sumithr/sumo-qa/compare/v0.51.2...v0.51.3) (2026-07-13)


### Bug Fixes

* **repo-map:** target the tree-sitter-language-pack 1.12.5 upstream binding ([#491](https://github.com/sumithr/sumo-qa/issues/491)) ([#492](https://github.com/sumithr/sumo-qa/issues/492)) ([d11c742](https://github.com/sumithr/sumo-qa/commit/d11c742869665832965faa45538215b91d40060d))

## [0.51.2](https://github.com/sumithr/sumo-qa/compare/v0.51.1...v0.51.2) (2026-06-28)


### Bug Fixes

* **ci:** skip the editable project in pip-audit so release branches don't fail ([#466](https://github.com/sumithr/sumo-qa/issues/466)) ([5def18f](https://github.com/sumithr/sumo-qa/commit/5def18fec508bf85d98d483ff14c1440d93efbb2))

## [0.51.1](https://github.com/sumithr/sumo-qa/compare/v0.51.0...v0.51.1) (2026-06-23)


### Bug Fixes

* **deps:** floor vulnerable transitive deps and mirror pip-audit in CI ([#464](https://github.com/sumithr/sumo-qa/issues/464)) ([2536376](https://github.com/sumithr/sumo-qa/commit/2536376029c67bb2ede4369a0ef9dbdbd9d3c472))

## [0.51.0](https://github.com/sumithr/sumo-qa/compare/v0.50.3...v0.51.0) (2026-06-22)


### Features

* **repo-map:** add language-agnostic imports edge layer via tree-sitter ([#460](https://github.com/sumithr/sumo-qa/issues/460)) ([f3a7f0e](https://github.com/sumithr/sumo-qa/commit/f3a7f0e994d3d45662076c1ae391224ab8af988b))

## [0.50.3](https://github.com/sumithr/sumo-qa/compare/v0.50.2...v0.50.3) (2026-06-21)


### Bug Fixes

* serve over-cap skill bodies as a progressive-loading pointer ([#393](https://github.com/sumithr/sumo-qa/issues/393)) ([#450](https://github.com/sumithr/sumo-qa/issues/450)) ([13f51aa](https://github.com/sumithr/sumo-qa/commit/13f51aa35453e6acd49a983e2cf0140bd63bf958))

## [0.50.2](https://github.com/sumithr/sumo-qa/compare/v0.50.1...v0.50.2) (2026-06-21)


### Bug Fixes

* version the diff-impact artifact and align README host claims ([#453](https://github.com/sumithr/sumo-qa/issues/453)) ([b7d4bb2](https://github.com/sumithr/sumo-qa/commit/b7d4bb2c6151511873eab36fbe82cf7e0c175a8b)), closes [#154](https://github.com/sumithr/sumo-qa/issues/154)

## [0.50.1](https://github.com/sumithr/sumo-qa/compare/v0.50.0...v0.50.1) (2026-06-21)


### Build System

* **deps-dev:** bump undici from 7.25.0 to 7.28.0 ([#446](https://github.com/sumithr/sumo-qa/issues/446)) ([3ba1116](https://github.com/sumithr/sumo-qa/commit/3ba11163e70de31838ef4019b51a80816f58c8c4))

## [0.50.0](https://github.com/sumithr/sumo-qa/compare/v0.49.1...v0.50.0) (2026-06-21)


### Features

* add security testing skill ([#443](https://github.com/sumithr/sumo-qa/issues/443)) ([84277eb](https://github.com/sumithr/sumo-qa/commit/84277eb8202f150b827fc6155f55dca2fb239c86))


### Tests

* **evals:** derive implementing-with-tdd technique allowlist from techniques.md headings ([#350](https://github.com/sumithr/sumo-qa/issues/350)) ([#442](https://github.com/sumithr/sumo-qa/issues/442)) ([0fa2341](https://github.com/sumithr/sumo-qa/commit/0fa2341678e8eaa1961488ec2e2d43108d04f9e9))

## [0.49.1](https://github.com/sumithr/sumo-qa/compare/v0.49.0...v0.49.1) (2026-06-16)


### Build System

* **deps-dev:** bump js-yaml from 4.1.1 to 4.2.0 ([#436](https://github.com/sumithr/sumo-qa/issues/436)) ([85f9b1c](https://github.com/sumithr/sumo-qa/commit/85f9b1c476bf294f75881de44078abd616b220b3))

## [0.49.0](https://github.com/sumithr/sumo-qa/compare/v0.48.3...v0.49.0) (2026-06-15)


### Features

* **skills:** include grounded security relevance in ordinary QA flows ([#282](https://github.com/sumithr/sumo-qa/issues/282)) ([#424](https://github.com/sumithr/sumo-qa/issues/424)) ([29e84ca](https://github.com/sumithr/sumo-qa/commit/29e84ca03f2085c337781bb1c6a7d1be90547628))

## [0.48.3](https://github.com/sumithr/sumo-qa/compare/v0.48.2...v0.48.3) (2026-06-15)


### Build System

* **deps-dev:** bump esbuild from 0.28.0 to 0.28.1 ([#411](https://github.com/sumithr/sumo-qa/issues/411)) ([875a2be](https://github.com/sumithr/sumo-qa/commit/875a2bea9ce617ec61bb46bd04db418d62d42f86))
* **deps-dev:** bump hono from 4.12.19 to 4.12.24 ([#338](https://github.com/sumithr/sumo-qa/issues/338)) ([5c31316](https://github.com/sumithr/sumo-qa/commit/5c31316171341b7f1a4552f982aa84955638e8df))
* **deps:** bump actions/setup-node from 5 to 6 ([#295](https://github.com/sumithr/sumo-qa/issues/295)) ([3f326e9](https://github.com/sumithr/sumo-qa/commit/3f326e9228eaea6e9b3a840dd045015d7bf9051d))

## [0.48.2](https://github.com/sumithr/sumo-qa/compare/v0.48.1...v0.48.2) (2026-06-15)


### Continuous Integration

* add an em-dash guard and clean em-dashes from the docs ([#423](https://github.com/sumithr/sumo-qa/issues/423)) ([8524639](https://github.com/sumithr/sumo-qa/commit/85246397d748d3d2ccb6b27f5c8981b1eae1eab8))

## [0.48.1](https://github.com/sumithr/sumo-qa/compare/v0.48.0...v0.48.1) (2026-06-14)


### Documentation

* rework README and demo around outcome-led QA workflows ([#417](https://github.com/sumithr/sumo-qa/issues/417)) ([8615477](https://github.com/sumithr/sumo-qa/commit/861547711a7289f701d342c3a3b84da83282fa9c))

## [0.48.0](https://github.com/sumithr/sumo-qa/compare/v0.47.0...v0.48.0) (2026-06-14)


### Features

* **report:** persist coverage/mutation into the QA report ([#409](https://github.com/sumithr/sumo-qa/issues/409)) ([cd90cc8](https://github.com/sumithr/sumo-qa/commit/cd90cc872987034d83ed49af65fc17d50719815a))

## [0.47.0](https://github.com/sumithr/sumo-qa/compare/v0.46.1...v0.47.0) (2026-06-14)


### Features

* **skills:** add flaky/failing test triage workflow ([#150](https://github.com/sumithr/sumo-qa/issues/150)) ([#421](https://github.com/sumithr/sumo-qa/issues/421)) ([9ce3842](https://github.com/sumithr/sumo-qa/commit/9ce3842250e621628a84af7e157ce30dfa18a9fe))

## [0.46.1](https://github.com/sumithr/sumo-qa/compare/v0.46.0...v0.46.1) (2026-06-14)


### Bug Fixes

* **installer:** derive REQUIRED_TOOL_NAMES from the live MCP registry ([#352](https://github.com/sumithr/sumo-qa/issues/352)) ([#419](https://github.com/sumithr/sumo-qa/issues/419)) ([95f0913](https://github.com/sumithr/sumo-qa/commit/95f0913a440f7548c10c7966370515929e0a3290))

## [0.46.0](https://github.com/sumithr/sumo-qa/compare/v0.45.0...v0.46.0) (2026-06-13)


### Features

* **skills:** add closed-loop regression workflow for concrete QA gaps ([#403](https://github.com/sumithr/sumo-qa/issues/403)) ([f2d0033](https://github.com/sumithr/sumo-qa/commit/f2d00339fce42c3f5f50ab74f84ed97d67210c3b))

## [0.45.0](https://github.com/sumithr/sumo-qa/compare/v0.44.0...v0.45.0) (2026-06-12)


### Features

* **report:** add polished local QA report (CLI + MCP) ([#381](https://github.com/sumithr/sumo-qa/issues/381)) ([a00f07b](https://github.com/sumithr/sumo-qa/commit/a00f07b6ad6045540971fbe55e1ccd8766ea23bd))

## [0.44.0](https://github.com/sumithr/sumo-qa/compare/v0.43.0...v0.44.0) (2026-06-11)


### Features

* **skills:** consume coverage/mutation artifacts as supporting QA evidence ([#147](https://github.com/sumithr/sumo-qa/issues/147)) ([#397](https://github.com/sumithr/sumo-qa/issues/397)) ([38a0d05](https://github.com/sumithr/sumo-qa/commit/38a0d059dca374a3583bfbee4f236f09f21c3ddd))

## [0.43.0](https://github.com/sumithr/sumo-qa/compare/v0.42.0...v0.43.0) (2026-06-11)


### Features

* **scorecard:** add evidence-based QA readiness scorecard ([#151](https://github.com/sumithr/sumo-qa/issues/151)) ([#392](https://github.com/sumithr/sumo-qa/issues/392)) ([ad561d7](https://github.com/sumithr/sumo-qa/commit/ad561d72e40e0c374a443491d2017e32b51d5872))

## [0.42.0](https://github.com/sumithr/sumo-qa/compare/v0.41.0...v0.42.0) (2026-06-10)


### Features

* **install:** add one-command install/update/doctor wrappers (install.sh + install.ps1) ([#390](https://github.com/sumithr/sumo-qa/issues/390)) ([bbf81ab](https://github.com/sumithr/sumo-qa/commit/bbf81abaeb5b0fa65061b7b970aeb326b86f9385))

## [0.41.0](https://github.com/sumithr/sumo-qa/compare/v0.40.0...v0.41.0) (2026-06-10)


### Features

* **packaging:** generate .claude-plugin/marketplace.json for plugin marketplace install ([#388](https://github.com/sumithr/sumo-qa/issues/388)) ([26c8755](https://github.com/sumithr/sumo-qa/commit/26c87554e1c1f12752482d0045afa76175fca675))

## [0.40.0](https://github.com/sumithr/sumo-qa/compare/v0.39.1...v0.40.0) (2026-06-10)


### Features

* **distribution:** add marketplace metadata, assets, and per-host install docs ([#84](https://github.com/sumithr/sumo-qa/issues/84)) ([#377](https://github.com/sumithr/sumo-qa/issues/377)) ([130fc0a](https://github.com/sumithr/sumo-qa/commit/130fc0a70a028bdcd71710a240ed1c0a76d76715))


### Bug Fixes

* **release:** sync marketplace preview after version bump ([#385](https://github.com/sumithr/sumo-qa/issues/385)) ([3286054](https://github.com/sumithr/sumo-qa/commit/32860544b2cd3241930c8401e981aa838087c969))

## [0.39.1](https://github.com/sumithr/sumo-qa/compare/v0.39.0...v0.39.1) (2026-06-09)


### Tests

* **evals:** tune local cheap-tier via judge/candidate bake-off + provider-file pattern ([#374](https://github.com/sumithr/sumo-qa/issues/374)) ([f8a0a97](https://github.com/sumithr/sumo-qa/commit/f8a0a979b76f38b7e36ebc1bf85ea0558572bce8))

## [0.39.0](https://github.com/sumithr/sumo-qa/compare/v0.38.0...v0.39.0) (2026-06-08)


### Features

* **export:** opt-in output_path file-write for export_test_cases ([#371](https://github.com/sumithr/sumo-qa/issues/371)) ([#372](https://github.com/sumithr/sumo-qa/issues/372)) ([46ff00b](https://github.com/sumithr/sumo-qa/commit/46ff00b89b6407cd6ed821343de322d9d9f742b7))

## [0.38.0](https://github.com/sumithr/sumo-qa/compare/v0.37.0...v0.38.0) (2026-06-08)


### Features

* **skills:** implementing-with-tdd retrospective regression + build-artifact technique ([#101](https://github.com/sumithr/sumo-qa/issues/101)/[#184](https://github.com/sumithr/sumo-qa/issues/184)) ([#340](https://github.com/sumithr/sumo-qa/issues/340)) ([7c83ea8](https://github.com/sumithr/sumo-qa/commit/7c83ea8d4a11330a358f8e0a00deee4e6aad0656))

## [0.37.0](https://github.com/sumithr/sumo-qa/compare/v0.36.0...v0.37.0) (2026-06-08)


### Features

* add explicit review feedback memory for recurring QA findings ([#145](https://github.com/sumithr/sumo-qa/issues/145)) ([#344](https://github.com/sumithr/sumo-qa/issues/344)) ([72bc88d](https://github.com/sumithr/sumo-qa/commit/72bc88ddab992120a710d39115f9168e1b887a0e))

## [0.36.0](https://github.com/sumithr/sumo-qa/compare/v0.35.1...v0.36.0) (2026-06-08)


### Features

* **skills:** reviewing-before-merge verification-evidence discipline ([#332](https://github.com/sumithr/sumo-qa/issues/332)/[#321](https://github.com/sumithr/sumo-qa/issues/321)/[#331](https://github.com/sumithr/sumo-qa/issues/331), addresses [#316](https://github.com/sumithr/sumo-qa/issues/316)) ([#339](https://github.com/sumithr/sumo-qa/issues/339)) ([990351f](https://github.com/sumithr/sumo-qa/commit/990351fef8a46f830874abb578c6c6938a3b9479))

## [0.35.1](https://github.com/sumithr/sumo-qa/compare/v0.35.0...v0.35.1) (2026-06-08)


### Tests

* **evals:** local-tier eval runner + judge-validation harness ([#366](https://github.com/sumithr/sumo-qa/issues/366)) ([c68b9a6](https://github.com/sumithr/sumo-qa/commit/c68b9a6bdb358d22ff8d670058d38403924a9a55))

## [0.35.0](https://github.com/sumithr/sumo-qa/compare/v0.34.1...v0.35.0) (2026-06-05)


### Features

* **export:** deterministic QA test-case export tool ([#148](https://github.com/sumithr/sumo-qa/issues/148)) ([#342](https://github.com/sumithr/sumo-qa/issues/342)) ([15b104a](https://github.com/sumithr/sumo-qa/commit/15b104a7c6febdf1f92b2f5d1e2a4926251d6d72))


### Bug Fixes

* **skill-manifest:** CommonMark-correct heading-fence parsing ([#297](https://github.com/sumithr/sumo-qa/issues/297)) ([#341](https://github.com/sumithr/sumo-qa/issues/341)) ([41875b3](https://github.com/sumithr/sumo-qa/commit/41875b359774ed0ab4bfe50a59b61d745d2e8752))


### Miscellaneous Chores

* **mutmut:** loud guard for subprocess-spawning test exclusions ([#195](https://github.com/sumithr/sumo-qa/issues/195)) ([#343](https://github.com/sumithr/sumo-qa/issues/343)) ([fd53a0d](https://github.com/sumithr/sumo-qa/commit/fd53a0d457ea60fe7df8fbb32e4926ab125ab256))

## [0.34.1](https://github.com/sumithr/sumo-qa/compare/v0.34.0...v0.34.1) (2026-06-04)


### Performance Improvements

* **server:** slim always-on tools/list (drop outputSchema + schema titles) ([#335](https://github.com/sumithr/sumo-qa/issues/335)) ([d0427bc](https://github.com/sumithr/sumo-qa/commit/d0427bc9492db1137a648b9c14618d3b1b193795))

## [0.34.0](https://github.com/sumithr/sumo-qa/compare/v0.33.0...v0.34.0) (2026-06-03)


### Features

* **skills:** combined reviewing-before-merge probes + [#299](https://github.com/sumithr/sumo-qa/issues/299) technique + [#276](https://github.com/sumithr/sumo-qa/issues/276) eval re-tier ([#333](https://github.com/sumithr/sumo-qa/issues/333)) ([e756317](https://github.com/sumithr/sumo-qa/commit/e7563170d0e419638594e6dcac47573322c03bf0))

## [0.33.0](https://github.com/sumithr/sumo-qa/compare/v0.32.0...v0.33.0) (2026-06-03)


### Features

* add acceptance-criteria coverage check to reviewing-before-merge ([#314](https://github.com/sumithr/sumo-qa/issues/314)) ([89ee562](https://github.com/sumithr/sumo-qa/commit/89ee562367ff267b9c0f8fd6785c714d96652f6f))

## [0.32.0](https://github.com/sumithr/sumo-qa/compare/v0.31.0...v0.32.0) (2026-06-03)


### Features

* add external-contract risk class to reviewing-before-merge ([#313](https://github.com/sumithr/sumo-qa/issues/313)) ([fc02455](https://github.com/sumithr/sumo-qa/commit/fc024553d4b6e21911f6bfccf25d47de83291200))

## [0.31.0](https://github.com/sumithr/sumo-qa/compare/v0.30.0...v0.31.0) (2026-06-03)


### Features

* add test_change vacuous-test probe to reviewing-before-merge ([#312](https://github.com/sumithr/sumo-qa/issues/312)) ([2a2563f](https://github.com/sumithr/sumo-qa/commit/2a2563f66afc24b31abb5b44b73c7b8813eee072))

## [0.30.0](https://github.com/sumithr/sumo-qa/compare/v0.29.0...v0.30.0) (2026-06-02)


### Features

* add product-grade CLI analyze and status commands ([#311](https://github.com/sumithr/sumo-qa/issues/311)) ([ac8c87a](https://github.com/sumithr/sumo-qa/commit/ac8c87aa27646487700347cf61c6900a5738cd73))


### Bug Fixes

* drive suffixed and A-B eval configs without cross-matching ([#315](https://github.com/sumithr/sumo-qa/issues/315)) ([88a7008](https://github.com/sumithr/sumo-qa/commit/88a70089157f1d00cbbb9b077822f25d6b937c5f))

## [0.29.0](https://github.com/sumithr/sumo-qa/compare/v0.28.0...v0.29.0) (2026-06-02)


### Features

* make sumo_qa_list_skill_manifests compact by default ([#308](https://github.com/sumithr/sumo-qa/issues/308)) ([cd9df02](https://github.com/sumithr/sumo-qa/commit/cd9df02f7fac67c639f51594756ce72f6a157406))

## [0.28.0](https://github.com/sumithr/sumo-qa/compare/v0.27.0...v0.28.0) (2026-06-02)


### Features

* **knowledge:** add per-entry and compact catalogue loaders ([#302](https://github.com/sumithr/sumo-qa/issues/302)) ([38ece06](https://github.com/sumithr/sumo-qa/commit/38ece06e8dce62f49326659eae756955ab30177f))
* **skills:** add content-hash digest + change-detection to partial skill loads ([#304](https://github.com/sumithr/sumo-qa/issues/304)) ([1f16916](https://github.com/sumithr/sumo-qa/commit/1f16916078dc6ed0454b24328d4547c789e650b6))
* **skills:** expose skill index as additive MCP resources/templates ([#303](https://github.com/sumithr/sumo-qa/issues/303)) ([0d8e662](https://github.com/sumithr/sumo-qa/commit/0d8e6626e53cdee8e8ec6f3e133a977008dc9b4e))


### Tests

* add cumulative token-budget tests + host docs for progressive skill loading ([#301](https://github.com/sumithr/sumo-qa/issues/301)) ([7ea5a82](https://github.com/sumithr/sumo-qa/commit/7ea5a824273b5b7536baa279509e3f07adfaae4a))

## [0.27.0](https://github.com/sumithr/sumo-qa/compare/v0.26.0...v0.27.0) (2026-06-02)


### Features

* **hooks:** add PostToolUse router for mutmut survivors and promptfoo FAILs ([#298](https://github.com/sumithr/sumo-qa/issues/298)) ([3eeca68](https://github.com/sumithr/sumo-qa/commit/3eeca6813325e888dda694530479055002f3858f))

## [0.26.0](https://github.com/sumithr/sumo-qa/compare/v0.25.0...v0.26.0) (2026-06-01)


### Features

* **skills:** add skill-manifest index + partial skill-context loader ([#285](https://github.com/sumithr/sumo-qa/issues/285)) ([#292](https://github.com/sumithr/sumo-qa/issues/292)) ([74d895f](https://github.com/sumithr/sumo-qa/commit/74d895fa5beb4b92d348e7799843204d1ff33896))

## [0.25.0](https://github.com/sumithr/sumo-qa/compare/v0.24.0...v0.25.0) (2026-06-01)


### Features

* **skills:** enforce repo-level / CI-reproducible tool setup ([#269](https://github.com/sumithr/sumo-qa/issues/269)) ([61ec92b](https://github.com/sumithr/sumo-qa/commit/61ec92b877c823ffb7f870307276a5068852c719))

## [0.24.0](https://github.com/sumithr/sumo-qa/compare/v0.23.0...v0.24.0) (2026-06-01)


### Features

* add host-neutral issue/PR context bundle for QA workflows ([#271](https://github.com/sumithr/sumo-qa/issues/271)) ([811e7e9](https://github.com/sumithr/sumo-qa/commit/811e7e9611ccdf8be683dfa9803ff6005c40603c))

## [0.23.0](https://github.com/sumithr/sumo-qa/compare/v0.22.0...v0.23.0) (2026-06-01)


### Features

* make repo-map test↔source mapping language-agnostic and auto-persist on first run ([#277](https://github.com/sumithr/sumo-qa/issues/277)) ([3af65e9](https://github.com/sumithr/sumo-qa/commit/3af65e9e7c299ffbe3ee06f5bd50068323871f62))

## [0.22.0](https://github.com/sumithr/sumo-qa/compare/v0.21.0...v0.22.0) (2026-06-01)


### Features

* **reviewing:** escalate UNPROVEN review risks into discriminating-input tests ([#272](https://github.com/sumithr/sumo-qa/issues/272)) ([ae2febb](https://github.com/sumithr/sumo-qa/commit/ae2febb17bf4ca8d822a1f2b5d250ca0136857fb))

## [0.21.0](https://github.com/sumithr/sumo-qa/compare/v0.20.3...v0.21.0) (2026-05-31)


### Features

* add risk-to-test traceability ledger ([#262](https://github.com/sumithr/sumo-qa/issues/262)) ([031abe7](https://github.com/sumithr/sumo-qa/commit/031abe70293e8dd80e8d4526f2f7a7a1c01c653d))

## [0.20.3](https://github.com/sumithr/sumo-qa/compare/v0.20.2...v0.20.3) (2026-05-30)


### Documentation

* de-specify repo docs to capability altitude ([#256](https://github.com/sumithr/sumo-qa/issues/256)) ([20b3ae9](https://github.com/sumithr/sumo-qa/commit/20b3ae938f029358ea08ce968eddf82c22059166))

## [0.20.2](https://github.com/sumithr/sumo-qa/compare/v0.20.1...v0.20.2) (2026-05-30)


### Continuous Integration

* fix release PR auto-merge to reliably bypass-merge ([#258](https://github.com/sumithr/sumo-qa/issues/258)) ([c90bdef](https://github.com/sumithr/sumo-qa/commit/c90bdef841f90aae12d10ecc01efa1e8990bc2e7))

## [0.20.1](https://github.com/sumithr/sumo-qa/compare/v0.20.0...v0.20.1) (2026-05-30)


### Tests

* add SKILL.md description-vs-body drift contract test ([#254](https://github.com/sumithr/sumo-qa/issues/254)) ([a09835d](https://github.com/sumithr/sumo-qa/commit/a09835d4c1b4008f08ebadf904ad8361a7c3cc51))


### Build System

* **deps:** bump axios and ibm-cloud-sdk-core ([#251](https://github.com/sumithr/sumo-qa/issues/251)) ([3acd924](https://github.com/sumithr/sumo-qa/commit/3acd924c146a7d7e4ea7d20172f0e444ddde1ea1))

## [0.20.0](https://github.com/sumithr/sumo-qa/compare/v0.19.0...v0.20.0) (2026-05-29)


### Features

* add sumo_qa_query_repo_map and wire repo-map evidence into QA skills ([#241](https://github.com/sumithr/sumo-qa/issues/241)) ([5fd54b3](https://github.com/sumithr/sumo-qa/commit/5fd54b31c6eac56c58e42731d7d836dd54aa57ad))

## [0.19.0](https://github.com/sumithr/sumo-qa/compare/v0.18.1...v0.19.0) (2026-05-29)


### Features

* add adversarial review-recall discovery pass + Codex-seeded eval corpus ([#236](https://github.com/sumithr/sumo-qa/issues/236)) ([#244](https://github.com/sumithr/sumo-qa/issues/244)) ([6b29e39](https://github.com/sumithr/sumo-qa/commit/6b29e396f63ff778755fd0374ecaabfa6e345973))
* enforce sumo-qa routing for QA-shaped requests on copilot ([#240](https://github.com/sumithr/sumo-qa/issues/240)) ([5d81db2](https://github.com/sumithr/sumo-qa/commit/5d81db2aa2b1a7d8e542b3d6af51c233123865e7))


### Continuous Integration

* fix release auto-merge race on required-check registration ([#250](https://github.com/sumithr/sumo-qa/issues/250)) ([44886a2](https://github.com/sumithr/sumo-qa/commit/44886a2ce622da24e40ee98b66de569a5dbfb710))

## [0.18.1](https://github.com/sumithr/sumo-qa/compare/v0.18.0...v0.18.1) (2026-05-29)


### Continuous Integration

* add upgrade-path smoke for the install pipeline ([#237](https://github.com/sumithr/sumo-qa/issues/237)) ([6601311](https://github.com/sumithr/sumo-qa/commit/66013112a4a6bf5c85dfecd1aab1c114e317820d))

## [0.18.0](https://github.com/sumithr/sumo-qa/compare/v0.17.0...v0.18.0) (2026-05-29)


### Features

* add deterministic repo-map scanner ([#155](https://github.com/sumithr/sumo-qa/issues/155) slice 2) ([#229](https://github.com/sumithr/sumo-qa/issues/229)) ([4415e73](https://github.com/sumithr/sumo-qa/commit/4415e73f25567d32c522233986c487d92d26b0f5))
* add sumo_qa_analyze_diff_impact diff-impact tool ([#156](https://github.com/sumithr/sumo-qa/issues/156) slice 4) ([#233](https://github.com/sumithr/sumo-qa/issues/233)) ([8ff6c9d](https://github.com/sumithr/sumo-qa/commit/8ff6c9d850aa2a0fd608d0e08bef92a18bd83e56))

## [0.17.0](https://github.com/sumithr/sumo-qa/compare/v0.16.1...v0.17.0) (2026-05-28)


### Features

* add repo-map schema models + validation envelope ([#222](https://github.com/sumithr/sumo-qa/issues/222)) ([6ad5964](https://github.com/sumithr/sumo-qa/commit/6ad596408edf095afaeb092832fa015c0e4373d5))

## [0.16.1](https://github.com/sumithr/sumo-qa/compare/v0.16.0...v0.16.1) (2026-05-28)


### Documentation

* simplify canonical install command and add manual uninstall ([#231](https://github.com/sumithr/sumo-qa/issues/231)) ([d20cf60](https://github.com/sumithr/sumo-qa/commit/d20cf606720003e0c223a5cfe1123b5375cd6144))

## [0.16.0](https://github.com/sumithr/sumo-qa/compare/v0.15.7...v0.16.0) (2026-05-28)


### Features

* add docs_change and test_change rule entries ([#217](https://github.com/sumithr/sumo-qa/issues/217)) ([18d9deb](https://github.com/sumithr/sumo-qa/commit/18d9deb909325c50e4f4b635afbe040f93b6ff44))


### Continuous Integration

* add scheduled smoke for external Skills CLI integration ([#226](https://github.com/sumithr/sumo-qa/issues/226)) ([af6304a](https://github.com/sumithr/sumo-qa/commit/af6304a67ff585289db282b186896b7b79aac2d6))

## [0.15.7](https://github.com/sumithr/sumo-qa/compare/v0.15.6...v0.15.7) (2026-05-28)


### Tests

* add deterministic trigger-routing harness for the 14 skill tools ([#219](https://github.com/sumithr/sumo-qa/issues/219)) ([eca72ca](https://github.com/sumithr/sumo-qa/commit/eca72ca8cee84f37e42ce5fe530bac77334dd656))

## [0.15.6](https://github.com/sumithr/sumo-qa/compare/v0.15.5...v0.15.6) (2026-05-27)


### Continuous Integration

* add least-privilege permissions to test and release workflows ([#209](https://github.com/sumithr/sumo-qa/issues/209)) ([cc333ff](https://github.com/sumithr/sumo-qa/commit/cc333ff6098d140ddf3a5443532322ced85c37fd))

## [0.15.5](https://github.com/sumithr/sumo-qa/compare/v0.15.4...v0.15.5) (2026-05-27)


### Bug Fixes

* refuse unsafe Claude Desktop config on macOS ([#193](https://github.com/sumithr/sumo-qa/issues/193)) ([cc59f40](https://github.com/sumithr/sumo-qa/commit/cc59f404a9f39188122e6ff2ca77c04c0f1f26b7))


### Continuous Integration

* bump actions/checkout to v5 ([#207](https://github.com/sumithr/sumo-qa/issues/207)) ([ba05cd7](https://github.com/sumithr/sumo-qa/commit/ba05cd7190ac0eaa62c5f50e33b39b26c365c330))

## [0.15.4](https://github.com/sumithr/sumo-qa/compare/v0.15.3...v0.15.4) (2026-05-27)


### Documentation

* add code of conduct, contributing, security policy, and PR template ([#203](https://github.com/sumithr/sumo-qa/issues/203)) ([1118aea](https://github.com/sumithr/sumo-qa/commit/1118aea825be81aa00053982df190d4791d99a03))

## [0.15.3](https://github.com/sumithr/sumo-qa/compare/v0.15.2...v0.15.3) (2026-05-27)


### Continuous Integration

* fix release-merge race on check-run registration ([#204](https://github.com/sumithr/sumo-qa/issues/204)) ([7381445](https://github.com/sumithr/sumo-qa/commit/738144509d69c52022ae44f1841d0a8a813a5163))

## [0.15.2](https://github.com/sumithr/sumo-qa/compare/v0.15.1...v0.15.2) (2026-05-27)


### Continuous Integration

* simplify release auto-merge to a bypass-actor merge ([#201](https://github.com/sumithr/sumo-qa/issues/201)) ([7043006](https://github.com/sumithr/sumo-qa/commit/704300628a72887ca8b8f3f17cf12773328d3a44))

## [0.15.1](https://github.com/sumithr/sumo-qa/compare/v0.15.0...v0.15.1) (2026-05-27)


### Code Refactoring

* **deciding-approach:** lazy-load catalogues, document responsibilities ([#189](https://github.com/sumithr/sumo-qa/issues/189)) ([3a2929d](https://github.com/sumithr/sumo-qa/commit/3a2929dabf20173cb660be88f00ad89d058d9627))


### Continuous Integration

* let release automation bypass approval after checks ([#196](https://github.com/sumithr/sumo-qa/issues/196)) ([6156e19](https://github.com/sumithr/sumo-qa/commit/6156e19ed70ccebb3179e987b489f17bbd479094))
* wait for release PR checks to appear ([#197](https://github.com/sumithr/sumo-qa/issues/197)) ([0fd3489](https://github.com/sumithr/sumo-qa/commit/0fd3489eb409c770ac3051edd2ab587417eba1a5))
* wait for release PR head check runs ([#198](https://github.com/sumithr/sumo-qa/issues/198)) ([273da6f](https://github.com/sumithr/sumo-qa/commit/273da6f63af27ba812252096c361a4d0d5a18d56))
* wait on release workflow head checks ([#199](https://github.com/sumithr/sumo-qa/issues/199)) ([6979be8](https://github.com/sumithr/sumo-qa/commit/6979be861f604aea77dcaeeaf2d67ef103182fae))

## [0.15.0](https://github.com/sumithr/sumo-qa/compare/v0.14.0...v0.15.0) (2026-05-27)


### Features

* scenario-aware enrichment in explain_test_data_requirements ([#185](https://github.com/sumithr/sumo-qa/issues/185)) ([273e2a4](https://github.com/sumithr/sumo-qa/commit/273e2a4f093c2d0e4dfa946364cfc4dc71996b71))

## [0.14.0](https://github.com/sumithr/sumo-qa/compare/v0.13.0...v0.14.0) (2026-05-27)


### Features

* ship PEP 561 py.typed marker and add mypy static type checking ([#182](https://github.com/sumithr/sumo-qa/issues/182)) ([2fd78ec](https://github.com/sumithr/sumo-qa/commit/2fd78ecea84282f4cca4c54b0ff44b2ee84eaa41))

## [0.13.0](https://github.com/sumithr/sumo-qa/compare/v0.12.0...v0.13.0) (2026-05-26)


### Features

* tech-agnostic surface probes for contract, config & async changes ([#179](https://github.com/sumithr/sumo-qa/issues/179)) ([3d9018d](https://github.com/sumithr/sumo-qa/commit/3d9018d39e860aae21fd95b8bda0050bcfabdc73))

## [0.12.0](https://github.com/sumithr/sumo-qa/compare/v0.11.2...v0.12.0) (2026-05-26)


### Features

* add sumo_qa_capabilities discovery tool ([#177](https://github.com/sumithr/sumo-qa/issues/177)) ([e8df4fa](https://github.com/sumithr/sumo-qa/commit/e8df4fa990dbdcc5fbef79630690ba455153f0e5)), closes [#87](https://github.com/sumithr/sumo-qa/issues/87)

## [0.11.2](https://github.com/sumithr/sumo-qa/compare/v0.11.1...v0.11.2) (2026-05-26)


### Performance Improvements

* reduce SKILL.md token weight across the eight remaining sumo-qa skills ([#173](https://github.com/sumithr/sumo-qa/issues/173)) ([77264f5](https://github.com/sumithr/sumo-qa/commit/77264f5e5c2a69d2fd86dca728e32c2a8a2cb98f)), closes [#172](https://github.com/sumithr/sumo-qa/issues/172)

## [0.11.1](https://github.com/sumithr/sumo-qa/compare/v0.11.0...v0.11.1) (2026-05-26)


### Performance Improvements

* reduce SKILL.md token weight across the six heaviest sumo-qa skills ([#170](https://github.com/sumithr/sumo-qa/issues/170)) ([bba230c](https://github.com/sumithr/sumo-qa/commit/bba230c621144f135cd1319c7dcbbe26bbac385a))

## [0.11.0](https://github.com/sumithr/sumo-qa/compare/v0.10.0...v0.11.0) (2026-05-26)


### Features

* unify external-skill discovery; ingestion reuses it ([#166](https://github.com/sumithr/sumo-qa/issues/166)) ([d7f413e](https://github.com/sumithr/sumo-qa/commit/d7f413ed8ec9f265ab4c073aa4c04c80d5e0979d))

## [0.10.0](https://github.com/sumithr/sumo-qa/compare/v0.9.4...v0.10.0) (2026-05-26)


### Features

* runtime ingestion of custom QA knowledge packs ([#164](https://github.com/sumithr/sumo-qa/issues/164)) ([2a35aa4](https://github.com/sumithr/sumo-qa/commit/2a35aa4fac2e52cdc5871be94ee4d2107f92abe7))

## [0.9.4](https://github.com/sumithr/sumo-qa/compare/v0.9.3...v0.9.4) (2026-05-25)


### Build System

* **deps:** bump actions/setup-python from 5 to 6 ([ed5d1e6](https://github.com/sumithr/sumo-qa/commit/ed5d1e6b9c5948a8ea5253464257186048722a58))

## [0.9.3](https://github.com/sumithr/sumo-qa/compare/v0.9.2...v0.9.3) (2026-05-25)


### Bug Fixes

* **ci:** plugin-dir handshake — stdin contract + auto-discover adapters ([#159](https://github.com/sumithr/sumo-qa/issues/159)) ([417cb39](https://github.com/sumithr/sumo-qa/commit/417cb39dd48f25fb6d953b1003243a7e7e3e6337))

## [0.9.2](https://github.com/sumithr/sumo-qa/compare/v0.9.1...v0.9.2) (2026-05-25)


### Bug Fixes

* **skills:** rewrite skill bodies to host-neutral capability contracts ([#143](https://github.com/sumithr/sumo-qa/issues/143)) ([c95367f](https://github.com/sumithr/sumo-qa/commit/c95367f14917c888ea40bc089c8d92b577963954))

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
