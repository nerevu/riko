from subprocess import CalledProcessError, run


def ruff_format(code: str) -> str:
    """Format generated code with Ruff when available."""
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
