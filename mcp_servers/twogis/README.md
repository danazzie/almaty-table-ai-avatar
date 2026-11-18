# 2GIS MCP server

Scrapes [2gis.kz](https://2gis.kz) restaurant search with Playwright (network intercept of catalog API + DOM fallback).

## Tools

`search_restaurants(query: str, location: str = "Алматы")` → list of restaurants:

- name, address, rating, price_range, cuisine, working_hours, phone

## Run (stdio)

From project root, after `playwright install chromium`:

```bash
python mcp_servers/twogis/server.py
```

The Gradio app starts this process automatically via MCP stdio. Results are cached for 10 minutes to avoid blocks; if 2gis.kz is unreachable or shows a captcha, the last cached results are served instead.
