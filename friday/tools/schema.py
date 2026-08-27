from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    """Raised when a value does not match a JSON Schema subset."""


def validate_schema(schema: dict[str, Any], instance: Any, path: str = "$") -> Any:
    """Validate a small JSON Schema subset: object, string, boolean, integer, enum.

    Unknown schema keywords are ignored. This is enough to gate tool arguments
    without adding a jsonschema dependency.
    """
    expected = schema.get("type")

    if expected == "object":
        if not isinstance(instance, dict):
            raise SchemaError(f"{path} must be an object")

        required = schema.get("required") or []
        for key in required:
            if key not in instance:
                raise SchemaError(f"{path}.{key} is required")

        properties: dict[str, Any] = schema.get("properties") or {}
        allow_additional = schema.get("additionalProperties", True)
        normalized: dict[str, Any] = {}

        for key, value in instance.items():
            if key in properties:
                normalized[key] = validate_schema(properties[key], value, f"{path}.{key}")
            elif allow_additional is False:
                raise SchemaError(f"{path}.{key} is not allowed")
            else:
                normalized[key] = value

        return normalized

    if expected == "string":
        if not isinstance(instance, str):
            raise SchemaError(f"{path} must be a string")
        min_length = schema.get("minLength")
        if min_length is not None and len(instance) < int(min_length):
            raise SchemaError(f"{path} must be at least {min_length} characters")
        _check_enum(schema, instance, path)
        return instance

    if expected == "boolean":
        if not isinstance(instance, bool):
            raise SchemaError(f"{path} must be a boolean")
        return instance

    if expected == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            raise SchemaError(f"{path} must be an integer")
        _check_enum(schema, instance, path)
        return instance

    _check_enum(schema, instance, path)
    return instance


def _check_enum(schema: dict[str, Any], instance: Any, path: str) -> None:
    allowed = schema.get("enum")
    if allowed is not None and instance not in allowed:
        raise SchemaError(f"{path} must be one of {list(allowed)}")
