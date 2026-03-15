---
name: post-validation
description: Validate blog posts against project quality and compliance gates
compatibility: opencode
license: MIT
metadata:
  audience: maintainers
  domain: content-quality
---

Use this skill to verify post quality before publication.

Checklist:
1. Front matter completeness and category/tag consistency.
2. Link validity and image reference correctness.
3. English-only image filenames and SVG text requirements.
4. Required structural quality (tables, code blocks, checklist).
5. Security and compliance checks for embedded snippets and content.

Deliverables:
- Pass/fail summary by file
- Exact fix list with commands to rerun validation
