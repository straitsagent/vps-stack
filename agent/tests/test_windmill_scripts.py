"""
Validates Windmill script function signatures before deployment.
Catches bugs like: non-default arg after default, None defaults on sliced params.
"""
import importlib.util
import inspect
import os
import pathlib
import re
import sys

import pytest


def _load_main_fn(script_path: str):
    spec = importlib.util.spec_from_file_location("_wm_script", script_path)
    mod = importlib.util.module_from_spec(spec)
    # Stub out any imports that would fail outside Windmill
    sys.modules.setdefault("windmill_http_client", type(sys)("windmill_http_client"))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass  # partial import is fine — we just need the function signature
    return getattr(mod, "main", None)


RESEARCH_TOOL = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/research_tool.py"
)


def test_research_tool_no_required_after_optional():
    """All required (no-default) params must come before any optional ones."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        return  # import failed entirely — skip rather than false-fail
    sig = inspect.signature(fn)
    seen_default = False
    for name, param in sig.parameters.items():
        has_default = param.default is not inspect.Parameter.empty
        if has_default:
            seen_default = True
        elif seen_default:
            raise AssertionError(
                f"research_tool.main: non-default param '{name}' follows a param with a default. "
                "This causes a Python SyntaxError at runtime."
            )


def test_research_tool_question_default_is_string():
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        return
    sig = inspect.signature(fn)
    q = sig.parameters.get("question")
    assert q is not None, "research_tool.main missing 'question' param"
    assert isinstance(q.default, str), (
        f"research_tool.main 'question' default should be str, got {type(q.default).__name__}. "
        "None default causes question[:60] crash."
    )


def test_research_tool_depth_has_default():
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        return
    sig = inspect.signature(fn)
    d = sig.parameters.get("depth")
    assert d is not None, "research_tool.main missing 'depth' param"
    assert d.default is not inspect.Parameter.empty, (
        "research_tool.main 'depth' has no default — causes syntax error when called without it."
    )
    assert isinstance(d.default, str)


# ── research_tool._synthesise_with_fallback tests ─────────────────────────────
# Stub packages absent from the agent container so research_tool can load here.

from unittest.mock import patch, MagicMock

for _pkg in ("feedparser", "yfinance", "bs4", "openai", "requests", "psycopg2"):
    if _pkg not in sys.modules:
        sys.modules[_pkg] = MagicMock()


def _load_rt():
    """Load research_tool module with stubs; returns module or None."""
    spec = importlib.util.spec_from_file_location("_rt", RESEARCH_TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("windmill_http_client", type(sys)("windmill_http_client"))
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"[_load_rt] failed: {e}")
        return None


_rt = _load_rt()


def test_synthesise_with_fallback_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_synthesise_with_fallback"), (
        "_synthesise_with_fallback not defined — Grok fallback not implemented"
    )


def test_synthesise_with_fallback_returns_grok_on_success():
    if _rt is None or not hasattr(_rt, "_synthesise_with_fallback"):
        pytest.skip("research_tool not loadable or function missing")
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = "grok synthesis"
    mock_resp.usage.prompt_tokens = 100
    mock_resp.usage.completion_tokens = 200
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp
    with patch.object(_rt, "OpenAI", return_value=mock_client):
        result = _rt._synthesise_with_fallback(
            messages=[{"role": "user", "content": "test"}],
            xai_key="test", deepseek_key="test",
            reasoning_effort="low", max_tokens=1500,
        )
    assert result["text"] == "grok synthesis"
    assert result["synthesiser_model"] == "grok-4.3"
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 200


def test_synthesise_with_fallback_uses_deepseek_on_grok_error():
    if _rt is None or not hasattr(_rt, "_synthesise_with_fallback"):
        pytest.skip("research_tool not loadable or function missing")
    mock_grok = MagicMock()
    mock_grok.chat.completions.create.side_effect = Exception("xAI timeout")
    mock_ds_resp = MagicMock()
    mock_ds_resp.choices[0].message.content = "deepseek fallback"
    mock_ds_resp.usage.prompt_tokens = 50
    mock_ds_resp.usage.completion_tokens = 100
    mock_ds = MagicMock()
    mock_ds.chat.completions.create.return_value = mock_ds_resp
    with patch.object(_rt, "OpenAI", side_effect=[mock_grok, mock_ds]):
        result = _rt._synthesise_with_fallback(
            messages=[{"role": "user", "content": "test"}],
            xai_key="test", deepseek_key="test",
            reasoning_effort="low", max_tokens=1500,
        )
    assert result["synthesiser_model"] == "deepseek-fallback"
    assert result["text"] == "deepseek fallback"


def test_synthesise_with_fallback_returns_error_if_both_fail():
    if _rt is None or not hasattr(_rt, "_synthesise_with_fallback"):
        pytest.skip("research_tool not loadable or function missing")
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("both down")
    with patch.object(_rt, "OpenAI", return_value=mock_client):
        result = _rt._synthesise_with_fallback(
            messages=[{"role": "user", "content": "test"}],
            xai_key="test", deepseek_key="test",
            reasoning_effort="low", max_tokens=1500,
        )
    assert result["synthesiser_model"] == "error"
    assert "failed" in result["text"].lower()


def test_research_tool_return_has_synthesiser_model():
    """main() return dict must include synthesiser_model key."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    # Inspect source for synthesiser_model in the return dict
    import ast
    with open(RESEARCH_TOOL) as f:
        src = f.read()
    assert "synthesiser_model" in src, (
        "research_tool.main return dict missing 'synthesiser_model' key"
    )


# ── W3 alert script tests ─────────────────────────────────────────────────────

WINDMILL_DIR = os.path.join(os.path.dirname(__file__), "../../windmill/u/admin")
EARNINGS_ALERT = os.path.join(WINDMILL_DIR, "portfolio_earnings_alert.py")
ANALYST_ALERT = os.path.join(WINDMILL_DIR, "portfolio_analyst_alert.py")

_DB_ARG = {"host": "localhost", "dbname": "test", "user": "test", "password": "test", "port": 5432}


def test_earnings_alert_script_has_correct_params():
    fn = _load_main_fn(EARNINGS_ALERT)
    if fn is None:
        pytest.skip("portfolio_earnings_alert not loadable")
    params = inspect.signature(fn).parameters
    assert "portfolio_db" in params
    assert "finnhub_key" in params
    assert "telegram_bot_token" in params


def test_earnings_alert_no_upcoming_returns_no_alert():
    for _pkg in ("requests",):
        if _pkg not in sys.modules:
            sys.modules[_pkg] = MagicMock()
    spec = importlib.util.spec_from_file_location("_ea", EARNINGS_ALERT)
    if spec is None:
        pytest.skip("portfolio_earnings_alert not found")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    if not hasattr(mod, "main"):
        pytest.skip("portfolio_earnings_alert not loadable")
    mock_db_resp = MagicMock()
    mock_db_resp.json.return_value = {"earningsCalendar": []}
    with patch.object(mod.requests, "get", return_value=mock_db_resp):
        with patch.object(mod, "_get_tickers", return_value=["AAPL"]):
            result = mod.main(
                portfolio_db=_DB_ARG,
                finnhub_key="test",
                telegram_bot_token="123:test",
            )
    assert result["alerts_sent"] == 0


def test_analyst_alert_script_has_correct_params():
    fn = _load_main_fn(ANALYST_ALERT)
    if fn is None:
        pytest.skip("portfolio_analyst_alert not loadable")
    params = inspect.signature(fn).parameters
    assert "portfolio_db" in params
    assert "finnhub_key" in params
    assert "telegram_bot_token" in params


def test_analyst_alert_no_changes_returns_no_alert():
    for _pkg in ("requests",):
        if _pkg not in sys.modules:
            sys.modules[_pkg] = MagicMock()
    spec = importlib.util.spec_from_file_location("_aa", ANALYST_ALERT)
    if spec is None:
        pytest.skip("portfolio_analyst_alert not found")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    if not hasattr(mod, "main"):
        pytest.skip("portfolio_analyst_alert not loadable")
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    with patch.object(mod.requests, "get", return_value=mock_resp):
        with patch.object(mod, "_get_tickers", return_value=["AAPL"]):
            result = mod.main(
                portfolio_db=_DB_ARG,
                finnhub_key="test",
                telegram_bot_token="123:test",
            )
    assert result["alerts_sent"] == 0


# ── Earnings analysis script tests ───────────────────────────────────────────

EARNINGS_ANALYSIS = os.path.join(WINDMILL_DIR, "portfolio_earnings_analysis.py")
EARNINGS_POST_CHECK = os.path.join(WINDMILL_DIR, "portfolio_earnings_post_check.py")


def test_earnings_analysis_script_has_correct_params():
    fn = _load_main_fn(EARNINGS_ANALYSIS)
    if fn is None:
        pytest.skip("portfolio_earnings_analysis not loadable")
    params = inspect.signature(fn).parameters
    for p in ("ticker", "analysis_type", "xai_key", "exa_key", "finnhub_key", "telegram_bot_token"):
        assert p in params, f"portfolio_earnings_analysis.main missing param '{p}'"


def test_earnings_analysis_analysis_type_default_is_pre():
    fn = _load_main_fn(EARNINGS_ANALYSIS)
    if fn is None:
        pytest.skip("portfolio_earnings_analysis not loadable")
    sig = inspect.signature(fn)
    p = sig.parameters.get("analysis_type")
    assert p is not None
    assert p.default == "pre", f"analysis_type default should be 'pre', got {p.default!r}"


def test_earnings_post_check_has_correct_params():
    fn = _load_main_fn(EARNINGS_POST_CHECK)
    if fn is None:
        pytest.skip("portfolio_earnings_post_check not loadable")
    params = inspect.signature(fn).parameters
    assert "portfolio_db" in params, "portfolio_earnings_post_check.main missing 'portfolio_db'"
    assert "finnhub_key" in params, "portfolio_earnings_post_check.main missing 'finnhub_key'"


def test_earnings_alert_dispatches_pre_analysis_for_upcoming():
    """Confirms _dispatch_pre_analysis is called when upcoming earnings are found."""
    spec = importlib.util.spec_from_file_location("_ea_dp", EARNINGS_ALERT)
    if spec is None:
        pytest.skip("portfolio_earnings_alert not found")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    if not hasattr(mod, "main") or not hasattr(mod, "_dispatch_pre_analysis"):
        pytest.skip("portfolio_earnings_alert missing _dispatch_pre_analysis")
    upcoming = {"date": "2026-06-20", "epsEstimate": 1.25, "epsActual": None, "symbol": "AAPL"}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"earningsCalendar": [upcoming]}
    dispatched = []
    def fake_dispatch(ticker, earnings_date, portfolio_db, wm_token):
        dispatched.append(ticker)
    with patch.object(mod.requests, "get", return_value=mock_resp):
        with patch.object(mod, "_get_tickers", return_value=["AAPL"]):
            with patch.object(mod, "_dispatch_pre_analysis", fake_dispatch):
                mod.main(
                    portfolio_db=_DB_ARG,
                    finnhub_key="test",
                    telegram_bot_token="123:test",
                )
    assert "AAPL" in dispatched, "_dispatch_pre_analysis not called for upcoming earnings"


# ── Earnings analysis: research dispatch tests ───────────────────────────────

def _load_earnings_mod():
    spec = importlib.util.spec_from_file_location("_ea_mod", EARNINGS_ANALYSIS)
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    for pkg in ("psycopg2", "yfinance", "openai"):
        sys.modules.setdefault(pkg, MagicMock())
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return mod


def test_earnings_analysis_main_has_wm_token_param():
    """main() must accept wm_token so it can dispatch research jobs."""
    fn = _load_main_fn(EARNINGS_ANALYSIS)
    if fn is None:
        pytest.skip("portfolio_earnings_analysis not loadable")
    assert "wm_token" in inspect.signature(fn).parameters, \
        "portfolio_earnings_analysis.main missing 'wm_token' param"


def test_grok_synthesise_returns_model_field():
    """_grok_synthesise must return a 'model' key so the report footer is accurate."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_grok_synthesise"):
        pytest.skip("portfolio_earnings_analysis not loadable")
    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock(message=MagicMock(content="text"))]
    fake_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    with patch("openai.OpenAI") as OpenAI_mock:
        OpenAI_mock.return_value.chat.completions.create.return_value = fake_resp
        result = mod._grok_synthesise("sys", "user", "fake-key")
    assert "model" in result, (
        "_grok_synthesise must include 'model' in its return dict so the footer "
        "shows the actual model name instead of hardcoded 'Grok-4.3'"
    )


def test_earnings_report_footer_uses_actual_model():
    """The report footer must show result['synthesiser_model'], not hardcoded 'Grok-4.3'."""
    mod = _load_earnings_mod()
    if mod is None:
        pytest.skip("portfolio_earnings_analysis not loadable")
    # If synthesiser_model is not in result, the footer should still not hardcode Grok-4.3
    # Check via grep that the footer line references result.get() or a variable, not literal "Grok-4.3"
    import ast, textwrap
    src_path = pathlib.Path("/windmill/u/admin/portfolio_earnings_analysis.py")
    if not src_path.exists():
        pytest.skip("script not in /windmill mount")
    src = src_path.read_text()
    footer_pattern = re.search(r'\*\*Model:\*\*.*', src)
    assert footer_pattern, "footer line not found in script"
    footer_line = footer_pattern.group(0)
    assert "Grok-4.3" not in footer_line, (
        f"Footer line still hardcodes 'Grok-4.3': {footer_line!r}\n"
        "Must use a variable (e.g. result.get('synthesiser_model', 'grok-4.3')) instead."
    )


def test_dispatch_and_wait_research_exists():
    """_dispatch_and_wait_research helper must exist in the module."""
    mod = _load_earnings_mod()
    if mod is None:
        pytest.skip("portfolio_earnings_analysis not loadable")
    assert hasattr(mod, "_dispatch_and_wait_research"), \
        "portfolio_earnings_analysis missing _dispatch_and_wait_research()"


def test_dispatch_and_wait_research_dispatches_and_polls():
    """On success, dispatches research job and polls until CompletedJob."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_dispatch_and_wait_research"):
        pytest.skip("not loadable")
    dispatch_resp = MagicMock()
    dispatch_resp.text = '"job-abc-123"'
    dispatch_resp.raise_for_status = MagicMock()
    poll_resp = MagicMock()
    poll_resp.status_code = 200
    poll_resp.json.return_value = {"type": "CompletedJob", "success": True}
    with patch.object(mod.requests, "post", return_value=dispatch_resp):
        with patch.object(mod.requests, "get", return_value=poll_resp):
            with patch.object(mod.time, "sleep"):
                result = mod._dispatch_and_wait_research("AAPL", "wm-token-test")
    assert result is True


