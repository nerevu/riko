from riko.types._guards import is_mapping


def invert_dict[K, V](d: dict[K, V]) -> dict[V, K]:
    """
    Swaps a dict's keys and values.

    Args:

        d: The dict to invert; its values must be hashable and unique.

    Returns:

        A new dict mapping each value back to its key.

    Examples:

        >>> invert_dict({"a": 1, "b": 2})
        {1: 'a', 2: 'b'}

    """
    return {v: k for k, v in d.items()}


def validate_dict(item: object) -> dict:
    if not is_mapping(item):
        raise TypeError(f"Expected a mapping, got {type(item).__name__}")

    return dict(item)
