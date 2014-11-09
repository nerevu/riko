# pipefeedautodiscovery.py
#
from pipe2py import util
from pipe2py.lib import autorss
from pipe2py.lib.dotdict import DotDict


def pipe_feedautodiscovery(context=None, _INPUT=None, conf=None, **kwargs):
    """This source search for feed links in a page

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        URL -- url

    Yields (_OUTPUT):
    feed entries
    """
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = util.get_abspath(url)

            if context and context.verbose:
                print "pipe_feedautodiscovery loading:", url

            for entry in autorss.getRSSLink(url.encode('utf-8')):
                yield {'link': entry}
                # todo: add rel, type, title

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