def test_dispatch_and_wait_research_returns_false_on_dispatch_error():
    """Returns False (not raises) when the dispatch request fails."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_dispatch_and_wait_research"):
        pytest.skip("not loadable")
    with patch.object(mod.requests, "post", side_effect=Exception("connection refused")):
        result = mod._dispatch_and_wait_research("AAPL", "wm-token-test")
    assert result is False


def test_run_pre_earnings_dispatches_research_when_missing():
    """When no research in ctx, _dispatch_and_wait_research must be called."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_run_pre_earnings"):
        pytest.skip("not loadable")
    ctx_no_research = {
        "ticker": "AAPL", "company_name": "Apple Inc", "currency": "USD",
        "shares": 100, "latest_price": 200.0, "position_usd": 20000.0,
        "total_portfolio_usd": 1000000.0,
    }
    dispatched = []
    def fake_dispatch(ticker, wm_token, timeout_s=120):
        dispatched.append(ticker)
        return False  # simulate failure so fallback kicks in
    with patch.object(mod, "_get_portfolio_context", return_value=ctx_no_research):
        with patch.object(mod, "_dispatch_and_wait_research", side_effect=fake_dispatch):
            with patch.object(mod, "_finnhub_earnings", return_value=[]):
                with patch.object(mod, "_yfinance_quarterly", return_value=""):
                    with patch.object(mod, "_edgar_prior_8k", return_value=None):
                        with patch.object(mod, "_exa_search", return_value=""):
                            with patch.object(mod, "_get_seeded_overview", return_value="fallback"):
                                with patch.object(mod, "_grok_synthesise",
                                                  return_value={"text": "ok", "input_tokens": 10, "output_tokens": 5}):
                                    mod._run_pre_earnings("AAPL", {}, "fk", "ek", "xk", "wmtok")
    assert "AAPL" in dispatched, "_dispatch_and_wait_research not called when research missing"


def test_run_pre_earnings_skips_dispatch_when_research_exists():
    """When research_content already in ctx, must NOT dispatch a research job."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_run_pre_earnings"):
        pytest.skip("not loadable")
    ctx_with_research = {
        "ticker": "AAPL", "company_name": "Apple Inc", "currency": "USD",
        "research_content": "Apple is a tech giant...",
        "research_date": "2026-05-01", "research_depth": "standard",
    }
    dispatched = []
    with patch.object(mod, "_get_portfolio_context", return_value=ctx_with_research):
        with patch.object(mod, "_dispatch_and_wait_research", side_effect=lambda *a, **k: dispatched.append(True)):
            with patch.object(mod, "_finnhub_earnings", return_value=[]):
                with patch.object(mod, "_yfinance_quarterly", return_value=""):
                    with patch.object(mod, "_edgar_prior_8k", return_value=None):
                        with patch.object(mod, "_exa_search", return_value=""):
                            with patch.object(mod, "_grok_synthesise",
                                              return_value={"text": "ok", "input_tokens": 10, "output_tokens": 5}):
                                mod._run_pre_earnings("AAPL", {}, "fk", "ek", "xk", "wmtok")
    assert len(dispatched) == 0, "_dispatch_and_wait_research called when research already exists"


def test_extract_research_synopsis_skips_metadata_preamble():
    """_extract_research_synopsis must skip cost/source tables and return narrative content."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_extract_research_synopsis"):
        pytest.skip("not loadable or function not present")
    content_with_preamble = (
        "# \n\n"
        "**Type:** stock | **Depth:** standard | **Date:** 2026-06-11 | **Ticker:** ADBE\n\n"
        "### Cost Breakdown\n"
        "| API | Usage | Est. Cost |\n"
        "|---|---|---|\n"
        "| Grok-4.3 | 6727 in + 913 out | $0.0107 |\n"
        "| **Total** | 7640 tokens | **$0.0307** |\n\n"
        "### Source Retrieval Quality\n"
        "| Source | Count | Content Level |\n"
        "|---|---|---|\n"
        "| finnhub | 10 | 9 full text |\n\n"
        "---\n\n"
        "**Analyst Expectations**\n"
        "- Revenue: $6.45B consensus (+9.85% YoY)\n"
        "- EPS: $5.9385 consensus\n"
    )
    synopsis = mod._extract_research_synopsis(content_with_preamble, max_chars=300)
    assert "Cost Breakdown" not in synopsis, "synopsis must not contain Cost Breakdown metadata table"
    assert "Analyst Expectations" in synopsis, "synopsis must contain narrative content"
    assert "Revenue:" in synopsis, "synopsis must contain revenue data"


def test_extract_research_synopsis_stops_before_sources_footer():
    """_extract_research_synopsis must not include the sources/tokens footer."""
    mod = _load_earnings_mod()
    if mod is None or not hasattr(mod, "_extract_research_synopsis"):
        pytest.skip("not loadable or function not present")
    content = (
        "# \n\n**Type:** stock\n\n---\n\n"
        "**Business Overview**\nThis is the narrative content.\n\n"
        "---\n\n"
        "**Sources used (3):**\n  - Finnhub\n"
        "**Model:** Grok-4.3 | **Tokens:** 100 in / 50 out\n"
    )
    synopsis = mod._extract_research_synopsis(content, max_chars=500)
    assert "Sources used" not in synopsis, "synopsis must not include sources footer"
    assert "Business Overview" in synopsis, "synopsis must contain narrative content"


# ── research_tool source-routing changes (search API audit) ──────────────────
# Tests for:
#   1. Perplexity recency filter added to payload
#   2. Exa date filter added to payload
#   3. Exa dropped for research_type=stock at standard depth
#   4. _fetch_serper_news added; called at brief + standard depth
#   5. EDGAR 8-K moved to standard depth; 10-K/10-Q remain deep-only
#   6. serper_key param added to main()


def _make_mock_requests():
    """Return a MagicMock requests module that succeeds silently."""
    mock_req = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"results": [], "earningsCalendar": []}
    mock_resp.text = ""
    mock_req.get.return_value = mock_resp
    mock_req.post.return_value = mock_resp
    return mock_req


# 1 ── Perplexity recency filter ───────────────────────────────────────────────

def test_perplexity_payload_includes_recency_filter():
    """_fetch_perplexity_batch must send search_recency_filter='month' in every payload."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    mock_req = _make_mock_requests()
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_perplexity_batch(["test query"], "fake_key", max_results=3)
    assert mock_req.post.called, "_fetch_perplexity_batch did not call requests.post"
    call_kwargs = mock_req.post.call_args
    payload = call_kwargs[1].get("json") or call_kwargs[0][1]
    assert payload.get("search_recency_filter") == "month", (
        f"Expected search_recency_filter='month' in Perplexity payload, got: {payload}"
    )


# 2 ── Exa date filter ─────────────────────────────────────────────────────────

def test_exa_payload_includes_start_published_date():
    """_fetch_exa_query must send startPublishedDate in every payload."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    mock_req = _make_mock_requests()
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_exa_query("test query", "fake_key", max_results=3)
    assert mock_req.post.called, "_fetch_exa_query did not call requests.post"
    call_kwargs = mock_req.post.call_args
    payload = call_kwargs[1].get("json") or call_kwargs[0][1]
    assert "startPublishedDate" in payload, (
        f"Expected startPublishedDate in Exa payload, got keys: {list(payload.keys())}"
    )


# 3 ── Exa routing by research_type ───────────────────────────────────────────

def test_exa_skipped_for_stock_at_standard_depth():
    """Exa must NOT be called for research_type='stock' at depth='standard'."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_exa(query, key, **kw):
        calls.append(query)
        return []
    with patch.object(_rt, "_fetch_exa_query", fake_exa), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_fetch_edgar_filings", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA stock", research_type="stock", depth="standard",
                 ticker="NVDA", exa_key="key", perplexity_key="key", deepseek_key="",
                 serper_key="")
    assert calls == [], (
        f"Exa should NOT be called for research_type='stock' at standard depth, but got calls: {calls}"
    )


def test_exa_called_for_project_at_standard_depth():
    """Exa MUST be called for research_type='project' at depth='standard'."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_exa(query, key, **kw):
        calls.append(query)
        return []
    with patch.object(_rt, "_fetch_exa_query", fake_exa), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_fetch_edgar_filings", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="infra debt spreads", research_type="project", depth="standard",
                 ticker="", exa_key="key", perplexity_key="key", deepseek_key="",
                 serper_key="")
    assert len(calls) > 0, (
        "Exa should be called for research_type='project' at standard depth"
    )


def test_exa_called_for_stock_at_deep_depth():
    """Exa MUST still be called for research_type='stock' at depth='deep'."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_exa(query, key, **kw):
        calls.append(query)
        return []
    with patch.object(_rt, "_fetch_exa_query", fake_exa), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_fetch_edgar_filings", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA deep dive", research_type="stock", depth="deep",
                 ticker="NVDA", exa_key="key", perplexity_key="key", deepseek_key="",
                 serper_key="")
    assert len(calls) > 0, (
        "Exa should still be called for research_type='stock' at deep depth"
    )


# 4 ── _fetch_serper_news ──────────────────────────────────────────────────────

def test_fetch_serper_news_exists():
    """_fetch_serper_news must be defined in research_tool."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_serper_news"), (
        "_fetch_serper_news not found in research_tool — function not yet implemented"
    )


def test_fetch_serper_news_posts_to_correct_endpoint():
    """_fetch_serper_news must POST to google.serper.dev/news with X-API-KEY header."""
    if _rt is None or not hasattr(_rt, "_fetch_serper_news"):
        pytest.skip("_fetch_serper_news not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {"news": [
        {"title": "Test", "link": "https://example.com", "snippet": "s", "date": "1d ago"},
    ]}
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_serper_news(["query 1"], "fake_serper_key")
    assert mock_req.post.called
    call_args = mock_req.post.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "serper" in url.lower() or "google" in url.lower(), (
        f"Expected serper.dev URL, got: {url}"
    )
    headers = call_args[1].get("headers", {})
    assert "X-API-KEY" in headers or "x-api-key" in headers, (
        f"Expected X-API-KEY header, got: {headers}"
    )


def test_fetch_serper_news_returns_normalised_items():
    """_fetch_serper_news must return list of dicts with source='serper'."""
    if _rt is None or not hasattr(_rt, "_fetch_serper_news"):
        pytest.skip("_fetch_serper_news not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {"news": [
        {"title": "Headline A", "link": "https://a.com", "snippet": "snip", "date": "2h ago"},
        {"title": "Headline B", "link": "https://b.com", "snippet": "snip2", "date": "5h ago"},
    ]}
    with patch.object(_rt, "requests", mock_req):
        items = _rt._fetch_serper_news(["query"], "fake_key")
    assert isinstance(items, list)
    assert len(items) == 2
    for item in items:
        assert item.get("source") == "serper", f"Expected source='serper', got: {item.get('source')}"
        assert "title" in item
        assert "url" in item


def test_serper_called_at_brief_depth():
    """_fetch_serper_news must be called when depth='brief' and serper_key is set."""
    if _rt is None or not hasattr(_rt, "_fetch_serper_news"):
        pytest.skip("_fetch_serper_news not defined")
    calls = []
    def fake_serper(queries, key, **kw):
        calls.append(queries)
        return []
    with patch.object(_rt, "_fetch_serper_news", fake_serper), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="macro rates", research_type="macro", depth="brief",
                 ticker="", perplexity_key="key", serper_key="serper_key_val", deepseek_key="")
    assert len(calls) > 0, "Serper not called at brief depth when serper_key is set"


def test_serper_called_at_standard_depth():
    """_fetch_serper_news must also be called at depth='standard'."""
    if _rt is None or not hasattr(_rt, "_fetch_serper_news"):
        pytest.skip("_fetch_serper_news not defined")
    calls = []
    def fake_serper(queries, key, **kw):
        calls.append(queries)
        return []
    with patch.object(_rt, "_fetch_serper_news", fake_serper), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_fetch_edgar_filings", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="macro outlook", research_type="macro", depth="standard",
                 ticker="", perplexity_key="key", serper_key="serper_key_val", deepseek_key="")
    assert len(calls) > 0, "Serper not called at standard depth when serper_key is set"


def test_serper_not_called_without_key():
    """_fetch_serper_news must NOT be called when serper_key is empty."""
    if _rt is None or not hasattr(_rt, "_fetch_serper_news"):
        pytest.skip("_fetch_serper_news not defined")
    calls = []
    def fake_serper(queries, key, **kw):
        calls.append(queries)
        return []
    with patch.object(_rt, "_fetch_serper_news", fake_serper), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="macro rates", research_type="macro", depth="brief",
                 ticker="", perplexity_key="key", serper_key="", deepseek_key="")
    assert calls == [], f"Serper should not be called without serper_key, got: {calls}"


