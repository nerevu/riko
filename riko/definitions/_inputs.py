# vim: sw=4:ts=4:expandtab
"""
Workflow input schemas and the references that read them.

A workflow provides each input a JSON Schema ``InputSchema`` under ``input_schemas``.
An input whose schema has no ``default`` is required, and a node's ``conf`` or ``map``
keyword refers to an input as ``{"input": name}``.

A run fills values from its context's ``inputs`` or ``InputSchema``'s ``default``. It
also checks the given values against their ``InputSchema``. It rejects missing inputs
and invalid values, and substitutes values for their references.

Examples:

    Basic usage::

        >>> from riko.ext import CompiledInputSchemas
        >>>
        >>> schemas = {"q": {"type": "string", "default": "riko"}}
        >>> dict(CompiledInputSchemas(schemas).resolve({}))
        {'q': 'riko'}

"""

from __future__ import annotations

import re
from functools import cached_property
from itertools import islice
from typing import TYPE_CHECKING

from attrs import define
from fastjsonschema import JsonSchemaDefinitionException, JsonSchemaValueException
from fastjsonschema import compile as fjs_compile

from riko.base._exceptions import InvalidPipelineError
from riko.base._funcutils import map_values
from riko.base._guards import is_known_sequence, is_mapping, require_mapping
from riko.base._iterutils import gen_nested_mappings
from riko.types._frozendict import (
    FrozenDict,
    FrozenInputs,
    FrozenInputSchema,
    JSONValue,
    json_freeze,
    normalize_mapping,
    thaw,
)
from riko.types._workflow import is_input_ref
from riko.types._wrappers import Func

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._frozendict import InputSchema, InputSchemaLike, InputSchemas
    from riko.types.modules import MaybeFrozenConf

    from ._workflow_definition import Inputs, RawValues

type CompiledSchema = Func[object]

_JSON_TYPE_NAMES: frozenset[str] = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)

_META_SCHEMA: dict[str, object] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "type": {
            "if": {"type": "string"},
            "then": {"enum": sorted(_JSON_TYPE_NAMES)},
            "else": {
                "type": "array",
                "items": {"enum": sorted(_JSON_TYPE_NAMES)},
                "minItems": 1,
                "uniqueItems": True,
            },
        },
    },
}

_META_VALIDATOR = fjs_compile(_META_SCHEMA)


def _admit_null(raw: object) -> object:
    """Widens a JSON Schema ``type`` so it also admits ``null``."""
    if isinstance(raw, str) and raw != "null":
        result: object = [raw, "null"]
    elif is_known_sequence(raw) and "null" not in raw:
        result = [*raw, "null"]
    else:
        result = raw

    return result


def compile_input_schema(name: str, schema: InputSchema) -> CompiledSchema:
    """
    Compiles an input's schema into a validator for the input's values.

    Must be a JSON Schema whose ``type``, when present, names JSON types.

    Args:

        name: The input name, used in error messages.
        schema: The input's schema.

    Returns:

        A function that raises ``JsonSchemaValueException`` for a value ``schema``
        rejects.

    Raises:

        InvalidPipelineError: If ``schema`` is not a valid JSON Schema.

    Examples:

        >>> validate = compile_input_schema("limit", {"type": "integer"})
        >>> validate(5)
        5
        >>> compile_input_schema("q", {"type": "strng"})
        Traceback (most recent call last):
        ...
        riko.exceptions.InvalidPipelineError: ...'q' has an invalid schema: ...

    """
    thawed = thaw(schema)
    what = f"workflow input {name!r} has an invalid schema"

    try:
        _META_VALIDATOR(thawed)
        validator = fjs_compile(thawed, detailed_exceptions=False)
    except JsonSchemaValueException as err:
        raise InvalidPipelineError(f"{what}: {err.message}") from err
    except (JsonSchemaDefinitionException, re.error) as err:
        raise InvalidPipelineError(f"{what}: {err}") from err

    return validator


def _validate_input(
    name: str, compiled_schema: CompiledSchema, value: JSONValue
) -> None:
    """Validates one input value with the input's compiled schema."""
    try:
        compiled_schema(thaw(value))
    except JsonSchemaValueException as err:
        msg = f"workflow input {name!r} is invalid: {err.message}"
        raise InvalidPipelineError(msg) from err


@define(frozen=True, slots=True)
class CompiledInputSchemas:
    """
    Compiles a workflow's input schemas and resolves run values against them.

    A hand-written workflow module builds one at import and resolves each call's
    ``context.inputs`` with it. Each schema compiles once rather than per call.

    Attributes:

        schemas: Each input's schema, keyed by input name.
        compiled: Each input's compiled schema, keyed by input name.

    Examples:

        >>> schemas = CompiledInputSchemas({"limit": {"type": "integer", "default": 5}})
        >>> dict(schemas.resolve(None))
        {'limit': 5}
        >>> dict(schemas.resolve({"limit": 10}))
        {'limit': 10}
        >>> schemas.resolve({"limit": "x"})
        Traceback (most recent call last):
        ...
        riko.exceptions.InvalidPipelineError: ...is invalid: data must be integer

    """

    schemas: InputSchemas

    @cached_property
    def compiled(self) -> FrozenDict[str, CompiledSchema]:
        """
        Compiles each input's schema and keys it by input name.

        Raises:

            InvalidPipelineError: If an input's schema is not a valid JSON Schema.

        """
        schemas = self.schemas.items()
        compiled = {name: compile_input_schema(name, s) for name, s in schemas}
        return FrozenDict.from_frozen(compiled)

    def validate(self) -> None:
        """
        Validates each input's schema.

        Raises:

            InvalidPipelineError: If an input's schema is not a valid JSON Schema.

        Examples:

            >>> CompiledInputSchemas({"limit": {"type": "integer"}}).validate()
            >>> CompiledInputSchemas({"q": {"type": "strng"}}).validate()
            Traceback (most recent call last):
            ...
            riko.exceptions.InvalidPipelineError: ...'q' has an invalid schema: ...

        """
        _ = self.compiled

    def resolve(self, given: RawValues | None) -> Inputs | None:
        """
        Resolves the inputs a run uses from its schemas and given values.

        A given value wins over the schema's default. A given value for an input with no
        schema passes through untouched.

        Args:

            given: Raw inputs keyed by input name, or ``None``.

        Returns:

            Inputs keyed by input name, or ``None`` when there are either no input
            schemas or no given values.

        Raises:

            InvalidPipelineError: If an input has neither a given value nor a default,
                a value does not match its input's schema, or an input's schema is
                malformed.

        """
        if given is None and not self.schemas:
            result = None
        else:
            schemas = self.schemas.items()
            defaults = {k: s["default"] for k, s in schemas if "default" in s}
            inputs = {**defaults, **normalize_mapping(given)}

            if missing := set(self.schemas).difference(inputs):
                msg = f"missing required workflow input(s): {sorted(missing)}"
                raise InvalidPipelineError(msg)

            for name, compiled_schema in self.compiled.items():
                _validate_input(name, compiled_schema, inputs[name])

            result = inputs

        return result


