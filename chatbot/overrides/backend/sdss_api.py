"""
SDSS standalone router — handles spatial process queries via OGC API - Processes.

Bypasses upstream router_agent.py which misclassifies intent queries like
"What processes are available?" as location names via its bare-location heuristic.
"""

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import APIKeyHeader
from openai import AsyncOpenAI
from pydantic import BaseModel
from tools_registry import (
    execute_pygeoapi_process,
    get_process_schema,
    list_pygeoapi_processes,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def _verify_api_key(x_api_key: str | None = Depends(_api_key_header)) -> None:
    if os.environ.get("ENABLE_AUTH", "false").lower() != "true":
        return
    expected = os.environ.get("API_KEY", "")
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


_TOOL_DEFS = [
    {
        "type": "function",
        "function": {
            "name": "list_pygeoapi_processes",
            "description": list_pygeoapi_processes.__doc__,
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_process_schema",
            "description": get_process_schema.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "The OGC process ID to retrieve the schema for.",
                    }
                },
                "required": ["process_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_pygeoapi_process",
            "description": execute_pygeoapi_process.__doc__,
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {
                        "type": "string",
                        "description": "The OGC process ID to execute.",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Input parameters as required by the process schema.",
                    },
                },
                "required": ["process_id", "inputs"],
            },
        },
    },
]

_TOOL_FNS: dict = {
    "list_pygeoapi_processes": list_pygeoapi_processes,
    "get_process_schema": get_process_schema,
    "execute_pygeoapi_process": execute_pygeoapi_process,
}

_SYSTEM_PROMPT_TEMPLATE = (
    "You are MOS Assistant, a spatial decision support system for Quebec agricultural research.\n"
    "KNOWLEDGE BASE — spatial analyses you can run:\n"
    "{process_catalog}\n\n"
    "Rules:\n"
    "1. Answer questions about what analyses are available directly from the knowledge base above.\n"
    "2. Only call execute_pygeoapi_process when the user explicitly asks to run or execute something.\n"
    '3. Use the exact process_id string shown above (e.g. "hello-world-pygeoapi").\n'
    "4. Respond in the same language the user used."
)


async def _build_process_catalog() -> str:
    """Fetch all process IDs + their input schemas and return a compact text block."""
    try:
        processes = await list_pygeoapi_processes()
    except Exception as exc:
        logger.warning("Could not fetch process list: %s", exc)
        return "(process catalog unavailable)"

    lines: list[str] = []
    for p in processes:
        pid = p["id"]
        lines.append(f'\nProcess "{pid}" — {p.get("title", "")}')
        lines.append(f'  Description: {p.get("description", "")}')
        try:
            schema = await get_process_schema(pid)
            inputs = schema.get("inputs", {})
            if inputs:
                lines.append("  Inputs:")
                for name, spec in inputs.items():
                    typ = spec.get("schema", {}).get("type", "any")
                    desc = spec.get("description", "")
                    required = spec.get("minOccurs", 0) > 0
                    req_flag = " [required]" if required else " [optional]"
                    lines.append(f"    - {name} ({typ}){req_flag}: {desc}")
        except Exception as exc:
            logger.warning("Could not fetch schema for %s: %s", pid, exc)
    return "\n".join(lines)


class _QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    conversation_history: list[dict] | None = None


class _QueryResponse(BaseModel):
    response: str
    action: str | None = None


@router.post(
    "/query", response_model=_QueryResponse, dependencies=[Depends(_verify_api_key)]
)
async def sdss_query(req: _QueryRequest) -> _QueryResponse:
    """Agentic tool-calling loop for spatial process discovery and execution."""
    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="LLM_API_KEY is not configured.")

    # Pre-fetch catalog + schemas so the LLM only needs to call execute_pygeoapi_process.
    catalog = await _build_process_catalog()
    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(process_catalog=catalog)

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
    )
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    max_tokens = int(os.environ.get("LLM_MAX_TOKENS", "1000"))

    messages: list = [{"role": "system", "content": system_prompt}]
    if req.conversation_history:
        messages.extend(req.conversation_history[-6:])
    messages.append({"role": "user", "content": req.query})

    for _ in range(6):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,  # type: ignore[arg-type]
            tools=_TOOL_DEFS,  # type: ignore[arg-type]
            tool_choice="auto",
            max_tokens=max_tokens,
        )
        msg = resp.choices[0].message
        messages.append(msg)  # type: ignore[arg-type]

        # --- Handle proper tool_calls (OpenAI-compatible models) ---
        if msg.tool_calls:
            tool_calls = msg.tool_calls
        else:
            # Llama-family via Ollama sometimes returns the tool call as JSON text
            # content instead of using the tool_calls field.
            tool_calls = _extract_text_tool_call(msg.content or "")

        if not tool_calls:
            return _QueryResponse(response=msg.content or "")

        for tc in tool_calls:
            if isinstance(tc, dict):
                fn_name = tc["name"]
                raw_args = tc.get("parameters") or tc.get("arguments") or {}
                tool_call_id = "text-tool-0"
            else:
                fn_name = tc.function.name
                raw_args = json.loads(tc.function.arguments)
                tool_call_id = tc.id

            fn = _TOOL_FNS.get(fn_name)
            if fn is None:
                result: object = {"error": f"Unknown tool: {fn_name}"}
            else:
                try:
                    args = (
                        raw_args if isinstance(raw_args, dict) else json.loads(raw_args)
                    )
                    # Llama-family models sometimes wrap scalar args in a list
                    if isinstance(args.get("process_id"), list):
                        args["process_id"] = args["process_id"][0]
                    logger.info("Tool %s called with args: %s", fn_name, args)
                    result = await fn(**args)
                except Exception as exc:
                    logger.warning(
                        "Tool %s failed with args %s: %s", fn_name, raw_args, exc
                    )
                    result = {"error": str(exc)}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": json.dumps(result),
                }
            )

    return _QueryResponse(response="I was unable to complete the spatial analysis.")


def _extract_text_tool_call(content: str) -> list[dict] | None:
    """Parse a tool call that Llama/Ollama returned as JSON text content."""
    content = content.strip()
    if not content.startswith("{"):
        return None
    try:
        parsed = json.loads(content)
        name = parsed.get("name") or parsed.get("function")
        params = parsed.get("parameters") or parsed.get("arguments") or {}
        if name and name in _TOOL_FNS:
            return [{"name": name, "parameters": params}]
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return None
