# Chocolife MCP server

Scrapes [Chocolife restaurant deals](https://chocolife.me/restorany-kafe-i-bary/) with Playwright.

## Tools

`search_deals(category: str = "рестораны", city: str = "Алматы")` → list of deals:

- title, restaurant_name, original_price, discount_price, discount_percent, description, url

## Run (stdio)

```bash
python mcp_servers/chocolife/server.py
```

The Gradio app starts this process automatically via MCP stdio. Results are cached for 10 minutes; if chocolife.me is unreachable, the last cached results are served instead.
