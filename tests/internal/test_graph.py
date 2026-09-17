# acyclic topological ordering
# reverse ordering
# strict cycle failure
# SCC fallback
# key= deterministic ties
# referenced-only nodes
# descendants()
# cyclic descendants()
# freeze_graph()
# MappingProxyType immutability
# preservation of implicit/referenced-only nodes

import pytest

from riko.coercion._graph import descendants

assert descendants("a", {"a": {"b"}, "b": {"c"}}) == frozenset({"b", "c"})
assert descendants("b", {"a": {"b"}}) == frozenset()
assert descendants("a", {"a": {"b"}, "b": {"a"}}) == frozenset({"b"})

with pytest.raises(KeyError):
    descendants("c", {"a": {"b"}})
