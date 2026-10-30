"""Convert Pydantic models to the JSON Schema sent as `response_format`.

Documented constraints (docs/META_API_FACTS.md): recursive $ref is rejected;
additionalProperties:false + required + enum are supported. Numeric/length keywords are
not documented, so they are stripped from the wire schema and enforced locally by Pydantic.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

_DROP = {"title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
         "minLength", "maxLength", "minItems", "maxItems", "pattern", "format"}


def wire_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def resolve(node: Any, stack: tuple[str, ...]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                if name in stack:
                    raise ValueError(f"recursive schema via {name} is not supported by the API")
                return resolve(copy.deepcopy(defs[name]), stack + (name,))
            out = {k: resolve(v, stack) for k, v in node.items() if k not in _DROP}
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [resolve(x, stack) for x in node]
        return node

    return resolve(raw, ())
