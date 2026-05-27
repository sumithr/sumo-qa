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