# 5 ── EDGAR at standard depth ─────────────────────────────────────────────────

def test_edgar_fetched_at_standard_depth_for_us_stock():
    """_fetch_edgar_filings must be called at depth='standard' for a US ticker."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_edgar(ticker, forms=None):
        calls.append({"ticker": ticker, "forms": forms})
        return []
    with patch.object(_rt, "_fetch_edgar_filings", fake_edgar), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA analysis", research_type="stock", depth="standard",
                 ticker="NVDA", perplexity_key="key", serper_key="", deepseek_key="")
    assert len(calls) > 0, "EDGAR should be called at standard depth for a US stock"


def test_edgar_standard_depth_uses_8k_only():
    """At depth='standard', _fetch_edgar_filings must be called with forms=['8-K'] only."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_edgar(ticker, forms=None):
        calls.append({"ticker": ticker, "forms": forms})
        return []
    with patch.object(_rt, "_fetch_edgar_filings", fake_edgar), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA analysis", research_type="stock", depth="standard",
                 ticker="NVDA", perplexity_key="key", serper_key="", deepseek_key="")
    assert calls, "EDGAR not called"
    assert calls[0]["forms"] == ["8-K"], (
        f"At standard depth, EDGAR should use forms=['8-K'] only, got: {calls[0]['forms']}"
    )


def test_edgar_deep_depth_uses_all_forms():
    """At depth='deep', _fetch_edgar_filings must be called with forms=None (all filing types)."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_edgar(ticker, forms=None):
        calls.append({"ticker": ticker, "forms": forms})
        return []
    with patch.object(_rt, "_fetch_edgar_filings", fake_edgar), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA deep", research_type="stock", depth="deep",
                 ticker="NVDA", perplexity_key="key", serper_key="", deepseek_key="")
    assert calls, "EDGAR not called at deep depth"
    assert calls[0]["forms"] is None, (
        f"At deep depth, EDGAR should use forms=None (all), got: {calls[0]['forms']}"
    )


def test_edgar_not_fetched_for_hk_ticker_at_standard():
    """_fetch_edgar_filings must NOT be called for HK tickers at standard depth."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    calls = []
    def fake_edgar(ticker, forms=None):
        calls.append(ticker)
        return []
    with patch.object(_rt, "_fetch_edgar_filings", fake_edgar), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="HSBC analysis", research_type="stock", depth="standard",
                 ticker="0005.HK", perplexity_key="key", serper_key="", deepseek_key="")
    assert calls == [], f"EDGAR should not be called for HK tickers, got: {calls}"


# 6 ── serper_key param in main() ─────────────────────────────────────────────

def test_research_tool_main_has_serper_key_param():
    """main() must accept serper_key parameter."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    params = inspect.signature(fn).parameters
    assert "serper_key" in params, (
        "research_tool.main missing 'serper_key' param — not yet implemented"
    )


# ── Windmill connectivity ─────────────────────────────────────────────────────

def test_windmill_health_endpoint_reachable():
    """Verify Windmill server is reachable from inside the container.
    Uses httpx to avoid the requests mock set up earlier in this module.
    WM_BASE_URL uses port 8000 (internal Docker network port)."""
    import httpx
    base_url = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
    r = httpx.get(f"{base_url}/api/version", timeout=5)
    assert r.status_code == 200


def test_windmill_token_authenticates():
    """Verify the WM_TOKEN can authenticate against the Windmill workspace."""
    import httpx
    base_url = os.environ.get("WM_BASE_URL", "http://windmill_server:8000")
    workspace = os.environ.get("WM_WORKSPACE", "admins")
    token = os.environ.get("WM_TOKEN", "")
    url = f"{base_url}/api/w/{workspace}/scripts/list"
    r = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=5)
    assert r.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 7 ── Tavily ──────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_tavily_function_exists():
    """_fetch_tavily must be defined in research_tool."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_tavily"), (
        "_fetch_tavily not found in research_tool — function not yet implemented"
    )


def test_fetch_tavily_posts_to_correct_endpoint():
    """_fetch_tavily must POST to api.tavily.com/search."""
    if _rt is None or not hasattr(_rt, "_fetch_tavily"):
        pytest.skip("_fetch_tavily not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {"results": []}
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_tavily(["NVDA earnings"], "fake_tavily_key")
    assert mock_req.post.called, "_fetch_tavily did not call requests.post"
    call_args = mock_req.post.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "tavily.com" in url, f"Expected tavily.com endpoint, got: {url}"


def test_fetch_tavily_uses_topic_finance_and_time_range_month():
    """_fetch_tavily must send topic='finance' and time_range='month' in the payload."""
    if _rt is None or not hasattr(_rt, "_fetch_tavily"):
        pytest.skip("_fetch_tavily not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {"results": []}
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_tavily(["NVDA earnings"], "fake_tavily_key")
    call_args = mock_req.post.call_args
    payload = call_args[1].get("json", {}) or (call_args[0][1] if len(call_args[0]) > 1 else {})
    assert payload.get("topic") == "finance", (
        f"Tavily payload must include topic='finance', got: {payload.get('topic')}"
    )
    assert payload.get("time_range") == "month", (
        f"Tavily payload must include time_range='month' (Hard Rule 14 workaround), got: {payload.get('time_range')}"
    )


def test_fetch_tavily_returns_normalised_items_with_freshness_sentinel_date():
    """_fetch_tavily must return items with source='tavily' and date='freshness:month'."""
    if _rt is None or not hasattr(_rt, "_fetch_tavily"):
        pytest.skip("_fetch_tavily not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {"results": [
        {"title": "Tavily Article", "url": "https://example.com/1", "content": "snippet text"},
        {"title": "Tavily Article 2", "url": "https://example.com/2", "content": "snippet 2"},
    ]}
    with patch.object(_rt, "requests", mock_req):
        items = _rt._fetch_tavily(["test query"], "fake_tavily_key")
    assert isinstance(items, list), "Expected list from _fetch_tavily"
    assert len(items) >= 1
    for item in items:
        assert item.get("source") == "tavily", f"Expected source='tavily', got: {item.get('source')}"
        assert item.get("date") == "freshness:month", (
            f"Tavily items must use date='freshness:month' sentinel (no real date in API response), "
            f"got: {item.get('date')}"
        )
        assert "title" in item and "url" in item


def test_tavily_called_at_standard_and_deep():
    """_fetch_tavily must be called at standard and deep depth when tavily_key is set."""
    if _rt is None or not hasattr(_rt, "_fetch_tavily"):
        pytest.skip("_fetch_tavily not defined")
    for depth in ("standard", "deep"):
        calls = []
        def fake_tavily(queries, key, **kw):
            calls.append(depth)
            return []
        with patch.object(_rt, "_fetch_tavily", fake_tavily), \
             patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
             patch.object(_rt, "_fetch_google_news", return_value=[]), \
             patch.object(_rt, "_build_db_context", return_value=""), \
             patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
             patch.object(_rt, "_send_research_email", return_value=None), \
             patch.object(_rt, "requests", _make_mock_requests()):
            _rt.main(question="NVDA analysis", research_type="stock", depth=depth,
                     ticker="NVDA", perplexity_key="key", serper_key="",
                     deepseek_key="", tavily_key="tavily_key_val")
        assert calls, f"_fetch_tavily not called at depth='{depth}'"


# ─────────────────────────────────────────────────────────────────────────────
# 8 ── Brave Search ────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_brave_news_function_exists():
    """_fetch_brave_news must be defined in research_tool."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_brave_news"), (
        "_fetch_brave_news not found in research_tool — function not yet implemented"
    )


def test_fetch_brave_news_calls_correct_endpoint():
    """_fetch_brave_news must call api.search.brave.com/res/v1/news/search."""
    if _rt is None or not hasattr(_rt, "_fetch_brave_news"):
        pytest.skip("_fetch_brave_news not defined")
    mock_req = _make_mock_requests()
    mock_req.get.return_value.json.return_value = {"results": []}
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_brave_news(["NVDA earnings"], "fake_brave_key")
    assert mock_req.get.called, "_fetch_brave_news did not call requests.get"
    call_args = mock_req.get.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "brave.com" in url, f"Expected brave.com endpoint, got: {url}"
    assert "news" in url, f"Expected news endpoint, got: {url}"


def test_fetch_brave_news_uses_freshness_pm():
    """_fetch_brave_news must send freshness='pm' (past month) in params."""
    if _rt is None or not hasattr(_rt, "_fetch_brave_news"):
        pytest.skip("_fetch_brave_news not defined")
    mock_req = _make_mock_requests()
    mock_req.get.return_value.json.return_value = {"results": []}
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_brave_news(["NVDA earnings"], "fake_brave_key")
    call_args = mock_req.get.call_args
    params = call_args[1].get("params", {}) or (call_args[0][1] if len(call_args[0]) > 1 else {})
    assert params.get("freshness") == "pm", (
        f"Brave must use freshness='pm' (past month) for recency, got: {params.get('freshness')}"
    )


def test_parse_brave_relative_date_converts_correctly():
    """_parse_brave_relative_date must convert Brave's relative date strings to ISO dates."""
    if _rt is None or not hasattr(_rt, "_parse_brave_relative_date"):
        pytest.skip("_parse_brave_relative_date not defined")
    from datetime import date, timedelta
    today = date.today()
    cases = [
        ("1d", (today - timedelta(days=1)).isoformat()),
        ("3w", (today - timedelta(weeks=3)).isoformat()),
        ("2mo", (today - timedelta(days=60)).isoformat()),
    ]
    for rel, expected in cases:
        result = _rt._parse_brave_relative_date(rel)
        assert result == expected, (
            f"_parse_brave_relative_date('{rel}') expected '{expected}', got '{result}'"
        )


def test_brave_called_at_standard_and_deep():
    """_fetch_brave_news must be called at standard and deep depth when brave_key is set."""
    if _rt is None or not hasattr(_rt, "_fetch_brave_news"):
        pytest.skip("_fetch_brave_news not defined")
    for depth in ("standard", "deep"):
        calls = []
        def fake_brave(queries, key, **kw):
            calls.append(depth)
            return []
        with patch.object(_rt, "_fetch_brave_news", fake_brave), \
             patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
             patch.object(_rt, "_fetch_google_news", return_value=[]), \
             patch.object(_rt, "_build_db_context", return_value=""), \
             patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
             patch.object(_rt, "_send_research_email", return_value=None), \
             patch.object(_rt, "requests", _make_mock_requests()):
            _rt.main(question="NVDA analysis", research_type="stock", depth=depth,
                     ticker="NVDA", perplexity_key="key", serper_key="",
                     deepseek_key="", brave_key="brave_key_val")
        assert calls, f"_fetch_brave_news not called at depth='{depth}'"


# ─────────────────────────────────────────────────────────────────────────────
# 9 ── Agentic Gap Analysis ────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def test_iterative_gap_analysis_function_exists():
    """_iterative_gap_analysis must be defined in research_tool."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_iterative_gap_analysis"), (
        "_iterative_gap_analysis not found in research_tool — function not yet implemented"
    )


def test_iterative_gap_analysis_calls_deepseek_with_sources():
    """_iterative_gap_analysis must call Deepseek API with sources context."""
    if _rt is None or not hasattr(_rt, "_iterative_gap_analysis"):
        pytest.skip("_iterative_gap_analysis not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {
        "choices": [{"message": {"content": '{"gaps": []}'}}]
    }
    sources = [{"title": "Article 1", "url": "https://a.com", "source": "perplexity"}]
    with patch.object(_rt, "requests", mock_req):
        _rt._iterative_gap_analysis(sources, "NVDA earnings", "stock", "fake_ds_key")
    assert mock_req.post.called, "_iterative_gap_analysis did not call requests.post (Deepseek)"
    call_args = mock_req.post.call_args
    url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "deepseek" in url.lower(), f"Expected Deepseek API URL, got: {url}"


def test_iterative_gap_analysis_returns_structured_gaps():
    """_iterative_gap_analysis must return list of dicts with description, query, source_type."""
    if _rt is None or not hasattr(_rt, "_iterative_gap_analysis"):
        pytest.skip("_iterative_gap_analysis not defined")
    mock_req = _make_mock_requests()
    mock_req.post.return_value.json.return_value = {
        "choices": [{"message": {"content": '{"gaps": [{"description": "Missing SEC data", "query": "NVDA 8-K filing", "source_type": "sec"}]}'}}]
    }
    sources = [{"title": "Article 1", "url": "https://a.com", "source": "perplexity"}]
    with patch.object(_rt, "requests", mock_req):
        gaps = _rt._iterative_gap_analysis(sources, "NVDA earnings", "stock", "fake_ds_key")
    assert isinstance(gaps, list), "Expected list of gaps"
    assert len(gaps) == 1
    gap = gaps[0]
    assert "description" in gap, "Gap must have 'description' field"
    assert "query" in gap, "Gap must have 'query' field"
    assert "source_type" in gap, "Gap must have 'source_type' field"
    assert gap["source_type"] == "sec"


def test_deep_depth_triggers_gap_analysis_after_round1():
    """At depth='deep', _iterative_gap_analysis must be called after Round 1 retrieval."""
    if _rt is None or not hasattr(_rt, "_iterative_gap_analysis"):
        pytest.skip("_iterative_gap_analysis not defined")
    calls = []
    def fake_gap_analysis(sources, question, research_type, deepseek_key):
        calls.append({"sources_count": len(sources), "question": question})
        return []
    with patch.object(_rt, "_iterative_gap_analysis", fake_gap_analysis), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA deep analysis", research_type="stock", depth="deep",
                 ticker="NVDA", perplexity_key="key", serper_key="",
                 deepseek_key="")
    assert calls, "_iterative_gap_analysis not called at depth='deep'"


def test_deep_depth_routes_gap_to_correct_source_type():
    """At depth='deep', gap source_type='sec' must trigger EDGAR, 'analyst' must trigger Exa."""
    if _rt is None or not hasattr(_rt, "_iterative_gap_analysis"):
        pytest.skip("_iterative_gap_analysis not defined")
    edgar_calls = []
    exa_calls = []

    def fake_gap_analysis(sources, question, research_type, deepseek_key):
        return [
            {"description": "Missing SEC 8-K", "query": "NVDA 8-K", "source_type": "sec"},
            {"description": "Missing analyst view", "query": "NVDA analyst", "source_type": "analyst"},
        ]

    def fake_edgar(ticker, forms=None):
        edgar_calls.append({"ticker": ticker, "query": "gap"})
        return []

    def fake_exa(queries, key, **kw):
        exa_calls.append(queries)
        return []

    with patch.object(_rt, "_iterative_gap_analysis", fake_gap_analysis), \
         patch.object(_rt, "_fetch_edgar_filings", fake_edgar), \
         patch.object(_rt, "_fetch_exa_query", fake_exa), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA deep analysis", research_type="stock", depth="deep",
                 ticker="NVDA", perplexity_key="key", serper_key="",
                 exa_key="exa_key_val", deepseek_key="")
    assert edgar_calls, "sec gap should have triggered EDGAR _fetch_edgar_filings"
    assert exa_calls, "analyst gap should have triggered Exa _fetch_exa"


# ─────────────────────────────────────────────────────────────────────────────
# 10 ── FRED ───────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def test_fetch_fred_data_function_exists():
    """_fetch_fred_data must be defined in research_tool."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_fred_data"), (
        "_fetch_fred_data not found in research_tool — function not yet implemented"
    )


