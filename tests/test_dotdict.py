# vim: sw=4:ts=4:expandtab
"""
Tests DotDict deletion: root, nested, and case-insensitive.
"""

from riko.dotdict import DotDict


class TestDotDictDelete:
    def test_delete_root(self):
        d = DotDict({"author": "bar", "title": "foo"})
        d.delete("author")
        assert d.asdict() == {"title": "foo"}

    def test_delete_nested(self):
        d = DotDict({"author": {"name": "bar", "url": "x.com"}})
        d.delete("author.name")
        assert d.asdict() == {"author": {"url": "x.com"}}

    def test_delete_deeply_nested(self):
        d = DotDict({"a": {"b": {"c": 1, "d": 2}}})
        d.delete("a.b.c")
        assert d.asdict() == {"a": {"b": {"d": 2}}}

    def test_delete_root_case_insensitive(self):
        d = DotDict({"author": "bar", "title": "foo"})
        d.delete("AUTHOR")
        assert d.asdict() == {"title": "foo"}

    def test_delete_nested_case_insensitive(self):
        d = DotDict({"author": {"name": "bar", "url": "x.com"}})
        d.delete("Author.Name")
        assert d.asdict() == {"author": {"url": "x.com"}}

    def test_delete_deeply_nested_case_insensitive(self):
        d = DotDict({"a": {"b": {"c": 1, "d": 2}}})
        d.delete("A.B.C")
        assert d.asdict() == {"a": {"b": {"d": 2}}}

    def test_delete_missing_root_noop(self):
        d = DotDict({"author": "bar"})
        d.delete("missing")
        assert d.asdict() == {"author": "bar"}

    def test_delete_missing_nested_key_noop(self):
        d = DotDict({"author": {"name": "bar"}})
        d.delete("author.missing")
        assert d.asdict() == {"author": {"name": "bar"}}

    def test_delete_missing_intermediate_noop(self):
        d = DotDict({"author": {"name": "bar"}})
        d.delete("missing.name")
        assert d.asdict() == {"author": {"name": "bar"}}
