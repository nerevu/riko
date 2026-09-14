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