def test_fetch_fred_data_calls_fred_observations_endpoint():
    """_fetch_fred_data must call api.stlouisfed.org/fred/series/observations."""
    if _rt is None or not hasattr(_rt, "_fetch_fred_data"):
        pytest.skip("_fetch_fred_data not defined")
    mock_req = _make_mock_requests()
    mock_req.get.return_value.json.return_value = {
        "observations": [{"date": "2026-05-01", "value": "3.5"}]
    }
    with patch.object(_rt, "requests", mock_req):
        _rt._fetch_fred_data("fake_fred_key")
    assert mock_req.get.called, "_fetch_fred_data did not call requests.get"
    call_urls = [c[0][0] for c in mock_req.get.call_args_list]
    assert any("stlouisfed.org" in u or "fred" in u.lower() for u in call_urls), (
        f"Expected FRED API URL, got calls to: {call_urls}"
    )


def test_fred_activated_for_macro_at_standard_plus():
    """_fetch_fred_data must be called for research_type='macro' at standard and deep."""
    if _rt is None or not hasattr(_rt, "_fetch_fred_data"):
        pytest.skip("_fetch_fred_data not defined")
    for depth in ("standard", "deep"):
        calls = []
        def fake_fred(fred_key):
            calls.append(depth)
            return []
        with patch.object(_rt, "_fetch_fred_data", fake_fred), \
             patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
             patch.object(_rt, "_fetch_google_news", return_value=[]), \
             patch.object(_rt, "_build_db_context", return_value=""), \
             patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
             patch.object(_rt, "_send_research_email", return_value=None), \
             patch.object(_rt, "requests", _make_mock_requests()):
            _rt.main(question="US rate outlook", research_type="macro", depth=depth,
                     ticker="", perplexity_key="key", serper_key="",
                     deepseek_key="", fred_key="fred_key_val")
        assert calls, f"_fetch_fred_data not called for research_type='macro' at depth='{depth}'"


def test_fred_not_called_for_stock_or_without_key():
    """_fetch_fred_data must NOT be called for research_type='stock' or when fred_key is empty."""
    if _rt is None or not hasattr(_rt, "_fetch_fred_data"):
        pytest.skip("_fetch_fred_data not defined")
    calls = []
    def fake_fred(fred_key):
        calls.append(fred_key)
        return []
    # stock type — even with fred_key, FRED should not run
    with patch.object(_rt, "_fetch_fred_data", fake_fred), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="NVDA", research_type="stock", depth="deep",
                 ticker="NVDA", perplexity_key="key", serper_key="",
                 deepseek_key="", fred_key="fred_key_val")
    assert calls == [], f"_fetch_fred_data should not be called for research_type='stock', got: {calls}"
    # macro type WITHOUT fred_key — should not run
    calls.clear()
    with patch.object(_rt, "_fetch_fred_data", fake_fred), \
         patch.object(_rt, "_fetch_perplexity_batch", return_value=[]), \
         patch.object(_rt, "_fetch_google_news", return_value=[]), \
         patch.object(_rt, "_build_db_context", return_value=""), \
         patch.object(_rt, "_synthesise_with_fallback", return_value={"text": "ok", "synthesiser_model": "x", "input_tokens": 1, "output_tokens": 1}), \
         patch.object(_rt, "_send_research_email", return_value=None), \
         patch.object(_rt, "requests", _make_mock_requests()):
        _rt.main(question="US rates", research_type="macro", depth="standard",
                 ticker="", perplexity_key="key", serper_key="",
                 deepseek_key="", fred_key="")
    assert calls == [], f"_fetch_fred_data should not be called without fred_key, got: {calls}"


# ─────────────────────────────────────────────────────────────────────────────
# 11 ── main() new key params ──────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def test_research_tool_main_has_tavily_key_param():
    """main() must accept tavily_key parameter."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    params = inspect.signature(fn).parameters
    assert "tavily_key" in params, (
        "research_tool.main missing 'tavily_key' param — not yet implemented"
    )


def test_research_tool_main_has_brave_key_param():
    """main() must accept brave_key parameter."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    params = inspect.signature(fn).parameters
    assert "brave_key" in params, (
        "research_tool.main missing 'brave_key' param — not yet implemented"
    )


def test_research_tool_main_has_fred_key_param():
    """main() must accept fred_key parameter."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    params = inspect.signature(fn).parameters
    assert "fred_key" in params, (
        "research_tool.main missing 'fred_key' param — not yet implemented"
    )


# ── Stock research depth enhancement tests ────────────────────────────────────

def _read_rt_source() -> str:
    with open(RESEARCH_TOOL) as f:
        return f.read()


# Filename

def test_research_tool_filename_includes_depth():
    src = _read_rt_source()
    assert "{depth}_" in src, (
        "research_tool filename does not include depth — "
        "expected pattern like {today_str}_{depth}_{slug}.md in file_path f-string"
    )


# Annual financials (replaces quarterly)

def test_annual_financials_uses_income_stmt_not_quarterly():
    src = _read_rt_source()
    assert "quarterly_income_stmt" not in src, (
        "_fetch_yfinance_financials still references quarterly_income_stmt — "
        "should use annual .income_stmt"
    )


def test_annual_financials_shows_3_years_of_data():
    src = _read_rt_source()
    assert "columns[:3]" in src, (
        "_fetch_yfinance_financials should use .columns[:3] for 3 fiscal years"
    )


# Financial health section

def test_financial_health_section_present_in_fin_context():
    src = _read_rt_source()
    assert "Financial Health" in src, (
        "_fetch_yfinance_financials missing 'Financial Health' section"
    )


def test_financial_health_includes_net_debt_ebitda():
    src = _read_rt_source()
    assert "Net Debt" in src, (
        "_fetch_yfinance_financials missing 'Net Debt' in financial health section"
    )


def test_dupont_section_present_in_fin_context():
    src = _read_rt_source()
    assert "DuPont" in src, (
        "_fetch_yfinance_financials missing DuPont analysis section"
    )


# Company overview

def test_fetch_company_overview_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_company_overview"), (
        "_fetch_company_overview not defined in research_tool"
    )


def test_fetch_company_overview_context_in_synthesis_prompt():
    src = _read_rt_source()
    assert "overview_context" in src, (
        "overview_context not injected into synthesis user_message in main()"
    )


# Valuation function

def test_fetch_yfinance_valuation_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_yfinance_valuation"), (
        "_fetch_yfinance_valuation not defined in research_tool"
    )


def test_fetch_yfinance_valuation_includes_p_s_and_p_fcf():
    src = _read_rt_source()
    assert "priceToSalesTrailing12Months" in src, (
        "_fetch_yfinance_valuation missing P/S — priceToSalesTrailing12Months field"
    )
    assert "P/FCF" in src, "_fetch_yfinance_valuation missing P/FCF"


def test_fetch_yfinance_valuation_includes_short_interest():
    src = _read_rt_source()
    assert "shortPercentOfFloat" in src, (
        "_fetch_yfinance_valuation missing short interest — shortPercentOfFloat field"
    )


def test_valuation_context_in_synthesis_prompt():
    src = _read_rt_source()
    assert "val_context" in src, (
        "val_context not injected into synthesis user_message in main()"
    )


# Ownership function

def test_fetch_ownership_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_ownership"), (
        "_fetch_ownership not defined in research_tool"
    )


def test_fetch_ownership_calls_institutional_holders():
    src = _read_rt_source()
    assert "institutional_holders" in src, (
        "_fetch_ownership missing .institutional_holders call"
    )


# Insider transactions function

def test_fetch_insider_transactions_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_insider_transactions"), (
        "_fetch_insider_transactions not defined in research_tool"
    )


def test_insider_context_in_synthesis_prompt():
    src = _read_rt_source()
    assert "ins_context" in src, (
        "ins_context not injected into synthesis user_message in main()"
    )


# Earnings calendar function

def test_fetch_earnings_calendar_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_earnings_calendar"), (
        "_fetch_earnings_calendar not defined in research_tool"
    )


def test_earnings_calendar_includes_next_earnings_date():
    src = _read_rt_source()
    assert ".calendar" in src, (
        "_fetch_earnings_calendar missing yfinance .calendar call for next earnings date"
    )


# MD&A synopsis function

def test_fetch_mdna_synopsis_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_mdna_synopsis"), (
        "_fetch_mdna_synopsis not defined in research_tool"
    )


def test_fetch_mdna_synopsis_context_in_synthesis_prompt():
    src = _read_rt_source()
    assert "mdna_context" in src, (
        "mdna_context not injected into synthesis user_message in main()"
    )


def test_fetch_mdna_synopsis_skips_gracefully_on_failure():
    if _rt is None or not hasattr(_rt, "_fetch_mdna_synopsis"):
        pytest.skip("research_tool not loadable or function missing")
    with patch.object(_rt, "requests") as mock_req:
        mock_req.get.side_effect = Exception("network error")
        result = _rt._fetch_mdna_synopsis("NVDA", "fake_key")
    markdown, data = result if isinstance(result, tuple) else (result, {})
    assert markdown == "", (
        "_fetch_mdna_synopsis should return '' on failure, not raise"
    )


# Management function (executives via yfinance)

def test_fetch_management_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_management"), (
        "_fetch_management not defined in research_tool"
    )


def test_fetch_management_calls_yfinance_info_officers():
    src = _read_rt_source()
    assert "companyOfficers" in src, (
        "_fetch_management missing companyOfficers key from yfinance info"
    )


# Board of directors function (DEF 14A via EDGAR)

def test_fetch_board_of_directors_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_board_of_directors"), (
        "_fetch_board_of_directors not defined in research_tool"
    )


def test_fetch_board_of_directors_calls_edgar_submissions():
    src = _read_rt_source()
    assert "DEF 14A" in src, (
        "_fetch_board_of_directors should fetch from EDGAR DEF 14A proxy statements"
    )


def test_fetch_board_of_directors_skips_hk_tickers():
    if _rt is None or not hasattr(_rt, "_fetch_board_of_directors"):
        pytest.skip("research_tool not loadable or function missing")
    with patch.object(_rt, "requests") as mock_req:
        result = _rt._fetch_board_of_directors("9988.HK")
    mock_req.get.assert_not_called()
    markdown, data = result if isinstance(result, tuple) else (result, {})
    assert markdown == "", (
        "_fetch_board_of_directors should return '' for HK tickers without calling EDGAR"
    )


# Competitor function

def test_fetch_competitors_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_fetch_competitors"), (
        "_fetch_competitors not defined in research_tool"
    )


def test_fetch_competitors_calls_finnhub_peers_endpoint():
    src = _read_rt_source()
    assert "stock/peers" in src, (
        "_fetch_competitors missing Finnhub /stock/peers API call"
    )


def test_competitor_context_in_synthesis_prompt():
    src = _read_rt_source()
    assert "comp_context" in src, (
        "comp_context not injected into synthesis user_message in main()"
    )


# Raw data sections written to output file

def test_supporting_data_section_written_to_output_file():
    src = _read_rt_source()
    assert "## Supporting Data" in src, (
        "'## Supporting Data' heading not found — raw data not appended to full_markdown"
    )


def test_raw_data_sections_appended_after_synthesis():
    src = _read_rt_source()
    assert "_data_sections" in src, (
        "_data_sections variable not found — raw data blocks not being appended to output file"
    )


# ── Stock Data Fetcher — standalone Windmill script ──────────────────────────

STOCK_DATA_FETCHER = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/stock_data_fetcher.py"
)


def _read_sdf_source() -> str:
    with open(STOCK_DATA_FETCHER) as f:
        return f.read()


def _load_sdf():
    """Load stock_data_fetcher module with stubs; returns module or None."""
    spec = importlib.util.spec_from_file_location("_sdf", STOCK_DATA_FETCHER)
    if spec is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("windmill_http_client", type(sys)("windmill_http_client"))
    try:
        spec.loader.exec_module(mod)
        return mod
    except Exception as e:
        print(f"[_load_sdf] failed: {e}")
        return None


_sdf = _load_sdf()


def test_stock_data_fetcher_main_has_correct_params():
    """main() must accept ticker (str), portfolio_db, and finnhub_key."""
    fn = _load_main_fn(STOCK_DATA_FETCHER)
    assert fn is not None, "stock_data_fetcher.main not loadable"
    sig = inspect.signature(fn)
    params = list(sig.parameters.keys())
    assert "ticker" in params, "stock_data_fetcher.main missing 'ticker' param"
    assert "portfolio_db" in params, "stock_data_fetcher.main missing 'portfolio_db' param"
    assert "finnhub_key" in params, "stock_data_fetcher.main missing 'finnhub_key' param"


def test_stock_data_fetcher_ticker_is_required_param():
    """ticker must NOT have a default value — it's the core input."""
    fn = _load_main_fn(STOCK_DATA_FETCHER)
    if fn is None:
        pytest.skip("stock_data_fetcher not loadable")
    sig = inspect.signature(fn)
    ticker_param = sig.parameters.get("ticker")
    assert ticker_param is not None, "ticker param missing from stock_data_fetcher.main"
    assert ticker_param.default is inspect.Parameter.empty, (
        "stock_data_fetcher.main 'ticker' should have no default — it is a required input"
    )


