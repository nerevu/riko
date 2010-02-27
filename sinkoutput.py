# sinkouput.py
#

def sink_output(_INPUT):
    """This sink prints source items to stdout.
    
    Keyword arguments:
    _INPUT -- source generator
    """
    for item in _INPUT:
        print item

# Example use

if __name__ == '__main__':
    sink_output(["one", "two"])
