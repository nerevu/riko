"""Best-effort source formatting for generated Python code."""

from subprocess import CalledProcessError, run


def ruff_format(code: str) -> str:
    """
    Formats generated Python source with Ruff when available.

    Args:

        code: Python source to format.

    Returns:

        Ruff's formatted source, or the original source when Ruff is unavailable
        or formatting fails.

    Examples:

        >>> ruff_format("x = 1\\n")
        'x = 1\\n'

    """
    try:
        result = run(
            ["ruff", "format", "-"],  # noqa: S607
            input=code,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, CalledProcessError):
        formatted = code
    else:
        formatted = result.stdout or code

    return formatted
