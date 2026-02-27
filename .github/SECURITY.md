# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| Latest (main branch) | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

### How to Report

1. **DO NOT** create a public GitHub issue for security vulnerabilities.
2. Email: Open a [private security advisory](https://github.com/2twodragon/investing/security/advisories/new) on this repository.
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix/Mitigation**: Depending on severity, typically within 14 days

### Scope

The following are in scope:
- API key exposure in code or logs
- Injection vulnerabilities in data collection scripts
- CI/CD pipeline security issues
- Dependency vulnerabilities

### Out of Scope

- Issues in third-party services (CoinGecko, CoinMarketCap, etc.)
- Social engineering attacks
- Denial of service attacks against the Jekyll static site

## Security Measures

This project implements the following security practices:

- **Dependency Scanning**: Weekly automated audits via Dependabot and pip-audit
- **Code Quality**: Automated linting with ruff, type checking with basedpyright
- **Secret Management**: All API keys stored in GitHub Secrets, never in code
- **SAST**: Static Application Security Testing with bandit
- **Workflow Security**: Minimal permissions, actionlint validation