def normalize_input_schema(
    raw: InputSchemaLike, what: str = "input"
) -> FrozenInputSchema:
    """
    Normalizes an input's schema into a frozen JSON Schema.

    A bare JSON type name stands for a schema of that type. A ``None`` default widens
    the schema's ``type`` to include ``null``. ``Workflow.validate_input_schemas``
    checks the result.

    Args:

        raw: A JSON type name or a JSON Schema.

    Kwargs:

        what: The name used in error messages.

    Returns:

        The frozen JSON Schema.

    Raises:

        InvalidPipelineError: If ``raw`` is neither a string nor a mapping, or holds
            a value that is not JSON-native.

    Examples:

        >>> dict(normalize_input_schema("integer"))
        {'type': 'integer'}
        >>> dict(normalize_input_schema({"type": "string", "default": None}))
        {'type': ('string', 'null'), 'default': None}

    """
    if isinstance(raw, str):
        schema: dict[str, object] = {"type": raw}
    elif is_mapping(raw):
        schema = dict(raw)
    else:
        raise InvalidPipelineError(f"{what} must be a type name or mapping")

    if "type" in schema and "default" in schema and schema["default"] is None:
        schema["type"] = _admit_null(schema["type"])

    return json_freeze(schema)


def freeze_inputs(value: Inputs | None) -> FrozenInputs | None:
    """
    Freezes the inputs a ``Context`` carries.

    Args:

        value: The inputs keyed by input name, or ``None`` when none are given.

    Returns:

        The frozen inputs, or ``None`` when none are given.

    Raises:

        TypeError: If ``value`` is not a mapping.
        InvalidPipelineError: If a value is not JSON-native.

    Examples:

        >>> freeze_inputs({"tags": ["a", "b"]})
        FrozenDict({'tags': ('a', 'b')})

    """
    if (result := value) is not None:
        what = "Context 'inputs'"
        result = json_freeze(require_mapping(value, what, error=TypeError))

    return result


def gen_input_references(value: MaybeFrozenConf) -> Iterator[str]:
    """
    Collects the input names a configuration refers to.

    A reference is an ``{"input": name}`` mapping nested anywhere inside ``value``.

    Args:

        value: A node configuration or keyword arguments.

    Yields:

        Each referenced input name.

    Examples:

        >>> conf = json_freeze({"url": {"input": "feed"}, "rule": [{"input": "q"}]})
        >>> list(gen_input_references(conf))
        ['feed', 'q']

    """
    for mapping in islice(gen_nested_mappings(value), 1, None):
        if is_input_ref(mapping):
            yield mapping["input"]


def _get_reference_name(value: object) -> str | None:
    """Gets the input name ``value`` refers to, or ``None`` if it is no reference."""
    return value["input"] if is_input_ref(value) else None


def resolve_input_references(value: JSONValue, inputs: Inputs) -> JSONValue:
    """
    Resolves every input reference inside a configuration to its input value.

    Args:

        value: A node configuration or keyword arguments.
        inputs: The resolved inputs keyed by input name.

    Returns:

        A copy of ``value`` with each ``{"input": name}`` mapping replaced by
        ``inputs[name]``. A list stays a list and a tuple stays a tuple.

    Examples:

        >>> conf = {"url": {"input": "feed"}, "limit": 2}
        >>> dict(resolve_input_references(conf, {"feed": "news.xml"}))
        {'url': 'news.xml', 'limit': 2}
        >>> rules = {"rules": [{"input": "q"}, {"field": "title"}]}
        >>> dict(resolve_input_references(rules, {"q": 5}))
        {'rules': [5, {'field': 'title'}]}
        >>> resolve_input_references(({"input": "q"}, 1), {"q": 5})
        (5, 1)

    """

    def substitute(val: JSONValue) -> JSONValue:
        if (name := _get_reference_name(val)) is None:
            result = resolve_input_references(val, inputs)
        else:
            result = inputs[name]

        return result

    if is_mapping(value):
        result = map_values(substitute, value)
    elif isinstance(value, list):
        result = list(map(substitute, value))
    elif isinstance(value, tuple):
        result = tuple(map(substitute, value))
    else:
        result = value

    return result


__all__ = [
    "CompiledInputSchemas",
    "compile_input_schema",
    "freeze_inputs",
    "gen_input_references",
    "normalize_input_schema",
    "resolve_input_references",
]
