"""
Drop this in as `<biodigest env>/lib/python3.10/site-packages/graph_tool/__init__.py`
(i.e. create a `graph_tool/` directory in that site-packages and put this file in it as
`__init__.py`) after installing biodigest per environment_biodigest.yml.

Satisfies `import graph_tool as gt` (and `from graph_tool import Graph`, etc.), which
biodigest/evaluation/d_utils/plotting_utils.py does unconditionally at import time purely for one
subnetwork-plotting function this env doesn't need. Real graph_tool is Boost/CGAL-based, not
pip-installable, and a heavy conda-forge install (see environment_biodigest.yml's caution note) --
not worth it just to satisfy an unused import. Attribute access still raises, just only if
something actually tries to use it.
"""

_MSG = (
    "graph_tool.{name} was used, but this is a stub. "
    "The real graph_tool package (Boost/CGAL-based) was intentionally not installed "
    "since this env is only used for biodigest's gene/disease-set and clustering "
    "scoring, not its subnetwork plotting feature. Install graph_tool via "
    "`conda install -c conda-forge graph-tool` if subnetwork plots are needed."
)


class _StubProxy:
    """Satisfies `from graph_tool import X` / `gt.X` at import time; raises only on use."""

    def __init__(self, name):
        self._name = name

    def __call__(self, *args, **kwargs):
        raise ImportError(_MSG.format(name=self._name))

    def __getattr__(self, attr):
        raise ImportError(_MSG.format(name=f"{self._name}.{attr}"))


def __getattr__(name):
    return _StubProxy(name)


Graph = _StubProxy("Graph")
GraphView = _StubProxy("GraphView")
draw = _StubProxy("draw")
stats = _StubProxy("stats")
load_graph = _StubProxy("load_graph")
