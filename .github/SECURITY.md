# Security Policy

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Report privately through GitHub's [private vulnerability reporting](https://github.com/sumithr/sumo-qa/security/advisories/new):

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Fill in the advisory form with as much detail as you can.

This routes the report straight to the maintainer without exposing it publicly, and lets us coordinate a fix and disclosure with you privately.

Please include, where possible:

- The affected version (`pip show sumo-qa` / the plugin version).
- A description of the issue and its impact.
- Steps to reproduce, or a proof of concept.
- Any suggested mitigation.

## Supported versions

sumo-qa is released continuously; only the latest published version on [PyPI](https://pypi.org/project/sumo-qa/) receives security fixes. Please upgrade to the latest release before reporting, in case the issue is already resolved.

| Version | Supported |
| ------- | --------- |
| Latest release | ✅ |
| Older releases | ❌ |

## Response

We aim to acknowledge a valid report within a few days and will keep you updated as we investigate and prepare a fix. Once a fix is released we will publish a security advisory crediting the reporter, unless you ask to remain anonymous.

## Verifying a release

Each GitHub release carries the wheel, the sdist and three evidence files:

- `SHA256SUMS`: the SHA-256 of every other release file.
- `sbom.cdx.json`: a CycloneDX SBOM of the wheel installed with the hashed runtime lock `.github/release/runtime-requirements.txt` on the release runner (Linux, CPython 3.13). It is that one resolution: dependencies gated on an older Python (such as `tomli`) or on another platform (such as `pywin32` on Windows) are not in it. Every dependency is installed with its hash checked against the lock and without dependency resolution, the wheel against the digest the build job recorded, and `pip check` must pass before the SBOM is generated. Hash pinning proves which artifacts were installed, not that they are benign: a locked dependency's import hooks run while the SBOM is generated, so the SBOM is an inventory of the locked set, not a malware check.
- `build-info.json`: source commit and ref, workflow run, runner, Python, the exact build-tool versions and the package digests.

Every file listed in `SHA256SUMS` has a signed build-provenance attestation from `.github/workflows/release.yml`, and the wheel and sdist also have an SBOM attestation. Pass `--source-ref` so only an attestation from the release tag counts: a manual dry run of the workflow from another branch also signs attestations, with that branch as the source ref. The packages on PyPI are the same bytes and carry PyPI's own trusted-publishing attestations.

```sh
VERSION=0.73.0   # the release to check
gh release download "v$VERSION" --repo sumithr/sumo-qa --dir "sumo-qa-$VERSION"
cd "sumo-qa-$VERSION"
sha256sum --check SHA256SUMS   # macOS: shasum -a 256 --check SHA256SUMS

# Provenance: built by release.yml in this repo from the release tag, on a
# GitHub-hosted runner.
gh attestation verify "sumo_qa-$VERSION-py3-none-any.whl" --repo sumithr/sumo-qa \
  --signer-workflow sumithr/sumo-qa/.github/workflows/release.yml \
  --source-ref "refs/tags/v$VERSION" --deny-self-hosted-runners

# SBOM: sbom.cdx.json is attested for this exact package digest.
gh attestation verify "sumo_qa-$VERSION-py3-none-any.whl" --repo sumithr/sumo-qa \
  --signer-workflow sumithr/sumo-qa/.github/workflows/release.yml \
  --source-ref "refs/tags/v$VERSION" --deny-self-hosted-runners \
  --predicate-type https://cyclonedx.org/bom
```

The same `gh attestation verify` commands work on a wheel fetched with `pip download sumo-qa==$VERSION --no-deps`. From a checkout, `python scripts/release_evidence.py verify "sumo-qa-$VERSION"` repeats the release gate's digest, SBOM and build-info checks.
