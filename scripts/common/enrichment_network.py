"""Network core for news enrichment (URL resolution, page fetch, extraction).

Holds the network-facing helpers of the enrichment pipeline: Google News URL
resolution, OG-image / page-metadata fetching over HTTP, and the HTML content
extractors that clean fetched descriptions.

Extracted 2026-07 from ``common.enrichment`` as part of the enrichment facade
decomposition (P2-A), mirroring the ``enrichment_images`` / ``enrichment_synthetic``
split. ``common.enrichment`` re-exports the public names so existing
``from common.enrichment import ...`` call sites (collectors, ``rss_fetcher``, …)
keep working unchanged.

NOTE (batch 0 — scaffolding only): symbols are moved here in subsequent batches
per ``docs/refactoring-plan-2026-07.md`` §1.4. Patch-string relocation happens in
the same commit as each symbol move to keep every batch's test gate hermetic.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("news-enrichment")
