"""Find RSS feed from site's LINK tag

   Modified by Greg Gaughan to yield a list of possible links
"""

__author__ = "Mark Pilgrim (f8dy@diveintomark.org)"
__copyright__ = "Copyright 2002, Mark Pilgrim"
__license__ = "Python"

try:
    import timeoutsocket  # http://www.timo-tasi.org/python/timeoutsocket.py
except ImportError:
    pass
else:
    timeoutsocket.setDefaultSocketTimeout(10)

from urllib2 import urlopen
from urlparse import urljoin
from sgmllib import SGMLParser

BUFFERSIZE = 1024


class LinkParser(SGMLParser):
    def reset(self):
        SGMLParser.reset(self)
        self.href = []

    def do_link(self, attrs):
        if not ('rel', 'alternate') in attrs:
            return

        if not ('type', 'application/rss+xml') in attrs:
            return

        hreflist = [e[1] for e in attrs if e[0] == 'href']

        if hreflist:
            self.href.extend(hreflist)

        self.setnomoretags()

    def end_head(self, attrs):
        self.setnomoretags()

    start_body = end_head


def getRSSLinkFromHTMLSource(html):
    try:
        parser = LinkParser()
        parser.feed(html)
        return parser.href
    except:
        return []


def getRSSLink(url):
    try:
        f = urlopen(url)
        parser = LinkParser()

        while True:
            chunk = f.read(BUFFERSIZE)
            parser.feed(chunk)

            if parser.nomoretags or not chunk:
                break

        return [urljoin(url, href) for href in parser.href]
    except:
        return []

if __name__ == '__main__':
    import sys
    print getRSSLink(sys.argv[1])
