"""Helpers to build JSON Schemas compatible with OpenAI Structured Outputs (strict mode):
every object lists all properties as required and forbids additional properties;
optional values are expressed as nullable types."""
from __future__ import annotations

from typing import Any


def obj(properties: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }
    if description:
        schema["description"] = description
    return schema


def arr(items: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "array", "items": items}
    if description:
        schema["description"] = description
    return schema


def string(description: str | None = None, *, nullable: bool = False, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": ["string", "null"] if nullable else "string"}
    if enum:
        schema["enum"] = enum + ([None] if nullable else [])
    if description:
        schema["description"] = description
    return schema


def number(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "number"}
    if description:
        schema["description"] = description
    return schema


def integer(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer"}
    if description:
        schema["description"] = description
    return schema


def boolean(description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "boolean"}
    if description:
        schema["description"] = description
    return schema
