from pathlib import Path


def ensure_directory(
    directory: str
) -> None:

    Path(
        directory
    ).mkdir(
        parents=True,
        exist_ok=True
    )


def normalize_text(
    text: str
) -> str:

    return " ".join(
        text.split()
    )