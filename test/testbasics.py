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
        p = pipe2py.compile.parse_and_build_pipe(pipe_def)
        
        count = 0
        for i in p:
            count += 1
            self.assertTrue("the" in i.get('description'))
            
        self.assertEqual(count, 4)

    def test_simplest(self):
        """Loads the RTW simple test pipeline and compiles and executes it to check the results
        """
        pipe_def = self._get_pipe_def("testpipe_simplest.json")
        p = pipe2py.compile.parse_and_build_pipe(pipe_def)
        
        count = 0
        for i in p:
            count += 1
            
        self.assertTrue(count > 0)
        
    def test_simpletagger(self):
        """Loads the RTW simple tagger pipeline and compiles and executes it to check the results
        """
        pipe_def = self._get_pipe_def("testpipe_simpletagger.json")
        p = pipe2py.compile.parse_and_build_pipe(pipe_def)
        
        count = 0
        for i in p:
            count += 1
            
        self.assertTrue(count > 0)
        
        
    #todo test malformed pipeline syntax too

if __name__ == '__main__':
    unittest.main()
