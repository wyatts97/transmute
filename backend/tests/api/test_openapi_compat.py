"""Guard against breaking changes to the public API.

``tests/fixtures/openapi_upstream.json`` is the OpenAPI spec of upstream
Transmute at the point this fork started. Every existing route, method,
parameter, request field and response field must keep working:

- no route, method, parameter, or success status code may disappear;
- requests may gain optional fields, never new required ones;
- responses may gain fields, never lose or stop guaranteeing them;
- an existing field keeps its type.

Additive changes (new routes, new optional fields) are fine.
"""
from __future__ import annotations

import json
from pathlib import Path

from main import create_app


BASELINE_PATH = Path(__file__).parent.parent / "fixtures" / "openapi_upstream.json"


class _Spec:
    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.components = spec.get("components", {}).get("schemas", {})

    def resolve(self, schema: dict) -> tuple[str | None, dict]:
        ref = schema.get("$ref")
        if ref:
            name = ref.rsplit("/", 1)[-1]
            return name, self.components.get(name, {})
        return None, schema

    def signature(self, schema: dict) -> str:
        name, resolved = self.resolve(schema)
        if name:
            return f"ref:{name}"
        if "anyOf" in resolved:
            return "anyOf(" + ",".join(sorted(self.signature(s) for s in resolved["anyOf"])) + ")"
        if resolved.get("type") == "array":
            return f"array[{self.signature(resolved.get('items', {}))}]"
        if "enum" in resolved:
            return f"{resolved.get('type', 'any')}:enum"
        return resolved.get("type", "any")


def _request_schema(operation: dict) -> dict | None:
    content = operation.get("requestBody", {}).get("content", {})
    for media in content.values():
        return media.get("schema")
    return None


def _response_schema(response: dict) -> dict | None:
    for media in response.get("content", {}).values():
        if "schema" in media:
            return media["schema"]
    return None


def _compare_objects(base: _Spec, cur: _Spec, b_schema: dict, c_schema: dict, *, where: str,
                     direction: str, problems: list[str], seen: set) -> None:
    b_name, b_obj = base.resolve(b_schema)
    c_name, c_obj = cur.resolve(c_schema)
    key = (b_name, c_name, direction)
    if key in seen:
        return
    seen.add(key)

    b_props = b_obj.get("properties", {})
    c_props = c_obj.get("properties", {})
    b_required = set(b_obj.get("required", []))
    c_required = set(c_obj.get("required", []))

    for prop, b_prop in b_props.items():
        if prop not in c_props:
            problems.append(f"{where}: field '{prop}' was removed")
            continue
        b_sig, c_sig = base.signature(b_prop), cur.signature(c_props[prop])
        if b_sig != c_sig:
            problems.append(f"{where}: field '{prop}' changed type {b_sig} -> {c_sig}")
        elif b_sig.startswith("ref:") or b_sig.startswith("array[ref:"):
            inner_b = b_prop.get("items", b_prop)
            inner_c = c_props[prop].get("items", c_props[prop])
            _compare_objects(base, cur, inner_b, inner_c, where=f"{where}.{prop}",
                             direction=direction, problems=problems, seen=seen)

    if direction == "request":
        for prop in sorted(c_required - b_required):
            problems.append(f"{where}: field '{prop}' became required")
    else:
        for prop in sorted(b_required - c_required):
            problems.append(f"{where}: response field '{prop}' is no longer guaranteed")


def find_breaking_changes(baseline: dict, current: dict) -> list[str]:
    base, cur = _Spec(baseline), _Spec(current)
    problems: list[str] = []
    for path, methods in baseline.get("paths", {}).items():
        cur_methods = current.get("paths", {}).get(path)
        if cur_methods is None:
            problems.append(f"{path}: route was removed")
            continue
        for method, b_op in methods.items():
            c_op = cur_methods.get(method)
            where = f"{method.upper()} {path}"
            if c_op is None:
                problems.append(f"{where}: method was removed")
                continue

            b_params = {(p["name"], p["in"]): p for p in b_op.get("parameters", [])}
            c_params = {(p["name"], p["in"]): p for p in c_op.get("parameters", [])}
            for key, b_param in b_params.items():
                if key not in c_params:
                    problems.append(f"{where}: parameter {key[0]} ({key[1]}) was removed")
                elif c_params[key].get("required") and not b_param.get("required"):
                    problems.append(f"{where}: parameter {key[0]} became required")
            for key, c_param in c_params.items():
                if key not in b_params and c_param.get("required"):
                    problems.append(f"{where}: new required parameter {key[0]}")

            b_body, c_body = _request_schema(b_op), _request_schema(c_op)
            if b_body is not None:
                if c_body is None:
                    problems.append(f"{where}: request body was removed")
                else:
                    _compare_objects(base, cur, b_body, c_body, where=f"{where} body",
                                     direction="request", problems=problems, seen=set())
            elif c_op.get("requestBody", {}).get("required"):
                problems.append(f"{where}: now requires a request body")

            for code, b_resp in b_op.get("responses", {}).items():
                c_resp = c_op.get("responses", {}).get(code)
                if c_resp is None:
                    if code.startswith("2"):
                        problems.append(f"{where}: success response {code} was removed")
                    continue
                b_schema, c_schema = _response_schema(b_resp), _response_schema(c_resp)
                if b_schema is not None and c_schema is not None:
                    _compare_objects(base, cur, b_schema, c_schema, where=f"{where} -> {code}",
                                     direction="response", problems=problems, seen=set())
    return problems


def test_api_has_no_breaking_changes_against_upstream():
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = create_app().openapi()
    problems = find_breaking_changes(baseline, current)
    assert not problems, "Breaking API changes:\n" + "\n".join(problems)


def test_checker_flags_breaking_changes():
    """The checker itself must catch the changes it exists to prevent."""
    baseline = {
        "paths": {
            "/api/things": {
                "post": {
                    "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Req"}}}},
                    "responses": {"200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Resp"}}}}},
                },
            },
            "/api/gone": {"get": {"responses": {"200": {}}}},
        },
        "components": {"schemas": {
            "Req": {"properties": {"id": {"type": "string"}}, "required": ["id"]},
            "Resp": {"properties": {"id": {"type": "string"}, "size": {"type": "integer"}}, "required": ["id", "size"]},
        }},
    }
    current = json.loads(json.dumps(baseline))
    del current["paths"]["/api/gone"]
    current["components"]["schemas"]["Req"]["properties"]["mode"] = {"type": "string"}
    current["components"]["schemas"]["Req"]["required"].append("mode")
    current["components"]["schemas"]["Resp"]["properties"]["size"] = {"type": "string"}
    current["components"]["schemas"]["Resp"]["required"] = ["id"]

    problems = find_breaking_changes(baseline, current)
    assert any("/api/gone: route was removed" in p for p in problems)
    assert any("field 'mode' became required" in p for p in problems)
    assert any("field 'size' changed type integer -> string" in p for p in problems)
    assert any("'size' is no longer guaranteed" in p for p in problems)

    additive = json.loads(json.dumps(baseline))
    additive["components"]["schemas"]["Req"]["properties"]["options"] = {"type": "object"}
    additive["components"]["schemas"]["Resp"]["properties"]["encoder_used"] = {"type": "string"}
    additive["paths"]["/api/new"] = {"get": {"responses": {"200": {}}}}
    assert find_breaking_changes(baseline, additive) == []
