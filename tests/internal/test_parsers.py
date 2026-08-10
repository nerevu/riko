from typing import cast

from riko import get_path
from riko._io import Fetch
from riko.modules.xpathfetchpage import pipe as xpathfetchpage
from riko.parsers import any2dict
from riko.types.modules import XpathFetchPageConf


def test_any2dict_strips_xhtml_namespace_from_keys():
    url = get_path("capnorth.xml")

    with Fetch(url, binary=True) as f:
        result = next(any2dict(f))
        assert sorted(result) == [
            "code",
            "identifier",
            "info",
            "msgType",
            "scope",
            "sender",
            "sent",
            "status",
        ]

        assert sorted(cast(dict, result["info"])) == [
            "area",
            "category",
            "certainty",
            "description",
            "expires",
            "headline",
            "parameter",
            "severity",
            "urgency",
        ]


def test_xpathfetchpage_strips_xhtml_namespace_from_nested_keys():
    conf = XpathFetchPageConf(
        {"url": get_path("users.jyu.fi.html"), "xpath": "/html/body/p/a"}
    )

    assert next(xpathfetchpage(conf=conf)) == {
        "href": "http://www.w3.org/",
        "img": {"src": "http://www.w3.org/Icons/w3c_home", "alt": "W3C"},
    }
