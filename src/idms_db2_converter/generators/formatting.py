def comma_block(
    items: list[str],
    first_prefix: str = "",
    next_prefix: str = "",
) -> list[str]:
    """
    Format a list of SQL items as comma-separated lines.

    Example:
        comma_block(
            items=["EMP_ID", "EMP_NAME", "DEPT_ID"],
            first_prefix="SELECT ",
            next_prefix="       "
        )

    Returns:
        [
            "SELECT EMP_ID,",
            "       EMP_NAME,",
            "       DEPT_ID"
        ]
    """

    if not items:
        return []

    lines: list[str] = []

    for index, item in enumerate(items):
        prefix = first_prefix if index == 0 else next_prefix

        suffix = "," if index < len(items) - 1 else ""

        lines.append(
            f"{prefix}{item}{suffix}"
        )

    return lines