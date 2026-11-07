"""Strict response schema for translation requests (docs/03 §3.2)."""

RESPONSE_SCHEMA: dict = {
    "type": "object",
    "required": ["items"],
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "text"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string", "minLength": 1},
                },
            },
        }
    },
}
