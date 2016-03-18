from pipe import modules as mod
from pipe2py.lib.collections import SyncPipe


def pipe_gigs(*args, **kwargs):
    p68_conf={
        'URL': [
            {'value': 'http://www.guru.com/rss/jobs/c/web-software-it/'},
            {'value': 'https://www.elance.com/r/rss/jobs/cat-it-programming/fxd-true/o-1/bgt-gt500-ns1/sct-database-development-10217-data-analysis-14174-database-administration-14177-business-intelligence-14173-data-engineering-14175-system-administration-10219-other-data-science-14178-technical-support-10218-other-it-programming-12350-software-application-10216-website-design-10225-web-programming-10224/tls-1/s-timelistedSort'}]}

    p90_conf = {'field': 'link'}
    p87_conf = {'COMBINE': 'or', 'MODE': 'block', 'rule': [{'field': 'title', 'value': 'php', 'op': 'contains'}]}
    p101_conf = {'KEY': [{'field': 'pubDate', 'dir': 'desc'}]}

    p101 = (
        SyncPipe('fetch', conf=p68_conf)
            .uniq(conf=p90_conf)
            .filter(conf=p87_conf)
            .sort(conf=p101_conf)
            .output)

    return p101


if __name__ == "__main__":
    for i in pipe_gigs():
        print i
