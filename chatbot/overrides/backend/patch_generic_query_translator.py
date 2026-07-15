"""
Build-time patch for upstream generic_query_translator.py.

Applied by Dockerfile.chatbot-backend after the upstream source is copied.
Keep each patch as a simple str.replace so drift is caught at build time
(a failed replace leaves the file unchanged and the unit test will catch it).
"""

from pathlib import Path

f = Path(__file__).parent / "generic_query_translator.py"
src = f.read_text()
original = src

# ---------------------------------------------------------------------------
# 1. Add response_format parameter to _llm_text
#    Lets callers enable Ollama's JSON-enforcement mode without touching the
#    call site in every agent.
# ---------------------------------------------------------------------------
src = src.replace(
    "async def _llm_text(\n"
    "    client: LLMClient,\n"
    "    messages: List[Dict],\n"
    "    max_tokens: int = 512,\n"
    "    temperature: float = 0.2,\n"
    ") -> str:\n"
    '    """Call *client* (LLMClient) and return the assistant text."""\n'
    "    try:\n"
    "        response = await client.chat(\n"
    "            messages, max_tokens=max_tokens, temperature=temperature\n"
    "        )",
    "async def _llm_text(\n"
    "    client: LLMClient,\n"
    "    messages: List[Dict],\n"
    "    max_tokens: int = 512,\n"
    "    temperature: float = 0.2,\n"
    "    response_format: Optional[Dict[str, Any]] = None,\n"
    ") -> str:\n"
    '    """Call *client* (LLMClient) and return the assistant text."""\n'
    "    try:\n"
    '        _chat_kw: Dict[str, Any] = {"max_tokens": max_tokens, "temperature": temperature}\n'
    "        if response_format is not None:\n"
    '            _chat_kw["response_format"] = response_format\n'
    "        response = await client.chat(messages, **_chat_kw)",
)

# ---------------------------------------------------------------------------
# 2. Add Quebec / Canada entries to _KNOWN_BBOXES
#    The upstream dict only has European cities; the keyword fallback never
#    resolves Quebec locations without these entries.
# ---------------------------------------------------------------------------
src = src.replace(
    '    "sahara": [-17.00, 15.00, 37.00, 35.00],\n}',
    '    "sahara": [-17.00, 15.00, 37.00, 35.00],\n'
    '    "canada": [-141.00, 41.68, -52.63, 83.11],\n'
    '    "montreal": [-73.97, 45.41, -73.47, 45.71],\n'
    '    "québec": [-71.42, 46.76, -71.17, 46.89],\n'
    '    "quebec city": [-71.42, 46.76, -71.17, 46.89],\n'
    '    "sherbrooke": [-71.97, 45.33, -71.81, 45.42],\n'
    '    "laval": [-73.82, 45.53, -73.62, 45.62],\n'
    '    "longueuil": [-73.55, 45.47, -73.43, 45.59],\n'
    '    "gatineau": [-75.92, 45.37, -75.68, 45.49],\n'
    '    "ontario": [-95.16, 41.67, -74.32, 56.85],\n'
    '    "toronto": [-79.64, 43.58, -79.12, 43.86],\n'
    "}",
)

# ---------------------------------------------------------------------------
# 3. Enable Ollama JSON mode in build_stac_query_agent and anchor bbox with
#    _KNOWN_BBOXES when the LLM returns an inaccurate location.
#    llama3.2 ignores "Return ONLY valid JSON" without API-level enforcement,
#    and its coordinate knowledge is unreliable for Quebec cities.
# ---------------------------------------------------------------------------
src = src.replace(
    "            raw = await _llm_text(\n"
    "                self._llm,\n"
    '                [{"role": "user", "content": prompt}],\n'
    "                max_tokens=256,\n"
    "                temperature=0.0,\n"
    "            )\n"
    "            result = _parse_json(raw)\n"
    "            if isinstance(result, dict):\n"
    "                return result\n"
    "        except Exception as exc:\n"
    '            logger.error(f"[GQT] build_stac_query_agent failed: {exc}")',
    "            raw = await _llm_text(\n"
    "                self._llm,\n"
    '                [{"role": "user", "content": prompt}],\n'
    "                max_tokens=256,\n"
    "                temperature=0.0,\n"
    '                response_format={"type": "json_object"},\n'
    "            )\n"
    "            result = _parse_json(raw)\n"
    "            if isinstance(result, dict):\n"
    "                _loc = (result.get('location_name') or '').lower()\n"
    "                if _loc and _loc in _KNOWN_BBOXES:\n"
    "                    result['bbox'] = _KNOWN_BBOXES[_loc]\n"
    "                return result\n"
    "        except Exception as exc:\n"
    '            logger.error(f"[GQT] build_stac_query_agent failed: {exc}")',
)

if src == original:
    raise RuntimeError(
        "patch_generic_query_translator.py: no changes applied — "
        "upstream source has drifted, update the patches."
    )

f.write_text(src)
print(f"generic_query_translator.py patched OK ({f})")
