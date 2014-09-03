# pipeforever.py
#


def pipe_forever():
    """This is a source to enable other modules, e.g. date builder, to be
       called so they can continue to consume values from indirect terminal
       inputs

    Yields (_OUTPUT):
    True
    """
    while True:
        yield {'forever': True}
