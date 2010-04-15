"""Unit tests using basic pipeline modules"""

import unittest

import pipe2py.compile

import fileinput
try:
    import json
except ImportError:
    import simplejson as json
    
    
class TestBasics(unittest.TestCase):

    def setUp(self):
        pass
    
    def tearDown(self):
        pass
    
    def _get_pipe_def(self, filename):
        pjson = []
        for line in fileinput.input(filename):
            pjson.append(line)    
        pjson = "".join(pjson)
        pipe_def = json.loads(pjson)
        
        return pipe_def
        

    def test_feed(self):
        """Loads a simple test pipeline and compiles and executes it to check the results
       
           TODO: have these tests iterate over a number of test pipelines
        """
        pipe_def = self._get_pipe_def("testpipe1.json")
        p = pipe2py.compile.parse_and_build_pipe(pipe_def, verbose=True)
        
        count = 0
        for i in p:
            count += 1
            self.assertTrue("the" in i.get('description'))
            
        self.assertEqual(count, 4)

    def test_simplest(self):
        """Loads the RTW simple test pipeline and compiles and executes it to check the results
        """
        pipe_def = self._get_pipe_def("pipe_2de0e4517ed76082dcddf66f7b218057.json")
        p = pipe2py.compile.parse_and_build_pipe(pipe_def, verbose=True)
        
        count = 0
        for i in p:
            count += 1
            
        self.assertTrue(count > 0)

    #Note: this test will be skipped for now
    # - it requires a TermExtractor module which isn't top of the list
    #   and it needs a neat way for tests to auto-compile/load subpipes
    #def test_simpletagger(self):
        #"""Loads the RTW simple tagger pipeline and compiles and executes it to check the results
        #"""
        ##Note: uses a subpipe pipe_2de0e4517ed76082dcddf66f7b218057
        ##      so this must be compiled into a module before this pipe will work
        #pipe_def = self._get_pipe_def("pipe_93abb8500bd41d56a37e8885094c8d10.json")
        #p = pipe2py.compile.parse_and_build_pipe(pipe_def, verbose=True)
        
        #count = 0
        #for i in p:
            #count += 1
            
        #self.assertTrue(count > 0)
        
    #Note: this test will be skipped for now
    # - it needs a neat way for tests to skip user interaction prompts
    #def test_urlbuilder(self):
        #"""Loads the RTW URL Builder test pipeline and compiles and executes it to check the results
        #"""
        #pipe_def = self._get_pipe_def("pipe_e519dd393f943315f7e4128d19db2eac.json")
        #p = pipe2py.compile.parse_and_build_pipe(pipe_def, verbose=True)
        
        #count = 0
        #for i in p:
            #count += 1
            
        #self.assertTrue(count > 0)
        
        
        
    #todo test malformed pipeline syntax too

if __name__ == '__main__':
    unittest.main()