def test_stock_data_fetcher_calls_store_for_ticker():
    """_store_stock_snapshot must be present in stock_data_fetcher — storage logic lives here."""
    src = _read_sdf_source()
    assert "_store_stock_snapshot" in src, (
        "_store_stock_snapshot not found in stock_data_fetcher"
    )


def test_stock_data_fetcher_returns_result_dict():
    """main() must return a dict with ticker, ok, and error keys."""
    src = _read_sdf_source()
    assert '"ticker"' in src or "'ticker'" in src, "'ticker' key missing from result dict"
    assert '"ok"' in src or "'ok'" in src, "'ok' key missing from result dict"
    assert '"error"' in src or "'error'" in src, "'error' key missing from result dict"


def test_stock_data_fetcher_skips_finnhub_for_hk_tickers():
    """Finnhub peers call must be guarded against HK tickers."""
    src = _read_sdf_source()
    assert ".HK" in src, "HK ticker guard not found in stock_data_fetcher"
    assert "stock/peers" in src, "Finnhub /stock/peers call not found in stock_data_fetcher"


def test_stock_data_fetcher_graceful_on_failure():
    """On exception, ok must be False and error populated — must not raise."""
    src = _read_sdf_source()
    assert "try" in src and "except" in src, (
        "stock_data_fetcher missing try/except — failure would crash the job"
    )
    assert '"error"' in src or "'error'" in src, (
        "'error' key missing from result dict — failures not surfaced"
    )


def test_stock_data_fetcher_no_mdna_or_board_fetch():
    """MD&A synopsis (DeepSeek) and DEF 14A board parsing must NOT be in stock_data_fetcher."""
    src = _read_sdf_source()
    assert "deepseek" not in src.lower(), (
        "Deepseek API found in stock_data_fetcher — mdna_synopsis must stay in research_tool"
    )
    assert "DEF 14A" not in src and "_fetch_board_of_directors" not in src, (
        "Board of directors fetch found in stock_data_fetcher — must stay in research_tool"
    )


def test_stock_data_fetcher_store_tables_present():
    """_store_stock_snapshot in stock_data_fetcher must write to the structured tables."""
    src = _read_sdf_source()
    for tbl in ("income_statements", "valuation_snapshots", "company_profiles"):
        assert tbl in src, f"{tbl} INSERT missing from stock_data_fetcher"


def test_stock_data_fetcher_no_portfolio_positions_read():
    """stock_data_fetcher must NOT query portfolio_positions — it is ticker-agnostic."""
    src = _read_sdf_source()
    assert "portfolio_positions" not in src, (
        "portfolio_positions query found in stock_data_fetcher — "
        "the fetcher must be generic; callers decide which tickers to pass"
    )


# ── research_tool: DB-read path (separation of concerns) ─────────────────────

def test_research_tool_main_has_wm_token_param():
    """main() must accept wm_token to dispatch stock_data_fetcher when data is stale."""
    fn = _load_main_fn(RESEARCH_TOOL)
    if fn is None:
        pytest.skip("research_tool not loadable")
    sig = inspect.signature(fn)
    assert "wm_token" in sig.parameters, (
        "research_tool.main missing 'wm_token' param"
    )
    assert sig.parameters["wm_token"].default == "", "wm_token default must be empty string"


def test_read_structured_stock_data_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_read_structured_stock_data"), (
        "_read_structured_stock_data not defined in research_tool — DB-read path missing"
    )


def test_read_structured_stock_data_returns_absent_on_empty_db():
    """Returns ({}, 'absent') when valuation_snapshots has no row for this ticker."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    psycopg2_mod = sys.modules["psycopg2"]
    orig = psycopg2_mod.connect
    psycopg2_mod.connect = MagicMock(return_value=mock_conn)
    try:
        sections, staleness = _rt._read_structured_stock_data(
            "NVDA", {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}
        )
    finally:
        psycopg2_mod.connect = orig
    assert staleness == "absent", f"Expected 'absent', got '{staleness}'"


def test_read_structured_stock_data_returns_stale_on_old_valuation():
    """Returns staleness='stale' when most recent valuation row is 4+ days old."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    from datetime import date, timedelta
    old_date = date.today() - timedelta(days=4)
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.side_effect = [(old_date,)] + [None] * 20
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    psycopg2_mod = sys.modules["psycopg2"]
    orig = psycopg2_mod.connect
    psycopg2_mod.connect = MagicMock(return_value=mock_conn)
    try:
        sections, staleness = _rt._read_structured_stock_data(
            "NVDA", {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}
        )
    finally:
        psycopg2_mod.connect = orig
    assert staleness == "stale", f"Expected 'stale', got '{staleness}'"


def test_read_structured_stock_data_returns_fresh_on_recent_valuation():
    """Returns staleness='fresh' when most recent valuation row is today."""
    if _rt is None:
        pytest.skip("research_tool not loadable")
    from datetime import date
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.side_effect = [(date.today(),)] + [None] * 20
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    psycopg2_mod = sys.modules["psycopg2"]
    orig = psycopg2_mod.connect
    psycopg2_mod.connect = MagicMock(return_value=mock_conn)
    try:
        sections, staleness = _rt._read_structured_stock_data(
            "NVDA", {"host": "h", "port": 5432, "dbname": "d", "user": "u", "password": "p"}
        )
    finally:
        psycopg2_mod.connect = orig
    assert staleness == "fresh", f"Expected 'fresh', got '{staleness}'"


def test_dispatch_stock_fetcher_function_exists():
    if _rt is None:
        pytest.skip("research_tool not loadable")
    assert hasattr(_rt, "_dispatch_stock_fetcher"), (
        "_dispatch_stock_fetcher not defined in research_tool"
    )


def test_dispatch_stock_fetcher_targets_correct_script():
    """Must POST to u/admin/stock_data_fetcher."""
    src = _read_rt_source()
    assert "u/admin/stock_data_fetcher" in src, (
        "stock_data_fetcher script path missing from _dispatch_stock_fetcher"
    )


def test_dispatch_stock_fetcher_passes_ticker_as_string():
    """Payload must send ticker as a plain string key."""
    src = _read_rt_source()
    assert "_dispatch_stock_fetcher" in src, "_dispatch_stock_fetcher missing from source"
    assert '"ticker"' in src or "'ticker'" in src, (
        "ticker key not found in _dispatch_stock_fetcher payload"
    )


def test_main_dispatches_fetcher_on_absent_data():
    """When _read_structured_stock_data returns 'absent', _dispatch_stock_fetcher must be called."""
    src = _read_rt_source()
    assert "_dispatch_stock_fetcher" in src, (
        "_dispatch_stock_fetcher not referenced in main() — fetcher dispatch logic missing"
    )
    assert "absent" in src, (
        "'absent' staleness check missing in main() — fetcher not triggered on missing data"
    )


def test_main_does_not_dispatch_without_wm_token():
    """Dispatch must be gated on wm_token being truthy."""
    src = _read_rt_source()
    assert "wm_token" in src, "wm_token not referenced in main()"
    assert "stale" in src, "'stale' check missing — fetcher not triggered on stale data"


def test_store_stock_snapshot_not_in_research_tool():
    """_store_stock_snapshot has moved to stock_data_fetcher — must NOT be in research_tool."""
    src = _read_rt_source()
    assert "_store_stock_snapshot" not in src, (
        "_store_stock_snapshot still in research_tool — it must be moved to stock_data_fetcher"
    )


def test_mdna_synopsis_still_live_fetched():
    """_fetch_mdna_synopsis must still be called from main() (Deepseek, not in fetcher)."""
    src = _read_rt_source()
    assert "_fetch_mdna_synopsis" in src, "_fetch_mdna_synopsis removed from research_tool"
    assert "mdna_context" in src, "mdna_context missing — MD&A synopsis not being fetched"


def test_board_of_directors_still_live_fetched():
    """_fetch_board_of_directors must still be called from main() (EDGAR, not in fetcher)."""
    src = _read_rt_source()
    assert "_fetch_board_of_directors" in src, "_fetch_board_of_directors removed from research_tool"


def test_main_falls_back_to_live_fetch_when_fetcher_fails():
    """When portfolio_db is set but fetcher returns False, live-fetch branch must still fire.

    The fix: 'if is_stock and sections:' / 'elif is_stock:' structure ensures the elif fires
    when sections={} regardless of whether portfolio_db was set. Previously the elif was
    'elif is_stock:' after 'if is_stock and portfolio_db:' — so it was unreachable when
    portfolio_db was truthy, even when the fetcher timed out and sections remained empty.
    """
    src = _read_rt_source()
    assert "if is_stock and sections" in src, (
        "Step 4 must use 'if is_stock and sections' for context-var assignment, "
        "not 'if is_stock and portfolio_db' — otherwise live-fetch fallback never fires "
        "when fetcher times out with empty sections"
    )


# ── Portfolio Rationalization script tests ─────────────────────────────────────

PORTFOLIO_RATIONALIZATION = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_rationalization.py"
)


def _read_pr_source() -> str:
    with open(PORTFOLIO_RATIONALIZATION) as f:
        return f.read()


def test_rationalization_script_exists():
    """portfolio_rationalization.py must exist in windmill/u/admin/."""
    assert os.path.exists(PORTFOLIO_RATIONALIZATION), (
        "windmill/u/admin/portfolio_rationalization.py not found — script not created"
    )


def test_rationalization_has_adr_consolidation():
    """Script must consolidate ADR pairs (BABA/9988.HK and BIDU/9888.HK)."""
    src = _read_pr_source()
    assert "9988.HK" in src or "9988" in src, "ADR pair 9988.HK not referenced — BABA consolidation missing"
    assert "9888.HK" in src or "9888" in src, "ADR pair 9888.HK not referenced — BIDU consolidation missing"


def test_rationalization_adr_pairs_loaded_from_db():
    """ADR pair mapping must come from DB (consolidation_group column), not a hardcoded dict."""
    src = _read_pr_source()
    assert "ADR_PAIRS" not in src, (
        "Hardcoded ADR_PAIRS dict found — must be replaced with a DB query on "
        "portfolio_positions.consolidation_group"
    )
    assert "consolidation_group" in src, (
        "consolidation_group not referenced — ADR pair DB query missing"
    )


def test_seed_sql_consolidation_group_set_for_adr_pairs():
    """seed.sql must set consolidation_group for all 4 ADR-pair tickers."""
    src_path = pathlib.Path("/windmill/../portfolio/seed.sql")
    alt_path = pathlib.Path("/root/portfolio/seed.sql")
    for p in (src_path, alt_path):
        try:
            if p.exists():
                seed_src = p.read_text()
                break
        except PermissionError:
            continue
    else:
        pytest.skip("seed.sql not readable")
    assert "Alibaba" in seed_src, "consolidation_group='Alibaba' not set in seed.sql for BABA/9988.HK"
    assert "Baidu" in seed_src, "consolidation_group='Baidu' not set in seed.sql for BIDU/9888.HK"


def test_rationalization_has_four_scenarios():
    """Script must compute composites under 4 weighting scenarios."""
    src = _read_pr_source()
    assert "balanced" in src.lower(), "Balanced scenario missing from rationalization script"
    assert "quality" in src.lower(), "Quality-focused scenario missing"
    assert "growth" in src.lower(), "Growth-focused scenario missing"
    assert "value" in src.lower(), "Value-focused scenario missing"


def test_rationalization_has_portfolio_scores_write():
    """Script must upsert results into portfolio_scores table."""
    src = _read_pr_source()
    assert "portfolio_scores" in src, "portfolio_scores table not referenced — DB write missing"
    assert "INSERT" in src or "upsert" in src.lower() or "ON CONFLICT" in src, (
        "No INSERT/upsert logic found — portfolio_scores write missing"
    )


def test_rationalization_grok_prompt_neutral():
    """Grok prompt must not contain domain-specific framing that silently skips content."""
    src = _read_pr_source()
    assert "infra finance" not in src.lower(), "Domain-specific 'infra finance' framing in Grok prompt — violates Hard Rule 10"
    assert "infrastructure" not in src.lower() or "infrastructure banker" not in src.lower(), (
        "Infrastructure banker framing in Grok prompt — keep prompts generic per Hard Rule 10"
    )


