"""API keys must not reach logs through a requests exception string.

Every collector in this repo fetches through ``common.utils.request_with_retry``,
and five of them pass a credential in ``params``: FRED (``api_key``) in
``collect_market_indicators`` and ``generate_market_summary``, FMP (``apikey``) in
``common.fmp_api`` and ``collect_stock_news``, CryptoPanic (``auth_token``) in
``collect_crypto_news``.

``requests`` builds the full URL *including the query string* into its exception
messages, on both failure paths — verified, not assumed:

    401 Client Error: UNAUTHORIZED for url: https://…/x?apikey=<KEY>
    HTTPSConnectionPool(host=…): Max retries exceeded with url: /x?apikey=<KEY> (…)

``request_with_retry`` logs that exception with ``%s`` at WARNING three times, and
callers log it again. This repo is **public**, and its collector workflows run on
GitHub Actions twice daily, so those lines land in publicly readable job logs.
GitHub masks registered secret values, but that is one layer and it fails as soon
as a value is transformed, or the same key is used somewhere it is not registered.

The 401 branch matters most: it is the "no retry" path, i.e. exactly what a wrong
or expired key produces — the state a key rotation passes through.

This mirrors the fix made in the sibling `crypto` repo (PRs #462/#463): redact at
the **producer**, so the single writer covers every reader, rather than patching
each log call site.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests as req

from common.utils import redact_credentials, request_with_retry

FAKE_CREDENTIAL = "s3cr3t-key-value-0123456789"


class TestRedactCredentials:
    """The redaction primitive."""

    @pytest.mark.parametrize(
        "param",
        ["apikey", "api_key", "apiKey", "auth_token", "token", "access_key", "key"],
    )
    def test_masks_every_credential_query_param(self, param):
        text = f"401 Client Error for url: https://api.example.com/v1/x?{param}={FAKE_CREDENTIAL}"
        out = redact_credentials(text)
        assert FAKE_CREDENTIAL not in out
        assert f"{param}=***" in out

    def test_masks_credential_that_is_not_the_last_param(self):
        text = f"url: https://x/y?from=2026-01-01&apikey={FAKE_CREDENTIAL}&to=2026-02-01"
        out = redact_credentials(text)
        assert FAKE_CREDENTIAL not in out
        # The surrounding params are diagnostic value — they must survive.
        assert "from=2026-01-01" in out
        assert "to=2026-02-01" in out

    def test_keeps_non_credential_params(self):
        text = "url: https://x/y?symbol=AAPL&limit=10"
        assert redact_credentials(text) == text

    def test_is_case_insensitive_on_the_param_name(self):
        text = f"url: https://x/y?APIKEY={FAKE_CREDENTIAL}"
        assert FAKE_CREDENTIAL not in redact_credentials(text)

    def test_does_not_truncate_at_a_substring_boundary(self):
        """``key`` must not match inside ``apikey`` and leave ``api`` + a live value."""
        text = f"url: https://x/y?apikey={FAKE_CREDENTIAL}"
        out = redact_credentials(text)
        assert FAKE_CREDENTIAL not in out
        assert "apikey=***" in out

    def test_handles_non_string_input(self):
        assert redact_credentials(None) == ""
        assert redact_credentials(123) == "123"


def _http_error(status: int) -> req.exceptions.HTTPError:
    """Build the exception ``resp.raise_for_status()`` produces for a keyed URL."""
    resp = MagicMock()
    resp.status_code = status
    exc = req.exceptions.HTTPError(
        f"{status} Client Error: UNAUTHORIZED for url: "
        f"https://financialmodelingprep.com/stable/quote?symbol=AAPL&apikey={FAKE_CREDENTIAL}"
    )
    exc.response = resp
    return exc


class TestRequestWithRetryDoesNotLogCredentials:
    @patch("common.utils.requests.get")
    def test_no_retry_client_error_warning_is_redacted(self, mock_get, caplog):
        """The 401 branch — what a wrong key during rotation actually produces."""
        resp = MagicMock()
        resp.raise_for_status.side_effect = _http_error(401)
        resp.status_code = 401
        mock_get.return_value = resp

        with caplog.at_level("WARNING"), pytest.raises(req.exceptions.HTTPError):
            request_with_retry("https://financialmodelingprep.com/stable/quote")

        assert caplog.text, "expected a WARNING to be emitted"
        assert FAKE_CREDENTIAL not in caplog.text
        assert "apikey=***" in caplog.text

    @patch("common.utils.requests.get")
    def test_retrying_warning_is_redacted(self, mock_get, caplog):
        mock_get.side_effect = req.exceptions.ConnectionError(
            f"Max retries exceeded with url: /stable/quote?apikey={FAKE_CREDENTIAL}"
        )

        with (
            caplog.at_level("WARNING"),
            patch("common.utils.time.sleep"),
            pytest.raises(req.exceptions.ConnectionError),
        ):
            request_with_retry("https://x/y", max_retries=1)

        assert FAKE_CREDENTIAL not in caplog.text

    @patch("common.utils.requests.get")
    def test_reraised_exception_is_redacted_for_callers(self, mock_get):
        """Callers log this exception again (``fmp_api`` does it at 7 sites).

        Redacting only this module's own log lines would leave those leaking, so the
        exception itself must be clean by the time it leaves ``request_with_retry``.
        """
        resp = MagicMock()
        resp.raise_for_status.side_effect = _http_error(401)
        resp.status_code = 401
        mock_get.return_value = resp

        with pytest.raises(req.exceptions.HTTPError) as excinfo:
            request_with_retry("https://financialmodelingprep.com/stable/quote")

        assert FAKE_CREDENTIAL not in str(excinfo.value)

    @patch("common.utils.requests.get")
    def test_reraised_exception_keeps_its_type_and_response(self, mock_get):
        """Redaction must not cost callers the attributes they branch on.

        ``request_with_retry`` itself reads ``e.response.status_code`` to decide
        whether to retry, and callers catch ``RequestException`` subclasses.
        """
        resp = MagicMock()
        resp.raise_for_status.side_effect = _http_error(403)
        resp.status_code = 403
        mock_get.return_value = resp

        with pytest.raises(req.exceptions.HTTPError) as excinfo:
            request_with_retry("https://x/y")

        assert excinfo.value.response is not None
        assert excinfo.value.response.status_code == 403
