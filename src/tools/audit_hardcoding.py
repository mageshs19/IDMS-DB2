import re
from pathlib import Path


SEARCH_TERMS = [
    "0400",
    "0405",
    "0410",
    "0415",
    "0420",
    "0425",
    "0430",
    "0435",
    "0440",
    "0445",
    "0450",
    "0455",
    "0460",
    "DEPARTMENT",
    "EMPLOYEE",
    "EMPOSITION",
    "JOB",
    "OFFICE",
    "COVERAGE",
    "EXPERTISE",
    "NON-HOSP",
    "SKILL",
    "STRUCTURE",
    "DEPT-EMPLOYEE",
    "EMP-EMPOSITION",
    "JOB-EMPOSITION",
    "OFFICE-EMPLOYEE",
    "NEW-DEPT-STORE-DEPARTMENT",
    "OLD-DEPT-ERASE-DEPARTMENT",
    "OLD-LASTNAME-MODIFY-EMPLOYEE",
]


SKIP_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "data",
    "output",
    "temp",
    "logs",
    "tests",
}


SKIP_FILES = {
    "audit_hardcoding.py",
    "installed.txt",
}


INCLUDE_SUFFIXES = {
    ".py",
}


FALSE_POSITIVE_SUBSTRINGS = {
    "STRUCTUREDBLOCKS",
    "CLASS STRUCTUREDBLOCKS",
    "FROM IDMS_DB2_CONVERTER.TRANSFORMERS.STRUCTURED_BLOCKS",
    "IDMS_DB2_CONVERTER.TRANSFORMERS.STRUCTURED_BLOCKS",
}


def should_skip(
    path: Path,
) -> bool:
    if path.name in SKIP_FILES:
        return True

    parts = set(
        part.lower()
        for part in path.parts
    )

    if parts.intersection(SKIP_DIRS):
        return True

    if path.suffix.lower() not in INCLUDE_SUFFIXES:
        return True

    return False


def strip_docstrings(
    text: str,
) -> str:
    text = re.sub(
        r'""".*?"""',
        "",
        text,
        flags=re.DOTALL,
    )

    text = re.sub(
        r"'''.*?'''",
        "",
        text,
        flags=re.DOTALL,
    )

    return text


def is_likely_comment_line(
    line: str,
) -> bool:
    stripped = line.strip()

    if not stripped:
        return True

    return stripped.startswith(
        (
            "#",
            "*",
            "- ",
        )
    )


def contains_false_positive(
    line: str,
) -> bool:
    upper_line = line.upper()

    for value in FALSE_POSITIVE_SUBSTRINGS:
        if value in upper_line:
            return True

    return False


def term_pattern(
    term: str,
) -> re.Pattern:
    escaped = re.escape(
        term,
    )

    if re.fullmatch(
        r"\d+",
        term,
    ):
        return re.compile(
            rf"(?<!\d){escaped}(?!\d)",
            re.IGNORECASE,
        )

    return re.compile(
        rf"(?<![A-Z0-9_-]){escaped}(?![A-Z0-9_-])",
        re.IGNORECASE,
    )


def main() -> None:
    root = Path.cwd()

    findings: list[str] = []

    compiled_terms = [
        (
            term,
            term_pattern(term),
        )
        for term in SEARCH_TERMS
    ]

    for path in root.rglob("*"):
        if not path.is_file():
            continue

        if should_skip(path):
            continue

        try:
            text = path.read_text(
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            continue

        text_without_docstrings = strip_docstrings(
            text,
        )

        for line_number, line in enumerate(
            text_without_docstrings.splitlines(),
            start=1,
        ):
            if is_likely_comment_line(
                line,
            ):
                continue

            if contains_false_positive(
                line,
            ):
                continue

            for term, pattern in compiled_terms:
                if pattern.search(line):
                    findings.append(
                        f"{path}:{line_number}: {line.strip()}"
                    )

    if not findings:
        print(
            "No hardcoded demo terms found in scanned Python logic."
        )
        return

    print(
        "Potential hardcoded demo terms found in Python logic:"
    )

    print()

    for item in findings:
        print(
            item,
        )


if __name__ == "__main__":
    main()