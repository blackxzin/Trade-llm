"""Guard the news analyst prompt against tool-signature drift (#1116).

The prompt used to advertise ``get_news(query, ...)`` while the tool takes a
``ticker``, tricking the LLM into hallucinating free-text query calls.
"""
import inspect
from unittest.mock import MagicMock

import pytest

import tradingagents.agents.analysts.news_analyst as na
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.utils.news_data_tools import get_crypto_news, get_news


@pytest.mark.unit
def test_get_news_takes_ticker_not_query():
    arg_names = set(get_news.args.keys())
    assert "ticker" in arg_names
    assert "query" not in arg_names


@pytest.mark.unit
def test_news_prompt_matches_get_news_signature():
    src = inspect.getsource(na)
    assert "get_news(ticker, start_date, end_date)" in src
    assert "get_news(query" not in src


def _bound_tools(state):
    """Run the news analyst node with a mock LLM and return the tool list
    it bound, without making a real LLM or network call."""
    bind_tools = MagicMock()
    bind_tools.return_value.invoke.return_value = MagicMock(tool_calls=[], content="")
    llm = MagicMock()
    llm.bind_tools = bind_tools
    create_news_analyst(llm)(state)
    return bind_tools.call_args[0][0]


@pytest.mark.unit
def test_crypto_run_binds_crypto_news_tool():
    state = {
        "trade_date": "2026-06-15", "asset_type": "crypto",
        "company_of_interest": "BTC-USD", "messages": [],
    }
    tools = _bound_tools(state)
    assert get_crypto_news in tools


@pytest.mark.unit
def test_stock_run_omits_crypto_news_tool():
    state = {
        "trade_date": "2026-06-15", "asset_type": "stock",
        "company_of_interest": "NVDA", "messages": [],
    }
    tools = _bound_tools(state)
    assert get_crypto_news not in tools
