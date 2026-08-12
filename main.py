from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

# Initialize with custom config
ta = TradingAgentsGraph(debug=True, config=config)

# forward propagate (stock)
_, decision = ta.propagate("NVDA", "2024-05-10")
print(decision)

# Crypto works the same way, but pass asset_type="crypto" explicitly — unlike
# the CLI, this constructor was not built with asset-type-filtered analysts,
# so a crypto run still includes the fundamentals analyst unless you build
# `selected_analysts` yourself without "fundamentals" for that call.
# _, decision = ta.propagate("BTC-USD", "2024-05-10", asset_type="crypto")
# print(decision)

# Memorize mistakes and reflect
# ta.reflect_and_remember(1000) # parameter is the position returns
