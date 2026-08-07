# Security Policy

## Reporting a Vulnerability

**Do not open a public issue for a security vulnerability.**

Report it through a [private security advisory](https://github.com/Twodragon0/investing/security/advisories/new). Include:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix, if you have one

### Response timeline

| Stage | Target |
| --- | --- |
| Acknowledgment | 48 hours |
| Assessment | 7 days |
| Fix or mitigation | 14 days, depending on severity |

## Supported Versions

| Version | Supported |
| --- | --- |
| `main` | :white_check_mark: |

Only `main` receives security updates. There are no tagged releases; the site deploys from `main`.

## Scope

In scope:

- API key or credential exposure in code, logs, or generated posts
- Injection vulnerabilities in the collection scripts (`scripts/collect_*.py`, `scripts/common/`)
- CI/CD pipeline security issues — workflow permissions, action pinning, secret handling
- Dependency vulnerabilities reachable from this repository's manifests

Out of scope:

- Issues in third-party data sources (CoinGecko, CoinMarketCap, FMP, Google News, …)
- Social engineering
- Denial of service against the Jekyll static site

## Security Measures

Enforced on every pull request unless noted otherwise:

| Area | Control | Where |
| --- | --- | --- |
| Secret detection | Gitleaks over full history, blocking | `.github/workflows/security-scan.yml` |
| Secret detection | GitHub secret scanning + push protection | Repository settings |
| SAST | Bandit, medium severity/confidence, blocking | `.github/workflows/security-scan.yml` |
| SAST | CodeQL (actions, python, javascript, ruby) | GitHub default setup |
| Workflow permissions | `write-all` and missing `permissions:` blocks fail the build | `.github/workflows/security-scan.yml` |
| Supply chain | Every external action pinned to a 40-hex commit SHA | `tests/test_workflow_action_pinning_guard.py` |
| Supply chain | `requirements.lock` hash-pinned, coverage enforced | `tests/test_requirements_lock_coverage.py` |
| Dependencies | Dependabot (pip, bundler, github-actions), weekly | `.github/dependabot.yml` |
| Dependencies | `pip-audit` | `.github/workflows/dependency-check.yml` |
| Dependencies | Dependency review on pull requests | `.github/workflows/dependency-review.yml` |

### Guards against silent weakening

A control that can be switched off without anyone noticing is not a control.
Regression guards fail the build when a gate is quietly removed or narrowed —
the Gitleaks config, the coverage floor, action pinning, the permission-lint
wiring. See [`docs/devsecops/ci-regression-guards.md`](../docs/devsecops/ci-regression-guards.md).

The guards themselves are verified by a falsifiability harness
(`scripts/tools/guard_falsifiability.py`): it injects each violation and
confirms the corresponding guard actually turns red. A guard that passes no
matter what you break is reported as `VACUOUS` and fails CI.
