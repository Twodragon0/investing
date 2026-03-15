---
name: security-review
description: Perform a focused security review for changed code and scripts
compatibility: opencode
license: MIT
metadata:
  audience: maintainers
  domain: security
---

Use this skill when reviewing code for security risks.

Checklist:
1. Secrets handling: no hardcoded credentials, tokens, or keys.
2. Input handling: validate and sanitize untrusted input.
3. Output safety: avoid leaking sensitive details in logs/errors.
4. Command safety: avoid dangerous shell patterns and over-broad permissions.
5. Data handling: enforce least privilege and safe defaults.

Deliverables:
- Priority-ranked findings (critical, warning, suggestion)
- Concrete file references and remediation steps
