# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching the source of a given web site as DOM nodes or a
string.

##################################################################################
# WARNING! this module may return an xml namespace in the keys, e.g.,
# `{http://www.w3.org/1999/xhtml}` without the `lxml` parser (`pip install riko[xml]`)
# See https://github.com/nerevu/riko/issues/20 for more info
##################################################################################

This module fetches the source of a given web site as DOM nodes or a string.
This data can then be converted into a RSS/JSON feed or merged with other data
in your Pipe using the Regex module, String Builder modules and others that
will help achieve what you want.

By default, the module will output the DOM elements as items. You can
optionally use the "Emit items as string" checkbox if you need the html as a
string.

You can use the "Extract using XPATH" field to fine tune what you need from the
HTML Page. For example, if I want all the links in the page I can simply use
"/a" to grab all links. If I want all the images in the html I can do "/img".
Read more on XPATH. You can also find XPATH statements using firebug to target
data that you want in a HTML page.

You have the option to run the parser using support for HTML4 (by default) or
checking the "Use HTML5 parser" checkbox to use the HTML5 parser.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.xpathfetchpage import pipe
        >>>
        >>> url = get_path('ouseful.xml')
        >>> conf = {'url': url, 'xpath': '/rss/channel/item'}
        >>> next(pipe(conf=conf))['title'][:44]
        'Running “Native” Data Wrangling Applications'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator, Sequence
from decimal import Decimal
from os.path import splitext
from typing import cast

import pygogo as gogo

from riko import ENCODING, Objconf
from riko.bado import io
from riko.cast import BasicCastType
from riko.parsers import Stringy, any2dict
from riko.types.general import Defaults, Extraction, FileTypes, ItemArg, Opts
from riko.types.values import ComplexArg, ComplexMapping, StrictDate
from riko.utils import Fetch, auto_close

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE}
DEFAULTS = Defaults({"encoding": ENCODING})
logger = gogo.Gogo(__name__, monolog=True).logger


# TODO: convert relative links to absolute
# TODO: remove the closing tag if using an HTML tag stripped of HTML tags
# TODO: clean html with Tidy


async def async_parser(
    _: ItemArg, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[
    Stringy | Decimal | float | ComplexMapping | StrictDate | Sequence[ComplexArg]
]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from traceback import format_exc
        >>>
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> async def run(reactor):
        ...     xml_url = get_path('ouseful.xml')
        ...     xml_conf = {'url': xml_url, 'xpath': '/rss/channel/item'}
        ...     xml_objconf = Objectify(xml_conf)
        ...     xml_args = (None, None, xml_objconf)
        ...     html_url = get_path('sciencedaily.html')
        ...     html_conf = {'url': html_url, 'xpath': '/html/head/title'}
        ...     html_objconf = Objectify(html_conf)
        ...     html_args = (None, None, html_objconf)
        ...     kwargs = {'stream': {}}
        ...
        ...     try:
        ...         xml_stream = await async_parser(*xml_args, **kwargs)
        ...         html_stream = await async_parser(*html_args, **kwargs)
        ...         print(next(xml_stream)['title'][:44])
        ...         print(next(html_stream)['content'])
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(format_exc())
        ...
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Running “Native” Data Wrangling Applications
        Help Page -- ScienceDaily

    """
    ext = splitext(objconf.url)[1].lstrip(".")

    if objconf.url.startswith("http") and not ext:
        ext = "html"

    # TODO: centralize error handling and retry logic
    """
    from twisted.internet import error as inet_error

    except (
        inet_error.DNSLookupError,
        inet_error.ConnectionRefusedError,
        inet_error.TimeoutError,
        inet_error.ConnectionLost,
    ) as e:
        logger.warning("Network error fetching %s: %s", objconf.url, e)
        stream = iter(())

    except UnicodeDecodeError as e:
        logger.error("Encoding error fetching %s: %s", objconf.url, e)
        stream = iter(())

    except OSError as e:
        logger.error("Filesystem error during fetch of %s: %s", objconf.url, e)
        stream = iter(())
    """
    f = await io.async_url_open(objconf.url, encoding=objconf.encoding)
    content = any2dict(f, ext, objconf.html5, path=objconf.xpath)
    stream = auto_close(content, f)
    return stream


def parser(
    _: ItemArg, extraction: Extraction, objconf: Objconf, **kwargs
) -> Iterator[
    Stringy | Decimal | float | ComplexMapping | StrictDate | Sequence[ComplexArg]
]:
    """
    Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from meza.fntools import Objectify
        >>> from riko import get_path
        >>>
        >>> url = get_path('ouseful.xml')
        >>> objconf = Objectify({'url': url, 'xpath': '/rss/channel/item'})
        >>> result = parser(None, None, objconf)
        >>> next(result)['title'][:44]
        'Running “Native” Data Wrangling Applications'

    """
    ext = splitext(objconf.url)[1].lstrip(".")

    if objconf.url.startswith("http") and not ext:
        ext = "html"

    with Fetch(objconf.url, encoding=objconf.encoding) as f:
        content = cast(FileTypes, f)
        yield from any2dict(content, ext, objconf.html5, path=objconf.xpath)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(
    *args, **kwargs
) -> Iterator[
    Stringy | Decimal | float | ComplexMapping | StrictDate | Sequence[ComplexArg]
]:
    """
    A source that asynchronously fetches the content of a given website as
    DOM nodes or a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', or 'html5'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)

        assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from traceback import format_exc
        >>>
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     xml_url = get_path('ouseful.xml')
        ...     xml_conf = {'url': xml_url, 'xpath': '/rss/channel/item'}
        ...     html_url = get_path('sciencedaily.html')
        ...     html_conf = {'url': html_url, 'xpath': '/html/head/title'}
        ...
        ...     try:
        ...         xml_stream = await async_pipe(conf=xml_conf)
        ...         html_stream = await async_pipe(conf=html_conf)
        ...         print(next(xml_stream)['guid']['content'])
        ...         print(next(html_stream)['content'])
        ...     except Exception as e:
        ...         logger.error(e)
        ...         logger.error(format_exc())
        ...
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        http://blog.ouseful.info/?p=12065
        Help Page -- ScienceDaily

    """
    parsed = await async_parser(*args, **kwargs)
    return parsed


@processor(DEFAULTS, **OPTS)
def pipe(
    *args, **kwargs
) -> Iterator[
    Stringy | Decimal | float | ComplexMapping | StrictDate | Sequence[ComplexArg]
]:
    """
    A source that fetches the content of a given website as DOM nodes or a
    string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'xpath', or 'html5'.

            url (str): The web site to fetch
            xpath (str): The XPATH to extract (default: None, i.e., return
                entire page)

            html5 (bool): Use the HTML5 parser (default: False)

        assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path('ouseful.xml')
        >>> conf = {'url': url, 'xpath': '/rss/channel/item'}
        >>> sorted(next(pipe(conf=conf)))[-3:]
        ['link', 'pubDate', 'title']
        >>> next(pipe(conf=conf)).get("guid")
        {'isPermaLink': 'false', 'content': 'http://blog.ouseful.info/?p=12065'}
        >>> url = get_path('sciencedaily.html')
        >>> conf = {'url': url, 'xpath': '/html/head/title'}
        >>> next(pipe(conf=conf))['content']
        'Help Page -- ScienceDaily'

    """
    return parser(*args, **kwargs)
