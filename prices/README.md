# Price tables

One file per month, `YYYY-MM.json`, frozen once published. Cost per decision is computed from a
trace with the table in force on the run date:

```json
{
  "per_tool_call_usd": 0.001,
  "models": {
    "<model id>": {"input_per_mtok_usd": 0.0, "output_per_mtok_usd": 0.0},
    "<decision model id>": {"per_call_usd": 0.0}
  }
}
```

Prices are list prices from each provider's public pricing page on the first of the month.
Decision-model prices are the price the vendor declares in `metadata.yaml`.
