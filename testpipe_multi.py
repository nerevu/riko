from multiprocessing import Process, Queue

from sourcefetchfeed import *
from sourcefilterfeed import *

#e.g. package
def testpipe1():
    s1 = source_fetchfeed(["testpipe1.py"])
    s2 = source_filterfeed("t", s1)
    return s2

#p = testpipe1()
#print p
#for l in p:
#    print l

if __name__=='__main__':
    q = Queue()
    
    p1 = Process(target=source_fetchfeedq, args=(q, ["testpipe1.py"]))
    p1.start()
    p2 = Process(target=source_filterfeedq, args=(q, "t", p1))
    p2.start()
    #todo
    #print q.get()    # prints "[42, None, 'hello']"
    #p.join()    