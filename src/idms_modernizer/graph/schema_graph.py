import networkx as nx


class SchemaGraph:

    def __init__(self):

        self.graph = nx.DiGraph()

    def add_record(
        self,
        record_name: str
    ):

        self.graph.add_node(
            record_name,
            node_type="record"
        )

    def add_relationship(
        self,
        owner: str,
        member: str,
        set_name: str
    ):

        self.graph.add_edge(
            owner,
            member,
            set_name=set_name
        )