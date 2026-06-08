---
name: web_researcher
description: "Search the web using SearXNG and crawl/extract page contents using Crawl4AI."
version: 1.0.0
category: research
---

# Web Researcher Skill

## Goal
Enable the agent to search the web for current information and crawl specific web pages to retrieve detailed content or documentation.

## Description
This skill acts as the agent's window to the internet. It provides two main capabilities:
1. **Search**: Query the web using a SearXNG meta-search engine instance.
2. **Crawl**: Retrieve, clean, and convert target web pages into clean markdown formats using a Crawl4AI service.

Both tools are routed through a secure API Gateway proxy to handle headers, token injection, and routing.

## Usage
Execute the skill scripts using the `execute_skill_script()` tool.

### 1. Web Search
To search the web, call:
```json
execute_skill_script({
  "skill_name": "web_researcher",
  "script_path": "scripts/search.py",
  "args": "--query 'current ROS 2 humble release status' --num_results 3"
})
```

### 2. Web Crawl
To crawl and extract a specific web page's content, call:
```json
execute_skill_script({
  "skill_name": "web_researcher",
  "script_path": "scripts/crawl.py",
  "args": "--url 'https://bob-ros2.github.io/bob_handbuch/index.html' --priority 1"
})
```

## Parameters

### `scripts/search.py`
| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--query` / `-q` | string | (Required) | The search query string. |
| `--num_results` / `-n` | integer | `3` | Maximum number of search results to return. |

### `scripts/crawl.py`
| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--url` / `-u` | string | (Required) | The target URL to crawl. |
| `--priority` / `-p` | integer | `1` | Job priority. |

## Requirements
- **API Gateway**: Must be running and exposed (normally on port `9080` of the host).
- **SearXNG Service**: Configured and accessible by the Gateway (via `SEARXNG_URL`).
- **Crawl4AI Service**: Configured and accessible by the Gateway (via `CRAWL4AI_BASE_URL` / `CRAWL4AI_API_KEY`).

## Technical Details
- **Environment Variables**:
  - `MASTER_SEARXNG_URL`: Gateway route for search (defaults to `http://api-gateway:8080/search`).
  - `SEARXNG_URL`: Direct SearXNG back-end URL.
  - `MASTER_CRAWL4AI_URL`: Gateway route for crawling (defaults to `http://api-gateway:8080/crawl`).
  - `CRAWL4AI_BASE_URL`: Direct Crawl4AI back-end URL (e.g. `http://192.168.1.10:3020`).
  - `CRAWL4AI_API_KEY`: Authentication Bearer token for Crawl4AI.
- **Data Flow**:
  - Search requests query SearXNG and return titles, descriptions, and URLs in JSON format.
  - Crawl requests are sent to Crawl4AI, which launches a headless browser to extract clean, LLM-friendly markdown content from the target URL.

## Best Practices
- **Combine Search & Crawl**: First search using `search.py` to identify relevant links, then use `crawl.py` on the target URL to extract detailed knowledge.
- **Specific URLs**: When crawling, ensure the URL is fully specified and begins with `http://` or `https://` (the script will prepend `http://` if missing).