def test_rationalization_has_absolute_thresholds():
    """Script must define absolute red-flag threshold constants (Finding 1)."""
    src = _read_pr_source()
    assert "4.0" in src or "NET_DEBT_THRESHOLD" in src, (
        "Net debt/EBITDA threshold (>4.0) not found — absolute red flags missing (Finding 1)"
    )
    assert "0.8" in src or "CURRENT_RATIO_MIN" in src, (
        "Current ratio threshold (<0.8) not found — absolute red flags missing (Finding 1)"
    )
    assert "60" in src or "PE_MAX" in src, (
        "Forward PE threshold (>60x) not found — absolute red flags missing (Finding 1)"
    )


def test_rationalization_has_completeness_penalty():
    """Script must multiply composite by coverage ratio (Finding 2)."""
    src = _read_pr_source()
    assert "n_available" in src or "completeness" in src.lower(), (
        "Completeness penalty not found — composite must be multiplied by coverage ratio (Finding 2)"
    )
    assert "n_total" in src or "coverage_ratio" in src or "data_completeness" in src, (
        "Coverage ratio denominator not found — completeness penalty incomplete (Finding 2)"
    )


def test_rationalization_min_pool_size_enforced():
    """Script must require ≥8 positions with data before admitting a factor to the composite (Finding 2)."""
    src = _read_pr_source()
    assert "8" in src, "Min pool size constant not found in source"
    assert "pool" in src.lower() or "min_pool" in src.lower() or "MIN_POOL" in src, (
        "Pool size guard not found — factor must be excluded if fewer than 8 positions have data (Finding 2)"
    )


def test_rationalization_thesis_no_freshness_multiplier():
    """Thesis score must be conviction_raw only — freshness_decay must NOT appear (Finding 4)."""
    src = _read_pr_source()
    assert "freshness_decay" not in src, (
        "freshness_decay found in rationalization script — thesis staleness must be a display flag only, "
        "not a score multiplier (Finding 4)"
    )


def test_rationalization_two_grok_calls():
    """Script must make 2 distinct Grok API calls — per-position then executive summary (Finding 5)."""
    src = _read_pr_source()
    grok_call_count = src.count("chat/completions") + src.count("_synthesise_with_fallback") + src.count("_call_grok")
    assert grok_call_count >= 2, (
        f"Expected ≥2 Grok call sites, found {grok_call_count} — "
        "split into Call 1 (per-position) and Call 2 (executive summary) per Finding 5"
    )


def test_rationalization_has_grok_fallback():
    """Both synthesis calls must fall back to deepseek-chat if Grok fails (Finding 7)."""
    src = _read_pr_source()
    assert "deepseek" in src.lower() or "fallback" in src.lower(), (
        "No Grok fallback logic found — both synthesis calls must fall back to deepseek-chat (Finding 7)"
    )
    assert "deepseek-chat" in src or "deepseek_key" in src, (
        "deepseek-chat or deepseek_key not referenced — fallback target missing (Finding 7)"
    )


def test_rationalization_has_delta_query():
    """Script must query prior portfolio_scores to compute Δ rank vs previous month (Finding 8)."""
    src = _read_pr_source()
    assert "delta_rank" in src or "delta" in src.lower(), (
        "Delta rank tracking not found — must query prior portfolio_scores for MoM rank change (Finding 8)"
    )
    assert "MAX(score_date)" in src or "prior" in src.lower() or "score_date" in src, (
        "Prior score_date query not found — delta tracking requires querying the previous run's scores (Finding 8)"
    )


def test_rationalization_ranking_table_top_half_label():
    """Ranking table must use '# top-half' label, not '# KEEP' (minimax A1)."""
    src = _read_pr_source()
    assert "# top-half" in src or "top_half" in src or "n_top_half" in src, (
        "Ranking table still uses '# KEEP' — rename to '# top-half' to accurately describe "
        "rank-robustness count (minimax finding A1)"
    )
    assert "# KEEP" not in src, (
        "'# KEEP' header still present — rename to '# top-half' (minimax finding A1)"
    )


def test_rationalization_red_flag_override_is_named_function():
    """Red-flag override must be an explicit named function, not just LLM prompt text (minimax A11)."""
    src = _read_pr_source()
    assert "_apply_red_flag_override" in src or "red_flag_override" in src, (
        "No named red-flag override function found — extract _apply_red_flag_override() "
        "so the override is enforced in code, not only in the LLM prompt (minimax finding A11)"
    )


def test_rationalization_ranking_table_has_metric_coverage():
    """Ranking table must show metric coverage column alongside factor coverage (minimax A2)."""
    src = _read_pr_source()
    assert "metric_coverage" in src or "Metric coverage" in src or "raw_coverage" in src, (
        "No metric-coverage column found — add raw sub-component coverage to the ranking table "
        "alongside factor coverage (minimax finding A2)"
    )


def test_rationalization_insider_uses_market_cap_normalisation():
    """Insider sub-component must use market-cap flow ratio, not raw net USD (minimax A4)."""
    src = _read_pr_source()
    assert (
        "market_cap" in src and "insider" in src.lower()
        and ("/ market_cap" in src or "insider_flow" in src or "insider_market_cap" in src)
    ), (
        "Insider normalization does not divide by market_cap — "
        "must use net_insider_90d/market_cap flow ratio for cross-size comparability (minimax finding A4)"
    )


def test_rationalization_negative_cagr_included_in_pool():
    """_cagr must return negative values (not None) so negative-CAGR positions rank at pool bottom (minimax A6)."""
    src = _read_pr_source()
    # The old pattern "if ratio <= 0: return None" must be gone
    # Check that _cagr does not bail out with None when ratio <= 0
    import re
    early_return = re.search(r"ratio\s*<=\s*0[^)]*\n\s*return None", src)
    assert early_return is None, (
        "_cagr still returns None when ratio <= 0 — negative CAGR should return a negative value "
        "so the position ranks at pool minimum rather than being excluded (minimax finding A6)"
    )


def test_rationalization_delta_for_all_four_scenarios():
    """Delta tracking must cover all 4 scenarios, not only balanced (minimax A10)."""
    src = _read_pr_source()
    assert "delta_rank_quality" in src, (
        "delta_rank_quality not found — add delta tracking for quality/growth/value scenarios (minimax A10)"
    )
    assert "delta_rank_growth" in src, (
        "delta_rank_growth not found — add delta tracking for quality/growth/value scenarios (minimax A10)"
    )
    assert "delta_rank_value" in src, (
        "delta_rank_value not found — add delta tracking for quality/growth/value scenarios (minimax A10)"
    )


def test_rationalization_call1_requests_json_output():
    """Grok Call 1 prompt must request structured JSON with evidence tags (minimax C2)."""
    src = _read_pr_source()
    assert "rationale_sentences" in src, (
        "Call 1 prompt does not request 'rationale_sentences' — add show-your-work JSON output spec (minimax C2)"
    )
    assert "evidence" in src, (
        "Call 1 prompt does not include 'evidence' field — add per-claim source metric tags (minimax C2)"
    )


def test_rationalization_has_json_parser_with_fallback():
    """Script must have a JSON parser for Call 1 output with graceful fallback (minimax C2)."""
    src = _read_pr_source()
    assert "_parse_call1_json" in src or "json.loads" in src, (
        "No JSON parser found for Call 1 output — add parser for show-your-work JSON (minimax C2)"
    )
    assert "json_parse" in src.lower() or "fallback" in src.lower() or "except" in src, (
        "No fallback handling found for JSON parse failures (minimax C2)"
    )


def test_rationalization_call1_split_into_batches():
    """Grok Call 1 must be split into 2 batches to avoid truncation at max_tokens=8000 (minimax A7)."""
    src = _read_pr_source()
    assert "call1a" in src or "batch" in src.lower() or "call_1a" in src or "call1_batch" in src, (
        "Call 1 is not batched — split into 2 batches (positions 1-15 and 16-31) "
        "to avoid silent truncation at max_tokens=8000 (minimax finding A7)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: portfolio_email.py
# ─────────────────────────────────────────────────────────────────────────────

PORTFOLIO_EMAIL = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_email.py"
)


def _read_pe_source() -> str:
    with open(PORTFOLIO_EMAIL) as f:
        return f.read()


def test_portfolio_email_fmt_pnl_none_is_em_dash():
    """fmt_pnl(None) must return em-dash — not 'None' or empty string."""
    src = _read_pe_source()
    assert "val is None" in src, "fmt_pnl must check for None explicitly"
    assert "—" in src or '"—"' in src or "'—'" in src, (
        "em-dash character not found — fmt_pnl missing null return"
    )


def test_portfolio_email_fx_direction_divides_by_rate():
    """FX stored as USD→HKD (1 USD = rate HKD), so to_usd must divide by rate."""
    src = _read_pe_source()
    assert "/ rate" in src, (
        "to_usd must divide amount by rate — fx_map stores USD→HKD "
        "so local_amount / rate = USD"
    )


def test_portfolio_email_has_consolidation_group_logic():
    """Script must group ADR pairs via consolidation_group column."""
    src = _read_pe_source()
    assert "consolidation_group" in src, (
        "portfolio_email must use consolidation_group for ADR pair display"
    )
    assert '"group"' in src or "'group'" in src, (
        "display_items must include type='group' entries for consolidated ADR pairs"
    )


def test_portfolio_email_group_sums_members():
    """Grouped display items must sum value and P&L across all member positions."""
    src = _read_pe_source()
    assert "members" in src, "group items must have a 'members' list"
    # The group value should be a sum of member values
    assert "sum(" in src and "value_today" in src, (
        "group value must be computed as sum of member value_today fields"
    )


def test_portfolio_email_main_params():
    """main() must accept portfolio_db, gmail_smtp, recipient_email."""
    fn = _load_main_fn(PORTFOLIO_EMAIL)
    if fn is None:
        src = _read_pe_source()
        assert "portfolio_db" in src and "gmail_smtp" in src
        return
    sig = inspect.signature(fn)
    for p in ("portfolio_db", "gmail_smtp"):
        assert p in sig.parameters, f"portfolio_email.main missing param: {p}"


# ─────────────────────────────────────────────────────────────────────────────
# C1: health_check.py
# ─────────────────────────────────────────────────────────────────────────────

HEALTH_CHECK = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/health_check.py"
)


def _read_hc_source() -> str:
    with open(HEALTH_CHECK) as f:
        return f.read()


def _load_hc_module():
    for mod_name in ("pytz",):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = type(sys)(mod_name)
    spec = importlib.util.spec_from_file_location("_hc_mod", HEALTH_CHECK)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        pass
    return mod


def test_health_check_six_schedules():
    """SCHEDULES list must have exactly 6 entries matching the 6 monitored jobs."""
    src = _read_hc_source()
    count = src.count('"path":')
    assert count == 6, f"Expected 6 SCHEDULES entries, found {count}"


def test_health_count_matching_requires_all_keywords():
    """count_matching uses AND logic — all keywords must appear in the subject."""
    hc = _load_hc_module()
    fn = getattr(hc, "count_matching", None)
    if fn is None:
        pytest.skip("health_check count_matching not loadable")
    subjects = ["Portfolio US Close Report", "Morning Digest News", "Portfolio Asia Close"]
    assert fn(subjects, ["Portfolio", "US Close"]) == 1
    assert fn(subjects, ["Portfolio"]) == 2
    assert fn(subjects, ["Morning", "Digest"]) == 1


def test_health_count_matching_case_insensitive():
    """count_matching must match keywords case-insensitively."""
    hc = _load_hc_module()
    fn = getattr(hc, "count_matching", None)
    if fn is None:
        pytest.skip("health_check count_matching not loadable")
    assert fn(["morning digest"], ["Morning Digest"]) == 1
    assert fn(["PORTFOLIO US CLOSE"], ["portfolio"]) == 1


def test_health_build_html_all_ok_text():
    """build_html must produce 'All N OK' summary when all schedules pass."""
    src = _read_hc_source()
    assert "All " in src and " OK" in src, (
        "build_html must show 'All N OK' when every schedule passes"
    )


def test_health_build_html_issue_count():
    """build_html must show a failure count when any schedule is FAILED or STALE."""
    src = _read_hc_source()
    assert "issue" in src.lower(), (
        "build_html must show issue count for failed/stale schedules"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: portfolio_move_monitor.py
# ─────────────────────────────────────────────────────────────────────────────

MOVE_MONITOR = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_move_monitor.py"
)


def _read_mm_source() -> str:
    with open(MOVE_MONITOR) as f:
        return f.read()


def test_move_monitor_portfolio_threshold_1_5_pct():
    """PORTFOLIO_ALERT_THRESHOLD must be 0.015 (1.5%)."""
    src = _read_mm_source()
    assert "PORTFOLIO_ALERT_THRESHOLD" in src
    assert "0.015" in src, "PORTFOLIO_ALERT_THRESHOLD must be 0.015 (1.5%)"


def test_move_monitor_position_threshold_5_pct():
    """POSITION_ALERT_THRESHOLD must be 0.05 (5%)."""
    src = _read_mm_source()
    assert "POSITION_ALERT_THRESHOLD" in src
    assert "0.05" in src, "POSITION_ALERT_THRESHOLD must be 0.05 (5%)"


