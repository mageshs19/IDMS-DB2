import os
from pathlib import Path
from graphviz import Digraph

from idms_modernizer.domain.schema_models import (
    SchemaMetadata
)


def generate_er_diagram(
    metadata: SchemaMetadata,
    output_path: str
) -> str:
    """Generate a simple ER diagram PNG from the canonical metadata.

    Nodes are records and edges are relationships (labeled with set name
    and cardinality if present).
    Returns the path to the generated PNG file.
    """

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] += (
        os.pathsep +
        r"C:\Program Files\Graphviz\bin"
)

    dot = Digraph("er", format="png")
    dot.attr(rankdir="LR")
    dot.attr("node", shape="box")

    # Add record nodes
    for record in metadata.records:
        # simple label: record name
        dot.node(record.name, label=record.name)

    # Add relationships
    for rel in metadata.relationships:
        owner = rel.owner_record
        member = rel.member_record
        label = rel.set_name
        if getattr(rel, "cardinality", None):
            label = f"{label}\n{rel.cardinality}"

        dot.edge(owner, member, label=label)

    # Render to the requested path (without extension)
    filename_no_ext = str(out.with_suffix(""))

    try:

        dot.render(
            filename=filename_no_ext,
            cleanup=True
        )

    except Exception as ex:

        raise RuntimeError(
            "Graphviz not installed. "
            "Install Graphviz and add "
            "'C:\\Program Files\\Graphviz\\bin' "
            "to PATH."
        ) from ex

    # Graphviz writes the .png next to filename_no_ext
    png_path = filename_no_ext + ".png"

    return png_path
