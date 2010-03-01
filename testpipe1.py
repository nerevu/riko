#todo future: from multiprocessing import Process, Queue

try:
    import wingdbstub
except:
    pass

from pipefetch import *
from pipefilter import *
from pipeoutput import *

def pipe_88ac07fd0ecb8975034ab9ed44e88945():
    """A simple pipe
    
    Yields (_OUTPUT)
    
    derived manually from:
    {"layout":[{"id":"_OUTPUT","xy":[230,366]},{"id":"sw-90","xy":[25,25]},{"id":"sw-102","xy":[77,148]}],
    
     "modules":[
       {"type":"output","id":"_OUTPUT","conf":[]},
       {"type":"fetch","id":"sw-90","conf":{"URL":{"value":"http://writetoreply.org/feed","type":"url"}}},
       {"type":"filter","id":"sw-102","conf":{
         "MODE":{"type":"text","value":"permit"},
         "COMBINE":{"type":"text","value":"and"},
         "RULE":[{"field":{"value":"title","type":"text"},"op":{"type":"text","value":"contains"},"value":{"value":"By","type":"text"}}]}}],
       
     "terminaldata":[
       {"id":"_OUTPUT","moduleid":"sw-90",
         "data":{"_type":"item","_attr":{"link":{"_type":"url","_count":"7"},"y:id":{"_type":"","_attr":{"value":{"_type":"url","_count":"6"},"permalink":{"_type":"text","_count":"7"}}},"slash:comments":{"_type":"number","_count":"7"},"wfw:commentRss":{"_type":"url","_count":"7"},"description":{"_type":"text","_count":"4"},"comments":{"_type":"url","_count":"7"},"dc:creator":{"_type":"text","_count":"7"},"content:encoded":{"_type":"text","_count":"7"},"y:title":{"_type":"text","_count":"7"},"title":{"_type":"text","_count":"7"},"category":{"_type":"text","_count":"7"},"guid":{"_type":"","_attr":{"isPermaLink":{"_type":"text","_count":"7"},"content":{"_type":"url","_count":"6"}}},"pubDate":{"_type":"datetime","_count":"7"},"y:published":{"_type":"datetime","_attr":{"hour":{"_type":"number","_count":"7"},"timezone":{"_type":"text","_count":"7"},"second":{"_type":"number","_count":"7"},"month":{"_type":"number","_count":"7"},"minute":{"_type":"number","_count":"7"},"utime":{"_type":"number","_count":"7"},"day_of_week":{"_type":"number","_count":"7"},"day":{"_type":"number","_count":"7"},"year":{"_type":"number","_count":"7"}}}}}},
       {"id":"_OUTPUT","moduleid":"sw-102",
         "data":{"_type":"item","_attr":{"link":{"_type":"url","_count":"4"},"y:id":{"_type":"","_attr":{"value":{"_type":"url","_count":"3"},"permalink":{"_type":"text","_count":"4"}}},"slash:comments":{"_type":"number","_count":"4"},"wfw:commentRss":{"_type":"url","_count":"4"},"description":{"_type":"text","_count":"4"},"comments":{"_type":"url","_count":"4"},"dc:creator":{"_type":"text","_count":"4"},"content:encoded":{"_type":"text","_count":"4"},"y:title":{"_type":"text","_count":"4"},"title":{"_type":"text","_count":"4"},"category":{"_type":"text","_count":"4"},"guid":{"_type":"","_attr":{"isPermaLink":{"_type":"text","_count":"4"},"content":{"_type":"url","_count":"3"}}},"pubDate":{"_type":"datetime","_count":"4"},"y:published":{"_type":"datetime","_attr":{"hour":{"_type":"number","_count":"4"},"timezone":{"_type":"text","_count":"4"},"second":{"_type":"number","_count":"4"},"month":{"_type":"number","_count":"4"},"minute":{"_type":"number","_count":"4"},"utime":{"_type":"number","_count":"4"},"day_of_week":{"_type":"number","_count":"4"},"day":{"_type":"number","_count":"4"},"year":{"_type":"number","_count":"4"}}}}}}],
         
     "wires":[
       {"id":"_w1","src":{"id":"_OUTPUT","moduleid":"sw-90"},"tgt":{"id":"_INPUT","moduleid":"sw-102"}},
       {"id":"_w3","src":{"id":"_OUTPUT","moduleid":"sw-102"},"tgt":{"id":"_INPUT","moduleid":"_OUTPUT"}}]}
    """
    
    ##sw_90 = source_fetchfeed(["http://writetoreply.org/feed"])
    sw_90 = pipe_fetch(["test/feed.xml"])
    sw_102 = pipe_filter(sw_90, "permit", "and", [("title", "contains", "By")])  #_w1
    _OUTPUT = pipe_output(sw_102)  #_w3

    return _OUTPUT

if __name__=='__main__':
    p = pipe_88ac07fd0ecb8975034ab9ed44e88945()
    
    for r in p:
        print r
    
    