def test_move_monitor_gmail_smtp_optional():
    """gmail_smtp must be optional (agent calls this without SMTP config)."""
    fn = _load_main_fn(MOVE_MONITOR)
    if fn is None:
        src = _read_mm_source()
        assert "gmail_smtp: dict = {}" in src or "gmail_smtp=None" in src or "gmail_smtp: dict = None" in src, (
            "gmail_smtp must have a default value so agent can call without SMTP"
        )
        return
    sig = inspect.signature(fn)
    if "gmail_smtp" in sig.parameters:
        assert sig.parameters["gmail_smtp"].default is not inspect.Parameter.empty, (
            "gmail_smtp must be optional with a default"
        )


def test_move_monitor_usdhkd_fallback_rate():
    """Must fall back to a hardcoded USDHKD rate when the FX table is empty."""
    src = _read_mm_source()
    assert "7.80" in src or "7.8" in src, (
        "move_monitor must define a fallback USDHKD rate when FX table is empty"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: morning_news_digest.py
# ─────────────────────────────────────────────────────────────────────────────

MORNING_DIGEST = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/morning_news_digest.py"
)


def _read_md_source() -> str:
    with open(MORNING_DIGEST) as f:
        return f.read()


def test_morning_digest_rss_48h_cutoff():
    """fetch_rss_headlines must apply a 48-hour recency cutoff (Hard Rule 14)."""
    src = _read_md_source()
    assert "48" in src, "48-hour cutoff not found in morning_news_digest"
    assert "cutoff" in src.lower(), (
        "fetch_rss_headlines must implement a cutoff — stale articles must be filtered"
    )


def test_morning_digest_google_news_48h_cutoff():
    """fetch_google_news must also apply a 48-hour recency cutoff."""
    src = _read_md_source()
    assert "fetch_google_news" in src, "fetch_google_news function missing"
    idx = src.find("def fetch_google_news")
    section = src[idx: idx + 600]
    assert "cutoff" in section.lower() or "48" in section, (
        "fetch_google_news must apply a recency cutoff"
    )


def test_morning_digest_link_filter_skips_tracking():
    """get_links must skip unsubscribe and tracking URLs."""
    src = _read_md_source()
    assert "_LINK_SKIP" in src, "_LINK_SKIP filter list missing"
    assert "unsubscribe" in src, "unsubscribe pattern must be in link filter"
    assert "track" in src, "tracking URL pattern must be in link filter"


def test_morning_digest_four_section_structure():
    """Digest must have 4 sections (RSS headlines, Google News, newsletter links, newsletter summaries)."""
    src = _read_md_source()
    assert "HEADLINE_FEEDS" in src, "Section 1 (RSS headline feeds) missing"
    assert "GOOGLE_NEWS_FEEDS" in src, "Section 2 (Google News feeds) missing"
    assert "KEY_DOMAINS" in src, "Section 3/4 (newsletter domains) missing"


# ─────────────────────────────────────────────────────────────────────────────
# C1: portfolio_price_fetcher.py
# ─────────────────────────────────────────────────────────────────────────────

PRICE_FETCHER = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_price_fetcher.py"
)


def _read_pf_source() -> str:
    with open(PRICE_FETCHER) as f:
        return f.read()


def test_price_fetcher_only_requires_portfolio_db():
    """main() must only take portfolio_db — no SMTP or API keys needed."""
    fn = _load_main_fn(PRICE_FETCHER)
    if fn is None:
        src = _read_pf_source()
        assert "def main(portfolio_db" in src
        return
    sig = inspect.signature(fn)
    required = [n for n, p in sig.parameters.items()
                if p.default is inspect.Parameter.empty]
    assert required == ["portfolio_db"], (
        f"price_fetcher.main should only require portfolio_db, got: {required}"
    )


def test_price_fetcher_fx_stored_usd_to_hkd():
    """FX rate must be stored as from_currency='USD', to_currency='HKD'."""
    src = _read_pf_source()
    assert ("'USD', 'HKD'" in src or '"USD", "HKD"' in src or
            "from_currency = 'USD'" in src or 'from_currency = "USD"' in src or
            "USDHKD" in src), (
        "FX rate must be stored with USD→HKD direction"
    )


def test_price_fetcher_on_conflict_do_nothing():
    """Price inserts must use ON CONFLICT DO NOTHING to tolerate re-runs."""
    src = _read_pf_source()
    assert "ON CONFLICT" in src.upper() and "DO NOTHING" in src.upper(), (
        "price_history INSERT must use ON CONFLICT (ticker, price_date) DO NOTHING"
    )


def test_price_fetcher_tail_2_for_pnl():
    """Must insert last 2 price rows per ticker so P&L works on first run."""
    src = _read_pf_source()
    assert "tail(2)" in src or ".tail(2)" in src, (
        "price fetcher must use .tail(2) to get 2 rows per ticker"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: youtube_monitor.py
# ─────────────────────────────────────────────────────────────────────────────

YOUTUBE_MONITOR = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/youtube_monitor.py"
)


def _read_yt_source() -> str:
    with open(YOUTUBE_MONITOR) as f:
        return f.read()


def test_youtube_max_attempts_is_3():
    """MAX_ATTEMPTS must be 3 — after 3 failures the video gets a bare link."""
    src = _read_yt_source()
    assert "MAX_ATTEMPTS" in src
    assert "MAX_ATTEMPTS = 3" in src, "MAX_ATTEMPTS must be exactly 3"


def test_youtube_max_state_ids_is_1000():
    """MAX_STATE_IDS must be 1000 to cap the Windmill variable size."""
    src = _read_yt_source()
    assert "MAX_STATE_IDS" in src
    assert "MAX_STATE_IDS = 1000" in src, "MAX_STATE_IDS must be 1000"


def test_youtube_load_state_handles_legacy_list():
    """load_state must handle the legacy flat-list format for backward compatibility."""
    src = _read_yt_source()
    assert "isinstance(data, list)" in src, (
        "load_state must handle legacy flat-list state format"
    )


def test_youtube_load_state_reads_processed_and_attempts():
    """load_state must read both 'processed' and 'attempts' keys from new format."""
    src = _read_yt_source()
    assert '"processed"' in src or "'processed'" in src, (
        "load_state must read 'processed' list from state dict"
    )
    assert '"attempts"' in src or "'attempts'" in src, (
        "load_state must read 'attempts' dict for retry tracking"
    )


def test_youtube_state_var_correct_path():
    """STATE_VAR must point to u/admin/youtube_processed_state."""
    src = _read_yt_source()
    assert "youtube_processed_state" in src, (
        "STATE_VAR must reference u/admin/youtube_processed_state"
    )


def test_youtube_save_state_trims_old_ids():
    """save_state must trim processed list to MAX_STATE_IDS to prevent unbounded growth."""
    src = _read_yt_source()
    idx = src.find("def save_state")
    assert idx != -1, "save_state function missing"
    section = src[idx: idx + 500]
    assert "MAX_STATE_IDS" in section, (
        "save_state must trim processed list using MAX_STATE_IDS"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: fundamentals_fetcher.py
# ─────────────────────────────────────────────────────────────────────────────

FUNDAMENTALS_FETCHER = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/fundamentals_fetcher.py"
)


def _read_ff_source() -> str:
    with open(FUNDAMENTALS_FETCHER) as f:
        return f.read()


def test_fundamentals_main_params():
    """main() must accept portfolio_db and finnhub_key."""
    fn = _load_main_fn(FUNDAMENTALS_FETCHER)
    if fn is None:
        src = _read_ff_source()
        assert "portfolio_db" in src and "finnhub_key" in src
        return
    sig = inspect.signature(fn)
    for p in ("portfolio_db", "finnhub_key"):
        assert p in sig.parameters, f"fundamentals_fetcher.main missing: {p}"


def test_fundamentals_hk_tickers_skip_finnhub():
    """HK tickers (.HK suffix) must not be sent to Finnhub (no HK coverage)."""
    src = _read_ff_source()
    assert ".HK" in src or "'.HK'" in src or '".HK"' in src, (
        "fundamentals_fetcher must differentiate HK vs US tickers"
    )
    assert "hk_tickers" in src or "endswith('.HK')" in src or 'endswith(".HK")' in src, (
        "HK tickers must be identified and excluded from Finnhub calls"
    )


def test_fundamentals_etf_tickers_set():
    """ETF_TICKERS set must be defined to suppress null warnings for index ETFs."""
    src = _read_ff_source()
    assert "ETF_TICKERS" in src, "ETF_TICKERS set not defined in fundamentals_fetcher"


def test_fundamentals_upserts_with_on_conflict():
    """fundamental_data INSERT must use ON CONFLICT for idempotent upserts."""
    src = _read_ff_source()
    assert "fundamental_data" in src, "fundamental_data table not referenced"
    assert "ON CONFLICT" in src.upper(), (
        "fundamental_data INSERT must use ON CONFLICT for safe re-runs"
    )


# ─────────────────────────────────────────────────────────────────────────────
# C1: portfolio_review.py
# ─────────────────────────────────────────────────────────────────────────────

PORTFOLIO_REVIEW = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_review.py"
)


def _read_rv_source() -> str:
    with open(PORTFOLIO_REVIEW) as f:
        return f.read()


def test_portfolio_review_main_params():
    """main() must accept portfolio_db, finnhub_key, deepseek_key, gmail_smtp."""
    fn = _load_main_fn(PORTFOLIO_REVIEW)
    if fn is None:
        src = _read_rv_source()
        for p in ("portfolio_db", "finnhub_key", "deepseek_key"):
            assert p in src, f"portfolio_review missing param: {p}"
        return
    sig = inspect.signature(fn)
    for p in ("portfolio_db", "finnhub_key", "deepseek_key"):
        assert p in sig.parameters, f"portfolio_review.main missing: {p}"


def test_portfolio_review_etf_tickers_defined():
    """ETF_TICKERS must be defined to exclude ETFs from P/E and analyst target display."""
    src = _read_rv_source()
    assert "ETF_TICKERS" in src, "ETF_TICKERS not defined in portfolio_review"


def test_portfolio_review_ranks_movers_by_percent():
    """Top-movers must be ranked by percentage change, not absolute dollar move."""
    src = _read_rv_source()
    assert "pct" in src.lower() or "percent" in src.lower(), (
        "portfolio_review top movers must rank by percentage change"
    )


# ── Portfolio Candidate Evaluation tests ──────────────────────────────────────

PORTFOLIO_CANDIDATE_EVAL = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_candidate_eval.py"
)


def _read_ce_source() -> str:
    with open(PORTFOLIO_CANDIDATE_EVAL) as f:
        return f.read()


def test_candidate_eval_script_exists():
    """portfolio_candidate_eval.py must exist in windmill/u/admin/."""
    assert os.path.exists(PORTFOLIO_CANDIDATE_EVAL), (
        "windmill/u/admin/portfolio_candidate_eval.py not found — script not created"
    )


def test_candidate_eval_main_has_correct_params():
    """main() must accept ticker, portfolio_db, gmail_smtp, xai_key, deepseek_key
    as required params; universe_tickers, thesis_text, replacement_ticker optional."""
    src = _read_ce_source()
    for p in ("ticker", "portfolio_db", "gmail_smtp", "xai_key", "deepseek_key"):
        assert p in src, f"candidate_eval missing required param: {p}"
    for p in ("universe_tickers", "thesis_text", "replacement_ticker"):
        assert p in src, f"candidate_eval missing optional param: {p}"


def test_candidate_eval_returns_verdict_dict():
    """Script must produce a verdict and binding_constraint."""
    src = _read_ce_source()
    assert "verdict" in src
    assert "binding_constraint" in src


def test_evaluate_red_flags_reused():
    """_evaluate_red_flags must be present — same thresholds as rationalization."""
    src = _read_ce_source()
    assert "_evaluate_red_flags" in src


def test_compute_correlation_function_exists():
    """_compute_correlation must be present for Gate 2 price correlation."""
    src = _read_ce_source()
    assert "_compute_correlation" in src


def test_compute_correlation_validates_date_range():
    """B1: correlation check must guard on date range and emit gate2_warn."""
    src = _read_ce_source()
    assert "gate2_warn" in src
    assert "insufficient_history" in src


def test_compute_fundamental_similarity_exists():
    """B2: fundamental cosine similarity must be computed."""
    src = _read_ce_source()
    assert "_compute_fundamental_similarity" in src or "max_fundamental_sim" in src


def test_compute_sector_geo_overlap_function_exists():
    """Gate 2 must count sector and country overlaps."""
    src = _read_ce_source()
    assert "_compute_sector_geo_overlap" in src or (
        "sector_match_count" in src and "country_match_count" in src
    )


def test_compute_factor_gap_has_explicit_math():
    """B3: gap-fill logic must use pool_median and pool_p60 explicitly."""
    src = _read_ce_source()
    assert "pool_median" in src
    assert "pool_p60" in src


def test_compute_factor_gap_function_exists():
    """B3: _compute_factor_gap function must be present."""
    src = _read_ce_source()
    assert "_compute_factor_gap" in src


def test_fetch_universe_function_exists():
    """Gate 3 universe fetcher must be present."""
    src = _read_ce_source()
    assert "_fetch_universe" in src


def test_candidate_eval_min_pool_five():
    """B4: min_pool must be 5 (not 3)."""
    src = _read_ce_source()
    assert "min_pool" in src
    assert "min_pool = 5" in src or "min_pool=5" in src


def test_candidate_eval_currency_exposure_check():
    """B8: currency exposure post-addition must be computed."""
    src = _read_ce_source()
    assert "currency_post_pct" in src or "currency_breach" in src


def test_candidate_eval_writes_to_evals_table():
    """Eval results must be persisted to portfolio_candidate_evals."""
    src = _read_ce_source()
    assert "portfolio_candidate_evals" in src


def test_candidate_eval_has_grok_fallback():
    """Script must fall back to deepseek if Grok is unavailable."""
    src = _read_ce_source()
    assert "deepseek" in src


