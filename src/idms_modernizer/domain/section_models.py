from dataclasses import dataclass, field


@dataclass
class RecordSection:
    record_name: str
    lines: list[str] = field(
        default_factory=list
    )