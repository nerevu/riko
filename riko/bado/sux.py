# -*- test-case-name: twisted.web.test.test_xml -*-
#
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.


"""
*S*mall, *U*ncomplicated *X*ML.

This is a very simple implementation of XML/HTML as a network
protocol.  It is not at all clever.  Its main features are that it
does not:

  - support namespaces
  - mung mnemonic entity references
  - validate
  - perform *any* external actions (such as fetching URLs or writing files)
    under *any* circumstances
  - has lots and lots of horrible hacks for supporting broken HTML (as an
    option, they're not on by default).
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from builtins import *  # noqa pylint: disable=unused-import

from chardet import detect
from meza.compat import decode

try:
    from twisted.internet.protocol import Protocol
except ImportError:
    Protocol = object
else:
    from twisted.python.reflect import prefixedMethodNames as find_method_names

logger = gogo.Gogo(__name__, monolog=True).logger

# Elements of the three-tuples in the state table.
BEGIN_HANDLER = 0
DO_HANDLER = 1
END_HANDLER = 2
IDENTCHARS = '.-_:'
LENIENT_IDENTCHARS = IDENTCHARS + ';+#/%~'

nop = lambda *args, **kwargs: None


def zipfndict(*args):
    for fndict in args:
        for key in fndict:
            yield (key, tuple(x.get(key, nop) for x in args))


def get_method_obj_dict(obj, prefix):
    names = find_method_names(obj.__class__, prefix)
    return {name: getattr(obj, prefix + name) for name in names}


class ParseError(Exception):
    def __init__(self, filename, line, col, message):
        self.filename = filename
        self.line = line
        self.col = col
        self.message = message

    def __str__(self):
        return "%s:%s:%s: %s" % (
            self.filename, self.line, self.col, self.message)


class XMLParser(Protocol):
    state = None
    encoding = None
    bom = None
    attrname = ''
    attrval = ''

    # _leadingBodyData will sometimes be set before switching to the
    # 'bodydata' state, when we "accidentally" read a byte of bodydata
    # in a different state.
    _leadingBodyData = None

    def __init__(self, filename='unnamed', **kwargs):
        self.filename = filename
        self.lenient = kwargs.get('lenient')
        self.strict = not self.lenient

    # protocol methods
    def connectionMade(self):
        self.lineno = 1
        self.colno = 0

    def saveMark(self):
        '''Get the line number and column of the last character parsed'''
        # This gets replaced during dataReceived, restored afterwards
        return (self.lineno, self.colno)

    def _raise_parse_error(self, message):
        raise ParseError(*((self.filename,) + self.saveMark() + (message,)))

    def _build_state_table(self):
        '''Return a dictionary of begin, do, end state function tuples'''
        # _build_state_table leaves something to be desired but it does what it
        # does.. probably slowly, so I'm doing some evil caching so it doesn't
        # get called more than once per class.
        stateTable = getattr(self.__class__, '__stateTable', None)

        if stateTable is None:
            prefixes = ('begin_', 'do_', 'end_')
            fndicts = (get_method_obj_dict(self, p) for p in prefixes)
            stateTable = dict(zipfndict(*fndicts))
            self.__class__.__stateTable = stateTable

        return stateTable

    def check_encoding(self, data):
        if self.encoding.startswith('UTF-16'):
            data = data[2:]

        if 'UTF-16' in self.encoding or 'UCS-2' in self.encoding:
            assert not len(data) & 1, 'UTF-16 must come in pairs for now'

    def maybeBodyData(self):
        if self.endtag:
            return 'bodydata'

        # Get ready for fun! We're going to allow
        # <script>if (foo < bar)</script> to work!
        # We do this by making everything between <script> and
        # </script> a Text
        # BUT <script src="foo"> will be special-cased to do regular,
        # lenient behavior, because those may not have </script>
        # -radix
        if (self.tagName == 'script' and 'src' not in self.tagAttributes):
            # we do this ourselves rather than having begin_waitforendscript
            # because that can get called multiple times and we don't want
            # bodydata to get reset other than the first time.
            self.begin_bodydata(None)
            return 'waitforendscript'

        return 'bodydata'

    def dataReceived(self, data):
        stateTable = self._build_state_table()
        self.encoding = self.encoding or detect(data)['encoding']
        self.check_encoding(data)
        self.state = self.state or 'begin'
        content = decode(data, self.encoding)

        # bring state, lineno, colno into local scope
        lineno, colno = self.lineno, self.colno
        curState = self.state

        # replace saveMark with a nested scope function
        saveMark = lambda: (lineno, colno)
        self.saveMark, _saveMark = saveMark, self.saveMark

        # fetch functions from the stateTable
        beginFn, doFn, endFn = stateTable[curState]

        try:
            for char in content:
                # do newline stuff
                if char == '\n':
                    lineno += 1
                    colno = 0
                else:
                    colno += 1

                newState = doFn(char)

                if newState and newState != curState:
                    # this is the endFn from the previous state
                    endFn()
                    curState = newState
                    beginFn, doFn, endFn = stateTable[curState]
                    beginFn(char)
        finally:
            self.saveMark = _saveMark
            self.lineno, self.colno = lineno, colno

        # state doesn't make sense if there's an exception..
        self.state = curState

    def connectionLost(self, reason):
        """
        End the last state we were in.
        """
        stateTable = self._build_state_table()
        stateTable[self.state][END_HANDLER]()

    # state methods

    def do_begin(self, byte):
        if byte.isspace():
            return

        if byte != '<' and self.lenient:
            self._leadingBodyData = byte
            return 'bodydata'
        elif byte != '<':
            msg = "First char of document [%r] wasn't <" % (byte,)
            self._raise_parse_error(msg)

        return 'tagstart'

    def begin_comment(self, byte):
        self.commentbuf = ''

    def do_comment(self, byte):
        self.commentbuf += byte

        if self.commentbuf.endswith('-->'):
            self.gotComment(self.commentbuf[:-3])
            return 'bodydata'

    def begin_tagstart(self, byte):
        self.tagName = ''               # name of the tag
        self.tagAttributes = {}         # attributes of the tag
        self.termtag = 0                # is the tag self-terminating
        self.endtag = 0

    def _get_val(self, byte):
        val = None
        alnum_or_ident = byte.isalnum() or byte in IDENTCHARS
        is_good = alnum_or_ident or byte in '/!?[' or byte.isspace()

        if byte == '-' and self.tagName == '!-':
            val = 'comment'
        elif byte.isspace() and self.tagName:
            # properly strict thing to do here is probably to only
            # accept whitespace
            val = 'waitforgt' if self.endtag else 'attrs'
        elif byte in '>/[':
            def_gt = self.strict and 'bodydata' or self.maybeBodyData()

            switch = {
                '>': 'bodydata' if self.endtag else def_gt,
                '/': 'afterslash'if self.tagName else None,
                '[': 'expectcdata' if self.tagName == '!' else None}

            val = switch[byte]

        if not (self.lenient or val or is_good):
            self._raise_parse_error('Invalid tag character: %r' % byte)

        return val

    def _update_tags(self, byte):
        alnum_or_ident = byte.isalnum() or byte in IDENTCHARS

        if (byte in '!?') or alnum_or_ident:
            self.tagName += byte
        elif byte == '>' and self.endtag:
            self.gotTagEnd(self.tagName)
        elif byte == '>':
            self.gotTagStart(self.tagName, {})
        elif byte == '/' and not self.tagName:
            self.endtag = 1
        elif byte in '!?' and not self.tagName:
            self.tagName += byte
            self.termtag = 1

    def do_tagstart(self, byte):
        if byte.isspace() and not self.tagName:
            self._raise_parse_error("Whitespace before tag-name")
        elif byte in '!?' and self.tagName and self.strict:
            self._raise_parse_error("Invalid character in tag-name")
        elif byte == '[' and not self.tagName == '!':
            self._raise_parse_error("Invalid '[' in tag-name")

        val = self._get_val(byte)
        self._update_tags(byte)
        return val

    def begin_unentity(self, byte):
        self.bodydata += byte

    def do_unentity(self, byte):
        self.bodydata += byte
        return 'bodydata'

    def end_unentity(self):
        self.gotText(self.bodydata)

    def begin_expectcdata(self, byte):
        self.cdatabuf = byte

    def do_expectcdata(self, byte):
        self.cdatabuf += byte
        cdb = self.cdatabuf
        cd = '[CDATA['

        if len(cd) > len(cdb):
            if cd.startswith(cdb):
                return
            elif self.lenient:
                # WHAT THE CRAP!?  MSWord9 generates HTML that includes these
                # bizarre <![if !foo]> <![endif]> chunks, so I've gotta ignore
                # 'em as best I can.  this should really be a separate parse
                # state but I don't even have any idea what these _are_.
                return 'waitforgt'
            else:
                self._raise_parse_error("Mal-formed CDATA header")
        if cd == cdb:
            self.cdatabuf = ''
            return 'cdata'

        self._raise_parse_error("Mal-formed CDATA header")

    def do_cdata(self, byte):
        self.cdatabuf += byte
        if self.cdatabuf.endswith("]]>"):
            self.cdatabuf = self.cdatabuf[:-3]
            return 'bodydata'

    def end_cdata(self):
        self.gotCData(self.cdatabuf)
        self.cdatabuf = ''

    def do_attrs(self, byte):
        if byte.isalnum() or byte in IDENTCHARS:
            # XXX FIXME really handle !DOCTYPE at some point
            if self.tagName == '!DOCTYPE':
                return 'doctype'

            if self.tagName[0] in '!?':
                return 'waitforgt'

            return 'attrname'
        elif byte.isspace():
            return
        elif byte == '>':
            self.gotTagStart(self.tagName, self.tagAttributes)
            return self.strict and 'bodydata' or self.maybeBodyData()
        elif byte == '/':
            return 'afterslash'
        elif self.lenient:
            # discard and move on?  Only case I've seen of this so far was:
            # <foo bar="baz"">
            return

        self._raise_parse_error("Unexpected character: %r" % byte)

    def begin_doctype(self, byte):
        self.doctype = byte

    def do_doctype(self, byte):
        if byte == '>':
            return 'bodydata'

        self.doctype += byte

    def end_doctype(self):
        self.gotDoctype(self.doctype)
        self.doctype = None

    def do_waitforgt(self, byte):
        if byte == '>':
            if self.endtag or self.lenient:
                return 'bodydata'

            return self.maybeBodyData()

    def begin_attrname(self, byte):
        self.attrname = byte
        self._attrname_termtag = 0

    def _get_attrname(self, byte):
        if byte == '=':
            val = 'beforeattrval'
        elif byte.isspace():
            val = 'beforeeq'
        elif self.lenient and byte in '"\'':
            val = 'attrval'
        elif self.lenient and byte == '>':
            val = 'bodydata' if self._attrname_termtag else None
        else:
            # something is really broken. let's leave this attribute where it
            # is and move on to the next thing
            val = None

        return val

    def do_attrname(self, byte):
        if byte.isalnum() or byte in IDENTCHARS:
            self.attrname += byte
        elif self.strict and not (byte.isspace() or byte == '='):
            msg = "Invalid attribute name: %r %r" % (self.attrname, byte)
            self._raise_parse_error(msg)
        elif byte in LENIENT_IDENTCHARS or byte.isalnum():
            self.attrname += byte
        elif byte == '/':
            self._attrname_termtag = 1
        elif byte == '>':
            self.attrval = 'True'
            self.tagAttributes[self.attrname] = self.attrval
            self.gotTagStart(self.tagName, self.tagAttributes)
            self.gotTagEnd(self.tagName) if self._attrname_termtag else None

        return self._get_attrname(byte)

    def do_beforeattrval(self, byte):
        chars = LENIENT_IDENTCHARS
        val = None

        if byte in '"\'':
            val = 'attrval'
        elif byte.isspace():
            pass
        elif self.lenient and (byte in chars or byte.isalnum()):
            val = 'messyattr'
        elif self.lenient and byte == '>':
            self.attrval = 'True'
            self.tagAttributes[self.attrname] = self.attrval
            self.gotTagStart(self.tagName, self.tagAttributes)
            val = self.maybeBodyData()
        elif self.lenient and byte == '\\':
            # I saw this in actual HTML once:
            # <font size=\"3\"><sup>SM</sup></font>
            pass
        else:
            msg = 'Invalid initial attribute value: %r; ' % byte
            msg += 'Attribute values must be quoted.'
            self._raise_parse_error(msg)

        return val

    def begin_beforeeq(self, byte):
        self._beforeeq_termtag = 0

    def do_beforeeq(self, byte):
        if byte == '=':
            return 'beforeattrval'
        elif byte.isspace():
            return
        elif self.lenient:
            if byte.isalnum() or byte in IDENTCHARS:
                self.attrval = 'True'
                self.tagAttributes[self.attrname] = self.attrval
                return 'attrname'
            elif byte == '>':
                self.attrval = 'True'
                self.tagAttributes[self.attrname] = self.attrval
                self.gotTagStart(self.tagName, self.tagAttributes)

                if self._beforeeq_termtag:
                    self.gotTagEnd(self.tagName)
                    return 'bodydata'

                return self.maybeBodyData()
            elif byte == '/':
                self._beforeeq_termtag = 1
                return

        self._raise_parse_error("Invalid attribute")

    def begin_attrval(self, byte):
        self.quotetype = byte
        self.attrval = ''

    def do_attrval(self, byte):
        if byte == self.quotetype:
            return 'attrs'
        self.attrval += byte

    def end_attrval(self):
        self.tagAttributes[self.attrname] = self.attrval
        self.attrname = self.attrval = ''

    def begin_messyattr(self, byte):
        self.attrval = byte

    def do_messyattr(self, byte):
        if byte.isspace():
            return 'attrs'
        elif byte == '>':
            endTag = 0

            if self.attrval.endswith('/'):
                endTag = 1
                self.attrval = self.attrval[:-1]

            self.tagAttributes[self.attrname] = self.attrval
            self.gotTagStart(self.tagName, self.tagAttributes)

            if endTag:
                self.gotTagEnd(self.tagName)
                return 'bodydata'

            return self.maybeBodyData()
        else:
            self.attrval += byte

    def end_messyattr(self):
        if self.attrval:
            self.tagAttributes[self.attrname] = self.attrval

    def begin_afterslash(self, byte):
        self._after_slash_closed = 0

    def do_afterslash(self, byte):
        # this state is only after a self-terminating slash, e.g. <foo/>
        if self._after_slash_closed:
            self._raise_parse_error("Mal-formed")  # XXX When does this happen??

        if byte != '>' and self.lenient:
            return
        elif byte != '>':
            self._raise_parse_error("No data allowed after '/'")

        self._after_slash_closed = 1
        self.gotTagStart(self.tagName, self.tagAttributes)
        self.gotTagEnd(self.tagName)

        # don't need maybeBodyData here because there better not be
        # any javascript code after a <script/>... we'll see :(
        return 'bodydata'

    def begin_bodydata(self, byte):
        if self._leadingBodyData:
            self.bodydata = self._leadingBodyData
            del self._leadingBodyData
        else:
            self.bodydata = ''

    def do_bodydata(self, byte):
        if byte == '<':
            return 'tagstart'
        if byte == '&':
            return 'entityref'
        self.bodydata += byte

    def end_bodydata(self):
        self.gotText(self.bodydata)
        self.bodydata = ''

    def do_waitforendscript(self, byte):
        if byte == '<':
            return 'waitscriptendtag'
        self.bodydata += byte

    def begin_waitscriptendtag(self, byte):
        self.temptagdata = ''
        self.tagName = ''
        self.endtag = 0

    def do_waitscriptendtag(self, byte):
        # 1 enforce / as first byte read
        # 2 enforce following bytes to be subset of "script" until
        #   tagName == "script"
        #   2a when that happens, gotText(self.bodydata) and
        #      gotTagEnd(self.tagName)
        # 3 spaces can happen anywhere, they're ignored
        #   e.g. < / script >
        # 4 anything else causes all data I've read to be moved to the
        #   bodydata, and switch back to waitforendscript state

        # If it turns out this _isn't_ a </script>, we need to
        # remember all the data we've been through so we can append it
        # to bodydata
        self.temptagdata += byte

        # 1
        if byte == '/':
            self.endtag = True
        elif not self.endtag:
            self.bodydata += "<" + self.temptagdata
            return 'waitforendscript'
        # 2
        elif byte.isalnum() or byte in IDENTCHARS:
            self.tagName += byte
            if not 'script'.startswith(self.tagName):
                self.bodydata += "<" + self.temptagdata
                return 'waitforendscript'
            elif self.tagName == 'script':
                self.gotText(self.bodydata)
                self.gotTagEnd(self.tagName)
                return 'waitforgt'
        # 3
        elif byte.isspace():
            return 'waitscriptendtag'
        # 4
        else:
            self.bodydata += "<" + self.temptagdata
            return 'waitforendscript'

    def begin_entityref(self, byte):
        self.erefbuf = ''
        self.erefextra = ''  # extra bit for lenient mode

    def do_entityref(self, byte):
        if byte.isspace() or byte == "<":
            if self.lenient:
                # '&foo' probably was '&amp;foo'
                if self.erefbuf and self.erefbuf != "amp":
                    self.erefextra = self.erefbuf

                self.erefbuf = "amp"

                if byte == "<":
                    return "tagstart"
                else:
                    self.erefextra += byte
                    return 'spacebodydata'

            self._raise_parse_error("Bad entity reference")
        elif byte != ';':
            self.erefbuf += byte
        else:
            return 'bodydata'

    def end_entityref(self):
        self.gotEntityReference(self.erefbuf)

    # hacky support for space after & in entityref in lenient
    # state should only happen in that case
    def begin_spacebodydata(self, byte):
        self.bodydata = self.erefextra
        self.erefextra = None

    do_spacebodydata = do_bodydata
    end_spacebodydata = end_bodydata

    # Sorta SAX-ish API

    def gotTagStart(self, name, attributes):
        '''Encountered an opening tag.

        Default behaviour is to print.'''
        print('begin', name, attributes)

    def gotText(self, data):
        '''Encountered text

        Default behaviour is to print.'''
        print('text:', repr(data))

    def gotEntityReference(self, entityRef):
        '''Encountered mnemonic entity reference

        Default behaviour is to print.'''
        print('entityRef: &%s;' % entityRef)

    def gotComment(self, comment):
        '''Encountered comment.

        Default behaviour is to ignore.'''
        pass

    def gotCData(self, cdata):
        '''Encountered CDATA

        Default behaviour is to call the gotText method'''
        self.gotText(cdata)

    def gotDoctype(self, doctype):
        """Encountered DOCTYPE

        This is really grotty: it basically just gives you everything between
        '<!DOCTYPE' and '>' as an argument.
        """
        print('!DOCTYPE', repr(doctype))

    def gotTagEnd(self, name):
        '''Encountered closing tag

        Default behaviour is to print.'''
        print('end', name)