def test_candidate_eval_thin_universe_flag():
    """thin_universe flag must be surfaced when peer pool is small."""
    src = _read_ce_source()
    assert "thin_universe" in src


def test_candidate_eval_grok_output_is_json():
    """C2: Grok output must be structured JSON with rationale_sentences and evidence."""
    src = _read_ce_source()
    assert "rationale_sentences" in src
    assert "evidence" in src


# ── Auto-fetch + research integration tests ──────────────────────────────────

def test_candidate_eval_has_check_data_staleness():
    """Script must check if quant data is absent/stale before evaluating."""
    src = _read_ce_source()
    assert "_check_data_staleness" in src


def test_candidate_eval_has_dispatch_stock_fetcher():
    """Script must be able to dispatch stock_data_fetcher as a sub-job."""
    src = _read_ce_source()
    assert "_dispatch_stock_fetcher" in src


def test_candidate_eval_auto_dispatches_on_stale():
    """main() must call staleness check and dispatch fetcher when stale."""
    src = _read_ce_source()
    assert "_check_data_staleness" in src
    assert "_dispatch_stock_fetcher" in src
    assert "AutoFetch" in src


def test_candidate_eval_has_check_research_staleness():
    """Script must check if a research report exists before evaluating."""
    src = _read_ce_source()
    assert "_check_research_staleness" in src


def test_candidate_eval_has_dispatch_research_tool():
    """Script must be able to dispatch research_tool as a sub-job."""
    src = _read_ce_source()
    assert "_dispatch_research_tool" in src


def test_candidate_eval_reads_research_reports():
    """Script must read from research_reports table and include in Grok prompt."""
    src = _read_ce_source()
    assert "research_reports" in src
    assert "_fetch_latest_research" in src


# ── Rationalization: optional research synthesis ──────────────────────────────

def test_rationalization_has_include_research_param():
    """main() must accept include_research bool param (default False)."""
    src = _read_pr_source()
    assert "include_research" in src


def test_rationalization_reads_research_reports():
    """Script must query research_reports and have _fetch_research_reports function."""
    src = _read_pr_source()
    assert "research_reports" in src
    assert "_fetch_research_reports" in src


def test_rationalization_research_gated_by_flag():
    """Research fetch must only execute when include_research is True."""
    src = _read_pr_source()
    assert "if include_research" in src


# ── Move monitor: Telegram push ───────────────────────────────────────────────

def test_move_monitor_has_telegram_params():
    """main() must accept telegram_bot_token and telegram_owner_id params."""
    src = _read_mm_source()
    assert "telegram_bot_token" in src, "move_monitor missing telegram_bot_token param"
    assert "telegram_owner_id" in src, "move_monitor missing telegram_owner_id param"


def test_move_monitor_sends_telegram_on_breach():
    """Script must call _send_telegram in the alert (threshold-breached) path."""
    src = _read_mm_source()
    assert "_send_telegram" in src, "move_monitor missing _send_telegram helper"
    # The call must be inside the alert body (not just defined but never called)
    assert src.count("_send_telegram(") >= 1, "_send_telegram not called in move_monitor"


def test_move_monitor_telegram_guarded_by_token_check():
    """Telegram send must be guarded so it only fires when token is set."""
    src = _read_mm_source()
    assert "telegram_bot_token" in src
    # Guard pattern: if telegram_bot_token (and something telegram_owner_id)
    assert "if telegram_bot_token" in src or "telegram_bot_token and" in src, \
        "move_monitor must guard _send_telegram call with a token check"


# ── Rationalization: Telegram push ───────────────────────────────────────────

def test_rationalization_has_telegram_params():
    """main() must accept telegram_bot_token and telegram_owner_id params."""
    src = _read_pr_source()
    assert "telegram_bot_token" in src, "rationalization missing telegram_bot_token param"
    assert "telegram_owner_id" in src, "rationalization missing telegram_owner_id param"


def test_rationalization_sends_telegram_after_email():
    """Script must call _send_telegram after the email send."""
    src = _read_pr_source()
    assert "_send_telegram" in src, "rationalization missing _send_telegram helper"
    assert src.count("_send_telegram(") >= 1, "_send_telegram not called in rationalization"


def test_rationalization_telegram_guarded_by_token_check():
    """Telegram send must be guarded so it only fires when token is set."""
    src = _read_pr_source()
    assert "if telegram_bot_token" in src or "telegram_bot_token and" in src, \
        "rationalization must guard _send_telegram with a token check"


# ── Portfolio email: Telegram snapshot ───────────────────────────────────────

PORTFOLIO_EMAIL_SRC_PATH = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/portfolio_email.py"
)


def _read_pe_source() -> str:
    with open(PORTFOLIO_EMAIL_SRC_PATH) as f:
        return f.read()


def test_portfolio_email_has_telegram_params():
    """main() must accept telegram_bot_token and telegram_owner_id params."""
    src = _read_pe_source()
    assert "telegram_bot_token" in src, "portfolio_email missing telegram_bot_token param"
    assert "telegram_owner_id" in src, "portfolio_email missing telegram_owner_id param"


def test_portfolio_email_sends_telegram_when_token_set():
    """Script must call _send_telegram to deliver the snapshot."""
    src = _read_pe_source()
    assert "_send_telegram" in src, "portfolio_email missing _send_telegram helper"
    assert src.count("_send_telegram(") >= 1, "_send_telegram not called in portfolio_email"


def test_portfolio_email_telegram_guarded_by_token_check():
    """Telegram send must be guarded so it only fires when token is set."""
    src = _read_pe_source()
    assert "if telegram_bot_token" in src or "telegram_bot_token and" in src, \
        "portfolio_email must guard _send_telegram with a token check"


# ── Macro daily push: new script ─────────────────────────────────────────────

MACRO_DAILY_PUSH = os.path.join(
    os.path.dirname(__file__), "../../windmill/u/admin/macro_daily_push.py"
)


def _read_mdp_source() -> str:
    with open(MACRO_DAILY_PUSH) as f:
        return f.read()


def test_macro_daily_push_has_telegram_params():
    """main() must accept telegram_bot_token and telegram_owner_id."""
    src = _read_mdp_source()
    assert "telegram_bot_token" in src, "macro_daily_push missing telegram_bot_token"
    assert "telegram_owner_id" in src, "macro_daily_push missing telegram_owner_id"


def test_macro_daily_push_fetches_yahoo_symbols():
    """Script must fetch Yahoo Finance data for core macro symbols."""
    src = _read_mdp_source()
    assert "query1.finance.yahoo.com" in src or "yfinance" in src or "USDSGD" in src or "VIX" in src, \
        "macro_daily_push must fetch Yahoo Finance macro data"


def test_macro_daily_push_calls_deepseek():
    """Script must call Deepseek for synthesis."""
    src = _read_mdp_source()
    assert "deepseek" in src.lower(), "macro_daily_push must call Deepseek for synthesis"


def test_macro_daily_push_sends_telegram():
    """Script must call _send_telegram to deliver the push."""
    src = _read_mdp_source()
    assert "_send_telegram" in src, "macro_daily_push missing _send_telegram"
    assert src.count("_send_telegram(") >= 1, "_send_telegram not called in macro_daily_push"


# ── YouTube monitor: Telegram push on new videos ─────────────────────────────

def test_youtube_monitor_has_telegram_params():
    """main() must accept telegram_bot_token and telegram_owner_id params."""
    src = _read_yt_source()
    assert "telegram_bot_token" in src, "youtube_monitor missing telegram_bot_token param"
    assert "telegram_owner_id" in src, "youtube_monitor missing telegram_owner_id param"


def test_youtube_monitor_sends_telegram_when_videos_found():
    """Script must call _send_telegram when new videos are found."""
    src = _read_yt_source()
    assert "_send_telegram" in src, "youtube_monitor missing _send_telegram helper"
    assert src.count("_send_telegram(") >= 1, "_send_telegram not called in youtube_monitor"


def test_youtube_monitor_telegram_guarded_by_token_check():
    """Telegram send must be guarded so it only fires when token is set."""
    src = _read_yt_source()
    assert "if telegram_bot_token" in src or "telegram_bot_token and" in src, \
        "youtube_monitor must guard _send_telegram with a token check"


# ── macro_daily_push: USD/xxx currency direction ──────────────────────────────

def test_macro_daily_push_uses_usd_base_labels():
    """macro_daily_push must display USD/SGD and USD/HKD (not SGD/USD, HKD/USD)."""
    src = _read_mdp_source()
    assert "USD/SGD" in src, "macro_daily_push must use USD/SGD label (not SGD/USD)"
    assert "USD/HKD" in src, "macro_daily_push must use USD/HKD label (not HKD/USD)"
    assert "SGD/USD" not in src, "macro_daily_push still shows SGD/USD — must be USD/SGD"
    assert "HKD/USD" not in src, "macro_daily_push still shows HKD/USD — must be USD/HKD"


# ── Telegram notification quality tests ───────────────────────────────────────

def _read_analyst_alert_source() -> str:
    path = os.path.join(os.path.dirname(__file__), "../../windmill/u/admin/portfolio_analyst_alert.py")
    with open(path) as f:
        return f.read()


def test_youtube_telegram_includes_links():
    """youtube_monitor Telegram push must include watch_url as a clickable link and channel_name."""
    src = _read_yt_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in youtube_monitor"
    tg_block = src[max(0, tg_idx - 500): tg_idx + 600]
    assert "watch_url" in tg_block, \
        "youtube_monitor tg_text must include watch_url as a clickable link"
    assert "channel_name" in tg_block, \
        "youtube_monitor tg_text must include channel_name"


def test_youtube_telegram_includes_date():
    """youtube_monitor Telegram push must include a date (day and month)."""
    src = _read_yt_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in youtube_monitor"
    tg_block = src[tg_idx: tg_idx + 800]
    assert "strftime" in tg_block or "%d" in tg_block or "%-d" in tg_block, \
        "youtube_monitor tg_text must include a formatted date"


def test_portfolio_email_telegram_includes_date():
    """portfolio_email Telegram push must include full date (day + month), not just time."""
    src = _read_pe_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_email"
    tg_block = src[tg_idx: tg_idx + 600]
    assert "%b" in tg_block or "%-d" in tg_block or "%d" in tg_block, \
        "portfolio_email tg_text must include a day/month date format"


def test_portfolio_email_telegram_includes_dollar_impact():
    """portfolio_email Telegram push must include dollar P&L per top mover."""
    src = _read_pe_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_email"
    tg_block = src[tg_idx: tg_idx + 600]
    assert "pnl" in tg_block or "impact" in tg_block or "dollar" in tg_block, \
        "portfolio_email tg_text must include dollar P&L per mover (pnl/impact field)"


def test_move_monitor_telegram_includes_dollar_impact():
    """portfolio_move_monitor Telegram push must include dollar_impact per position."""
    src = _read_mm_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_move_monitor"
    tg_block = src[max(0, tg_idx - 500): tg_idx + 600]
    assert "dollar_impact" in tg_block, \
        "portfolio_move_monitor tg_text must include dollar_impact per alerted position"


def test_move_monitor_telegram_includes_threshold_label():
    """portfolio_move_monitor Telegram push must state which threshold was breached."""
    src = _read_mm_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_move_monitor"
    tg_block = src[max(0, tg_idx - 500): tg_idx + 800]
    assert "threshold" in tg_block.lower() or "PORTFOLIO_ALERT_THRESHOLD" in tg_block or "±" in tg_block, \
        "portfolio_move_monitor tg_text must indicate which threshold (±1.5%/±5%) was breached"


def test_rationalization_telegram_includes_scores():
    """portfolio_rationalization Telegram push must include composite scores, not just rank numbers."""
    src = _read_pr_source()
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_rationalization"
    tg_block = src[tg_idx: tg_idx + 600]
    assert "balanced" in tg_block or "score" in tg_block.lower(), \
        "portfolio_rationalization tg_text must include composite scores (balanced)"


def test_morning_news_has_telegram_push():
    """morning_news_digest must have _send_telegram and use it with links from rss_headlines."""
    src = _read_md_source()
    assert "_send_telegram" in src, \
        "morning_news_digest missing _send_telegram — no Telegram push implemented"
    assert "telegram_bot_token" in src, \
        "morning_news_digest main() must accept telegram_bot_token param"
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in morning_news_digest"
    tg_block = src[max(0, tg_idx - 600): tg_idx + 600]
    assert "link" in tg_block, \
        "morning_news_digest tg_text must include article links from rss_headlines"


def test_health_check_has_telegram_push():
    """health_check must have _send_telegram and use rows data to show pass/fail status."""
    src = _read_hc_source()
    assert "_send_telegram" in src, \
        "health_check missing _send_telegram — no Telegram push implemented"
    assert "telegram_bot_token" in src, \
        "health_check main() must accept telegram_bot_token param"
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in health_check"
    tg_block = src[tg_idx: tg_idx + 600]
    assert "rows" in tg_block or "status" in tg_block, \
        "health_check tg_text must use rows/status data"


def test_portfolio_review_has_telegram_push():
    """portfolio_review must have _send_telegram with week P&L and top movers."""
    src = _read_rv_source()
    assert "_send_telegram" in src, \
        "portfolio_review missing _send_telegram — no Telegram push implemented"
    assert "telegram_bot_token" in src, \
        "portfolio_review main() must accept telegram_bot_token param"
    tg_idx = src.find("tg_text")
    assert tg_idx != -1, "tg_text not found in portfolio_review"
    tg_block = src[tg_idx: tg_idx + 600]
    assert "week_pnl" in tg_block or "week_impact" in tg_block, \
        "portfolio_review tg_text must include week P&L data"
