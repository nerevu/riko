"""Test creator

   Gets a pipeline definition from Yahoo and saves its json representation
   for testing.
   Also gets the pipelines output as json and saves it for testing.
"""

try:
    import json
    json.loads  # test access to the attributes of the right json module
except (ImportError, AttributeError):
    import simplejson as json

from optparse import OptionParser
import urllib
import os
import os.path
import sys
from pprint import pprint


if __name__ == '__main__':
    pjson = []
    pipeid = None

    usage = "usage: %prog [options] pipeid"
    parser = OptionParser(usage=usage)
    parser.add_option(
        "-v", dest="verbose", help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    if len(args):
        pipeid = args[0]
    if pipeid:
        # todo: refactor this url->json
        # Get the pipeline definition
        base = 'http://query.yahooapis.com/v1/public/yql?q='
        select = """select%20PIPE.working%20from%20json%20"""
        where = """where%20url%3D%22http%3A%2F%2Fpipes.yahoo.com"""
        pipe = """%2Fpipes%2Fpipe.info%3F_out%3Djson%26_id%3D"""
        end = '%22&format=json'
        url = base + select + where + pipe + pipeid + end

        name = "pipe_%s" % pipeid
        src = ''.join(urllib.urlopen(url).readlines())
        src_json = json.loads(src)
        results = src_json['query']['results']

        if not results:
            print "Pipe not found"
            sys.exit(1)

        pjson = results['json']['PIPE']['working']

        with open(os.path.join('pipelines', '%s.json' % name), 'w') as f:
            pprint(json.loads(pjson.encode("utf-8")), f)

        # Get the pipeline output
        base = 'http://pipes.yahoo.com/pipes/pipe.run'
        url = '%s?_id=%s&_render=json' % (base, pipeid)
        src = ''.join(urllib.urlopen(url).readlines())
        ojson = json.loads(src)

        if not ojson['count']:
            print 'Pipe results not found'
            sys.exit(1)

        path = os.path.join('data', '%s_output.json' % name)
        with open(path, 'w') as f:
            pprint(ojson.encode("utf-8"), f)

        # todo: to create stable, repeatable test cases we should:
        #  build the pipeline to find the external data sources
        #  download and save any fetchdata/fetch source data
        #  replace the fetchdata/fetch references with the local copy
        #  (so would need to save the pipeline python but that would make it
        #  hard to test changes, so we could declare a list of live->local-test
        #  file mappings and pass them in with the test context)
        #  also needs to handle any sub-pipelines and their external sources

        # optional:
        # todo: confirm file overwrite
        # fp = open(os.path.join('test', '%s.py' % name), 'w')
        # print >>fp, parse_and_write_pipe(context, pipe_def, name)
