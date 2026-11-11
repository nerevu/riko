from collections.abc import Callable, Mapping

class JsonSchemaException(ValueError): ...  # noqa: N818

class JsonSchemaValueException(JsonSchemaException):
    message: str

    def __init__(
        self,
        message: str,
        value: object = None,
        name: str | None = None,
        definition: object = None,
        rule: str | None = None,
    ) -> None: ...

class JsonSchemaDefinitionException(JsonSchemaException): ...

def compile(
    definition: Mapping[str, object] | bool,
    handlers: Mapping[str, Callable[[str], object]] = ...,
    formats: Mapping[str, str | Callable[[object], bool]] = ...,
    use_default: bool = True,
    use_formats: bool = True,
    detailed_exceptions: bool = True,
    fast_fail: bool = True,
) -> Callable[[object], object]: ...
