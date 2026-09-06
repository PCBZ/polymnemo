# polymnemo
A shared long-term memory across any LLM, over MCP

> Early development. See the [project wiki](https://github.com/PCBZ/polymnemo/wiki)
> for the plan and the [issues](https://github.com/PCBZ/polymnemo/issues) for progress.

## Development (local)

Requires **Python 3.11+**. Uses plain `venv` + `pip` (any 3.11 interpreter works —
[pyenv](https://github.com/pyenv/pyenv), Homebrew, or python.org).

```bash
# with pyenv:  pyenv install 3.11.15  (respects .python-version)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
```

Run the MCP server (Streamable HTTP at `/mcp`):

```bash
polymnemo                          # http://127.0.0.1:8000/mcp
```

Configuration is via `POLYMNEMO_*` environment variables — see [.env.example](.env.example).

### Docker

```bash
docker build -t polymnemo .
docker run -e PORT=8080 -p 8080:8080 polymnemo   # serves /mcp on :8080
```
