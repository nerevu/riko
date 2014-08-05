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


if __name__ == '__main__':
    pjson = []

    usage = "usage: %prog [options] pipeid"
    parser = OptionParser(usage=usage)
    parser.add_option(
        "-v", dest="verbose", help="set verbose debug", action="store_true")
    (options, args) = parser.parse_args()

    pipeid = None
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
        pipe_def = json.loads(src)
        results = pipe_def['query']['results']

        if not results:
            print "Pipe not found"
            sys.exit(1)
        pjson = pipe_def['query']['results']['json']['PIPE']['working']
        pipe_def = pjson # json.loads(pjson)
        pjson = json.dumps(pjson)
        name = "pipe_%s" % pipeid

        fj = open(os.path.join("pipelines", "%s.json" % name), "w")   #todo confirm file overwrite
        print >>fj, pjson

        #Get the pipeline output
        url = ("""http://pipes.yahoo.com/pipes/pipe.run"""
               """?_id=""" + pipeid + """&_render=json""")
        ojson = urllib.urlopen(url).readlines()
        ojson = "".join(ojson)
        pipe_output = json.loads(ojson)
        if not pipe_output['count']:
            print "Pipe results not found"
            sys.exit(1)
        ojson = pipe_output

        fjo = open(os.path.join("pipelines", "%s_output.json" % name), "w")   #todo confirm file overwrite
        print >>fjo, ojson

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
