# -*- test-case-name: twisted.web.test.test_xml -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Micro Document Object Model: a partial DOM implementation with SUX.

This is an implementation of what we consider to be the useful subset of the
DOM.  The chief advantage of this library is that, not being burdened with
standards compliance, it can remain very stable between versions.  We can also
implement utility 'pythonic' ways to access and mutate the XML tree.

Since this has not subjected to a serious trial by fire, it is not recommended
to use this outside of Twisted applications.  However, it seems to work just
fine for the documentation generator, which parses a fairly representative
sample of XML.

Microdom mainly focuses on working with HTML and XHTML.
"""

from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import re
import itertools as it

from io import open, BytesIO, StringIO
from functools import partial
from builtins import *

from meza._compat import encode, decode

try:
    from twisted.python.util import InsensitiveDict
except ImportError:
    pass

from .sux import XMLParser, ParseError
from riko.lib.utils import combine_dicts

# order is important
HTML_ESCAPE_CHARS = (
    ('&', '&amp;'),  # don't add any entities before this one
    ('<', '&lt;'), ('>', '&gt;'), ('"', '&quot;'))

REV_HTML_ESCAPE_CHARS = list(HTML_ESCAPE_CHARS)
REV_HTML_ESCAPE_CHARS.reverse()
XML_ESCAPE_CHARS = HTML_ESCAPE_CHARS + (("'", '&apos;'),)
REV_XML_ESCAPE_CHARS = list(XML_ESCAPE_CHARS)
REV_XML_ESCAPE_CHARS.reverse()


def unescape(text, chars=REV_HTML_ESCAPE_CHARS):
    "Perform the exact opposite of 'escape'."
    for s, h in chars:
        text = text.replace(h, s)

    return text


def escape(text, chars=HTML_ESCAPE_CHARS):
    "Escape a few XML special chars with XML entities."
    for s, h in chars:
        text = text.replace(s, h)

    return text


def unescape_dict(d):
    return {k: unescape(v) for k, v in d.items()}


def invert_dict(d):
    return {v: k for k, v in d.items()}


def getElementsByTagName(iNode, path, icase=False):
    """
    Return a list of all child elements of C{iNode} with a name matching
    C{name}.

    @param iNode: An element at which to begin searching.  If C{iNode} has a
        name matching C{name}, it will be included in the result.

    @param name: A C{str} giving the name of the elements to return.

    @return: A C{list} of direct or indirect child elements of C{iNode} with
        the name C{name}.  This may include C{iNode}.
    """
    same = lambda x, y: x.lower() == y.lower() if icase else x == y
    is_node = hasattr(iNode, 'nodeName')
    has_bracket = '[' in path

    if is_node and not has_bracket and same(iNode.nodeName, path):
        yield iNode

    if is_node and iNode.hasChildNodes():
        for c in getElementsByTagName(iNode.childNodes, path, icase):
            yield c

    if not is_node:
        name = path[:path.find('[')] if has_bracket else path
        pos = int(path[path.find('[') + 1:-1]) - 1 if has_bracket else 0
        nodes = [n for n in iNode if same(n.nodeName, name)]

        if pos < len(nodes):
            yield nodes[pos]

        for child in iNode:
            for c in getElementsByTagName(child, path, icase):
                yield c


class MismatchedTags(Exception):
    def __init__(self, *args):
        (
            self.filename, self.expect, self.got, self.begLine, self.begCol,
            self.endLine, self.endCol) = args

    def __str__(self):
        msg = 'expected </%(expect)s>, got </%(got)s> line: %(endLine)s '
        msg += 'col: %(endCol)s, began line: %(begLine)s, col: %(begCol)s'
        return (msg % self.__dict__)


class Node(object):
    nodeName = "Node"

    def __init__(self, parentNode=None):
        self.parentNode = parentNode
        self.childNodes = []

    def isEqualToNode(self, other):
        """
        Compare this node to C{other}.  If the nodes have the same number of
        children and corresponding children are equal to each other, return
        C{True}, otherwise return C{False}.

        @type other: L{Node}
        @rtype: C{bool}
        """
        if len(self.childNodes) != len(other.childNodes):
            return False

        for a, b in zip(self.childNodes, other.childNodes):
            if not a.isEqualToNode(b):
                return False

        return True

    def writexml(self, *args, **kwargs):
        raise NotImplementedError()

    def toxml(self, *args, **kwargs):
        s = StringIO()
        self.writexml(s, *args, **kwargs)
        return s.getvalue()

    def writeprettyxml(self, stream, *args, **kwargs):
        return self.writexml(stream, *args, **kwargs)

    def toprettyxml(self, **kwargs):
        return self.toxml(**kwargs)

    def cloneNode(self, deep=0, parent=None):
        raise NotImplementedError()

    def hasChildNodes(self):
        return self.childNodes

    def appendChild(self, child):
        """
        Make the given L{Node} the last child of this node.

        @param child: The L{Node} which will become a child of this node.

        @raise TypeError: If C{child} is not a C{Node} instance.
        """
        if not isinstance(child, Node):
            raise TypeError("expected Node instance")

        self.childNodes.append(child)
        child.parentNode = self

    def insertBefore(self, new, ref):
        """
        Make the given L{Node} C{new} a child of this node which comes before
        the L{Node} C{ref}.

        @param new: A L{Node} which will become a child of this node.

        @param ref: A L{Node} which is already a child of this node which
            C{new} will be inserted before.

        @raise TypeError: If C{new} or C{ref} is not a C{Node} instance.

        @return: C{new}
        """
        if not isinstance(new, Node) or not isinstance(ref, Node):
            raise TypeError("expected Node instance")

        i = self.childNodes.index(ref)
        new.parentNode = self
        self.childNodes.insert(i, new)
        return new

    def removeChild(self, child):
        """
        Remove the given L{Node} from this node's children.

        @param child: A L{Node} which is a child of this node which will no
            longer be a child of this node after this method is called.

        @raise TypeError: If C{child} is not a C{Node} instance.

        @return: C{child}
        """
        if not isinstance(child, Node):
            raise TypeError("expected Node instance")

        if child in self.childNodes:
            self.childNodes.remove(child)
            child.parentNode = None

        return child

    def replaceChild(self, newChild, oldChild):
        """
        Replace a L{Node} which is already a child of this node with a
        different node.

        @param newChild: A L{Node} which will be made a child of this node.

        @param oldChild: A L{Node} which is a child of this node which will
            give up its position to C{newChild}.

        @raise TypeError: If C{newChild} or C{oldChild} is not a C{Node}
            instance.

        @raise ValueError: If C{oldChild} is not a child of this C{Node}.
        """
        if not isinstance(newChild, Node) or not isinstance(oldChild, Node):
            raise TypeError("expected Node instance")

        if oldChild.parentNode is not self:
            raise ValueError("oldChild is not a child of this node")

        self.childNodes[self.childNodes.index(oldChild)] = newChild
        oldChild.parentNodem, newChild.parentNode = None, self

    def lastChild(self):
        return self.childNodes[-1]

    def firstChild(self):
        if len(self.childNodes):
            return self.childNodes[0]
        return None

    # def get_ownerDocument(self):
    #     """This doesn't really get the owner document; microdom nodes
    #     don't even have one necessarily.  This gets the root node,
    #     which is usually what you really meant.
    #     *NOT DOM COMPLIANT.*
    #     """
    #     node = self
    #     while (node.parentNode): node=node.parentNode
    #     return node

    # ownerDocument = node.get_ownerDocument()
    # leaving commented for discussion; see also domhelpers.getParents(node)


class Document(Node):
    def __init__(self, documentElement=None):
        Node.__init__(self)

        if documentElement:
            self.appendChild(documentElement)

    def cloneNode(self, deep=0, parent=None):
        d = Document()
        d.doctype = self.doctype

        if deep:
            newEl = self.documentElement.cloneNode(1, self)
        else:
            newEl = self.documentElement

        d.appendChild(newEl)
        return d

    doctype = None

    def isEqualToDocument(self, n):
        return (self.doctype == n.doctype) and Node.isEqualToNode(self, n)

    isEqualToNode = isEqualToDocument

    def get_documentElement(self):
        return self.childNodes[0]

    documentElement = property(get_documentElement)

    def appendChild(self, child):
        """
        Make the given L{Node} the I{document element} of this L{Document}.

        @param child: The L{Node} to make into this L{Document}'s document
            element.

        @raise ValueError: If this document already has a document element.
        """
        if self.childNodes:
            raise ValueError("Only one element per document.")

        Node.appendChild(self, child)

    def writexml(self, stream, *args, **kwargs):
        newl = kwargs['newl']
        stream.write('<?xml version="1.0"?>' + newl)

        if self.doctype:
            stream.write("<!DOCTYPE " + self.doctype + ">" + newl)

        self.documentElement.writexml(stream, *args, **kwargs)

    # of dubious utility (?)
    def createElement(self, name, **kw):
        return Element(name, **kw)

    def createTextNode(self, text):
        return Text(text)

    def createComment(self, text):
        return Comment(text)

    def getElementsByTagName(self, name):
        icase = self.documentElement.case_insensitive
        return getElementsByTagName(self.childNodes, name, icase)

    def getElementById(self, id):
        # TODO: rewrite this!!
        childNodes = self.childNodes[:]

        while childNodes:
            node = childNodes.pop(0)

            if node.childNodes:
                childNodes.extend(node.childNodes)

            if hasattr(node, 'getAttribute') and node.getAttribute('id') == id:
                return node


class EntityReference(Node):
    def __init__(self, eref, parentNode=None):
        Node.__init__(self, parentNode)
        self.eref = eref
        self.nodeValue = self.data = "&" + eref + ";"

    def isEqualToEntityReference(self, n):
        if not isinstance(n, EntityReference):
            return 0
        return (self.eref == n.eref) and (self.nodeValue == n.nodeValue)

    isEqualToNode = isEqualToEntityReference

    def writexml(self, stream, *args, **kwargs):
        stream.write(self.nodeValue)

    def cloneNode(self, deep=0, parent=None):
        return EntityReference(self.eref, parent)


class CharacterData(Node):
    def __init__(self, data, parentNode=None):
        Node.__init__(self, parentNode)
        self.value = self.data = self.nodeValue = data

    def isEqualToCharacterData(self, n):
        return self.value == n.value

    isEqualToNode = isEqualToCharacterData


class Comment(CharacterData):
    """A comment node"""
    def writexml(self, stream, *args, **kwargs):
        val = encode(self.data)
        stream.write("<!--%s-->" % val)

    def cloneNode(self, deep=0, parent=None):
        return Comment(self.nodeValue, parent)


class Text(CharacterData):
    def __init__(self, data, parentNode=None, raw=0):
        CharacterData.__init__(self, data, parentNode)
        self.raw = raw

    def isEqualToNode(self, other):
        """
        Compare this text to C{text}.  If the underlying values and the C{raw}
        flag are the same, return C{True}, otherwise return C{False}.
        """
        return (
            CharacterData.isEqualToNode(self, other) and
            self.raw == other.raw)

    def cloneNode(self, deep=0, parent=None):
        return Text(self.nodeValue, parent, self.raw)

    def writexml(self, stream, *args, **kwargs):
        if self.raw:
            val = decode(self.nodeValue)
        else:
            v = decode(self.nodeValue)
            v = ' '.join(v.split()) if kwargs.get('strip') else v
            val = escape(v)

        val = encode(val)
        stream.write(val)

    def __repr__(self):
        return "Text(%s" % repr(self.nodeValue) + ')'


class CDATASection(CharacterData):
    def cloneNode(self, deep=0, parent=None):
        return CDATASection(self.nodeValue, parent)

    def writexml(self, stream, *args, **kwargs):
        stream.write("<![CDATA[")
        stream.write(self.nodeValue)
        stream.write("]]>")


class _Attr(CharacterData):
    "Support class for getAttributeNode."


class Element(Node):
    nsprefixes = None
    create_attr = lambda k, v: (' ', k, '="', escape(v), '"')

    SINGLETONS = (
        'img', 'br', 'hr', 'base', 'meta', 'link', 'param',
        'area', 'input', 'col', 'basefont', 'isindex', 'frame')

    BLOCKELEMENTS = (
        'html', 'head', 'body', 'noscript', 'ins', 'del',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'script',
        'ul', 'ol', 'dl', 'pre', 'hr', 'blockquote',
        'address', 'p', 'div', 'fieldset', 'table', 'tr',
        'form', 'object', 'fieldset', 'applet', 'map')

    NICEFORMATS = ('tr', 'ul', 'ol', 'head')

    def __init__(
        self, tagName, attributes=None, parentNode=None, filename=None,
        markpos=None, case_insensitive=1, namespace=None
    ):
        Node.__init__(self, parentNode)
        preserve_case = not case_insensitive
        tagName = tagName if preserve_case else tagName.lower()
        unescaped = unescape_dict(attributes or {})

        if case_insensitive:
            self.attributes = InsensitiveDict(unescaped, preserve=preserve_case)
        else:
            self.attributes = unescaped

        self.preserve_case = not case_insensitive
        self.case_insensitive = case_insensitive
        self.endTagName = self.nodeName = self.tagName = tagName
        self._filename = filename
        self._markpos = markpos
        self.namespace = namespace
        self.tag_is_blockelement = tagName in self.BLOCKELEMENTS
        self.tag_is_nice_format = tagName in self.NICEFORMATS
        self.tag_is_singleton = tagName.lower() in self.SINGLETONS

    def addPrefixes(self, pfxs):
        if self.nsprefixes is None:
            self.nsprefixes = pfxs
        else:
            self.nsprefixes.update(pfxs)

    def endTag(self, endTagName):
        if self.case_insensitive:
            endTagName = endTagName.lower()

        self.endTagName = endTagName

    def isEqualToElement(self, n):
        same_attrs = self.attributes == n.attributes

        if self.case_insensitive:
            eq = same_attrs and (self.nodeName.lower() == n.nodeName.lower())
        else:
            eq = same_attrs and (self.nodeName == n.nodeName)

        return eq

    def isEqualToNode(self, other):
        """
        Compare this element to C{other}.  If the C{nodeName}, C{namespace},
        C{attributes}, and C{childNodes} are all the same, return C{True},
        otherwise return C{False}.
        """
        return (
            self.nodeName.lower() == other.nodeName.lower() and
            self.namespace == other.namespace and
            self.attributes == other.attributes and
            Node.isEqualToNode(self, other))

    def cloneNode(self, deep=0, parent=None):
        clone = Element(
            self.tagName, parentNode=parent, namespace=self.namespace,
            case_insensitive=self.case_insensitive)

        clone.attributes.update(self.attributes)

        if deep:
            clone.childNodes = [
                child.cloneNode(1, clone) for child in self.childNodes]
        else:
            clone.childNodes = []

        return clone

    def getElementsByTagName(self, name):
        icase = self.case_insensitive
        return getElementsByTagName(self.childNodes, name, icase)

    def hasAttributes(self):
        return 1

    def getAttribute(self, name, default=None):
        return self.attributes.get(name, default)

    def getAttributeNS(self, ns, name, default=None):
        nsk = (ns, name)

        if nsk in self.attributes:
            return self.attributes[nsk]

        if ns == self.namespace:
            return self.attributes.get(name, default)

        return default

    def getAttributeNode(self, name):
        return _Attr(self.getAttribute(name), self)

    def setAttribute(self, name, attr):
        self.attributes[name] = attr

    def removeAttribute(self, name):
        if name in self.attributes:
            del self.attributes[name]

    def hasAttribute(self, name):
        return name in self.attributes

    def gen_prefixes(self, nsprefixes):
        for k, v in self.nsprefixes.items():
            if k not in nsprefixes:
                yield (k, v)

    def _writexml(self, namespace, nsprefixes, newl, indent):
        newprefixes = dict(self.gen_prefixes(nsprefixes))
        begin = [newl, indent, '<'] if self.tag_is_blockelement else ['<']
        is_same_namespace = self.namespace and namespace == self.namespace

        # Make a local for tracking what end tag will be used. If namespace
        # prefixes are involved, this will be changed to account for that
        # before it's actually used.
        endTagName = self.endTagName

        if not is_same_namespace and self.namespace in nsprefixes:
            # This tag's namespace already has a prefix bound to it. Use
            # that prefix.
            prefix = nsprefixes[self.namespace]
            begin.extend(prefix + ':' + self.tagName)

            # Also make sure we use it for the end tag.
            endTagName = prefix + ':' + self.endTagName
        elif not is_same_namespace:
            # This tag's namespace has no prefix bound to it. Change the
            # default namespace to this tag's namespace so we don't need
            # prefixes.  Alternatively, we could add a new prefix binding.
            # I'm not sure why the code was written one way rather than the
            # other. -exarkun
            begin.extend(self.tagName)
            begin.extend(self.create_attr("xmlns", self.namespace))

            # The default namespace just changed.  Make sure any children
            # know about this.
            namespace = self.namespace
        else:
            # This tag has no namespace or its namespace is already the default
            # namespace.  Nothing extra to do here.
            begin.extend(self.tagName)

        prefixes = ('p%s' % str(i) for i in it.count())

        for attr, val in sorted(self.attributes.items()):
            if val and isinstance(attr, tuple):
                ns, key = attr

                if ns in nsprefixes:
                    prefix = nsprefixes[ns]
                else:
                    newprefixes[ns] = prefix = next(prefixes)

                begin.extend(self.create_attr(prefix + ':' + key, val))
            elif val:
                begin.extend(self.create_attr(attr, val))

        return begin, namespace, endTagName, newprefixes

    def _write_child(self, stream, newl, newindent, **kwargs):
        for child in self.childNodes:
            if self.tag_is_blockelement and self.tag_is_nice_format:
                stream.write(''.join((newl, newindent)))

            child.writexml(stream, newl=newl, newindent=newindent, **kwargs)

    def writexml(self, stream, *args, **kwargs):
        """
        Serialize this L{Element} to the given stream.

        @param stream: A file-like object to which this L{Element} will be
            written.

        @param nsprefixes: A C{dict} mapping namespace URIs as C{str} to
            prefixes as C{str}.  This defines the prefixes which are already in
            scope in the document at the point at which this L{Element} exists.
            This is essentially an implementation detail for namespace support.
            Applications should not try to use it.

        @param namespace: The namespace URI as a C{str} which is the default at
            the point in the document at which this L{Element} exists.  This is
            essentially an implementation detail for namespace support.
            Applications should not try to use it.
        """
        indent = kwargs.get('indent', '')
        addindent = kwargs.get('addindent', '')
        newl = kwargs.get('newl', '')
        strip = kwargs.get('strip', 0)
        nsprefixes = kwargs.get('nsprefixes', {})
        namespace = kwargs.get('namespace', '')

        # this should never be necessary unless people start
        # changing .tagName on the fly(?)
        if self.case_insensitive:
            self.endTagName = self.tagName

        _args = (namespace, nsprefixes, newl, indent)
        begin, namespace, endTagName, newprefixes = self._writexml(*_args)

        for ns, prefix in newprefixes.items():
            if prefix:
                begin.extend(self.create_attr('xmlns:' + prefix, ns))

        newprefixes.update(nsprefixes)
        downprefixes = newprefixes
        stream.write(''.join(begin))

        if self.childNodes:
            stream.write(">")
            newindent = indent + addindent

            kwargs = {
                'newindent': newindent,
                'addindent': addindent,
                'newl': newl,
                'strip': strip,
                'downprefixes': downprefixes,
                'namespace': namespace}

            self._write_child(stream, newl, newindent, **kwargs)

            if self.tag_is_blockelement:
                stream.write(''.join((newl, indent)))

            stream.write(''.join(('</', endTagName, '>')))
        elif not self.tag_is_singleton:
            stream.write(''.join(('></', endTagName, '>')))
        else:
            stream.write(" />")

    def __repr__(self):
        rep = "Element(%s" % repr(self.nodeName)

        if self.attributes:
            rep += ", attributes=%r" % (self.attributes,)

        if self._filename:
            rep += ", filename=%r" % (self._filename,)

        if self._markpos:
            rep += ", markpos=%r" % (self._markpos,)

        return rep + ')'

    def __str__(self):
        rep = "<" + self.nodeName

        if self._filename or self._markpos:
            rep += " ("

        if self._filename:
            rep += repr(self._filename)

        if self._markpos:
            rep += " line %s column %s" % self._markpos

        if self._filename or self._markpos:
            rep += ")"

        for item in self.attributes.items():
            rep += " %s=%r" % item

        if self.hasChildNodes():
            rep += " >...</%s>" % self.nodeName
        else:
            rep += " />"

        return rep


class MicroDOMParser(XMLParser):
    # <dash> glyph: a quick scan thru the DTD says BODY, AREA, LINK, IMG, HR,
    # P, DT, DD, LI, INPUT, OPTION, THEAD, TFOOT, TBODY, COLGROUP, COL, TR, TH,
    # TD, HEAD, BASE, META, HTML all have optional closing tags
    def_soon_closers = 'area link br img hr input base meta'.split()
    def_later_closers = {
        'p': ['p', 'dt'],
        'dt': ['dt', 'dd'],
        'dd': ['dt', 'dd'],
        'li': ['li'],
        'tbody': ['thead', 'tfoot', 'tbody'],
        'thead': ['thead', 'tfoot', 'tbody'],
        'tfoot': ['thead', 'tfoot', 'tbody'],
        'colgroup': ['colgroup'],
        'col': ['col'],
        'tr': ['tr'],
        'td': ['td'],
        'th': ['th'],
        'head': ['body'],
        'title': ['head', 'body'],  # this looks wrong...
        'option': ['option'],
    }

    def __init__(self, case_insensitive=True, **kwargs):
        # Protocol is an old style class so we can't use super
        XMLParser.__init__(self, **kwargs)
        self.elementstack = []
        d = {'xmlns': 'xmlns', '': None}
        dr = invert_dict(d)
        self.nsstack = [(d, None, dr)]
        self.documents = []
        self._mddoctype = None
        self.case_insensitive = case_insensitive
        self.preserve_case = case_insensitive
        self.soonClosers = kwargs.get('soonClosers', self.def_soon_closers)
        self.laterClosers = kwargs.get('laterClosers', self.def_later_closers)
        self.indentlevel = 0

    def shouldPreserveSpace(self):
        for idx, _ in enumerate(self.elementstack):
            el = self.elementstack[-idx]
            preserve = el.getAttribute("xml:space", '') == 'preserve'

            if (el.tagName == 'pre') or preserve:
                return 1

        return 0

    def _getparent(self):
        if self.elementstack:
            return self.elementstack[-1]
        else:
            return None

    COMMENT = re.compile(r"\s*/[/*]\s*")

    def _fixScriptElement(self, el):
        # this deals with case where there is comment or CDATA inside
        # <script> tag and we want to do the right thing with it
        if self.strict or not len(el.childNodes) == 1:
            return

        c = el.firstChild()

        if isinstance(c, Text):
            # deal with nasty people who do stuff like:
            #   <script> // <!--
            #      x = 1;
            #   // --></script>
            # tidy does this, for example.
            prefix = ""
            oldvalue = c.value
            match = self.COMMENT.match(oldvalue)

            if match:
                prefix = match.group()
                oldvalue = oldvalue[len(prefix):]

            # now see if contents are actual node and comment or CDATA
            try:
                e = parseString("<a>%s</a>" % oldvalue).childNodes[0]
            except (ParseError, MismatchedTags):
                return

            if len(e.childNodes) != 1:
                return

            e = e.firstChild()

            if isinstance(e, (CDATASection, Comment)):
                el.childNodes = [e] + ([Text(prefix)] if prefix else [])

    def gotDoctype(self, doctype):
        self._mddoctype = doctype

    def _check_parent(self, parent, name):
        if (self.lenient and isinstance(parent, Element)):
            parentName = parent.tagName
            myName = name

            if self.case_insensitive:
                parentName = parentName.lower()
                myName = myName.lower()

            if myName in self.laterClosers.get(parentName, []):
                self.gotTagEnd(parent.tagName)
                parent = self._getparent()

        return parent

    def _gen_attrs(self, attributes, namespaces):
        for k, v in attributes.items():
            ksplit = k.split(':', 1)

            if len(ksplit) == 2:
                pfx, tv = ksplit

                if pfx != 'xml' and pfx in namespaces:
                    yield ((namespaces[pfx], tv), v)
                else:
                    yield (k, v)
            else:
                yield (k, v)

    def _gen_newspaces(self, unesc_attributes):
        for k, v in unesc_attributes.items():
            if k.startswith('xmlns'):
                spacenames = k.split(':', 1)

                if len(spacenames) == 2:
                    yield (spacenames[1], v)
                else:
                    yield ('', v)

    def _gen_new_attrs(self, unesc_attributes):
        for k, v in unesc_attributes.items():
            if not k.startswith('xmlns'):
                yield (k, v)

    def gotTagStart(self, name, attributes):
        # logger.debug('%s<%s>', ' ' * self.indentlevel, name)
        self.indentlevel += 2
        parent = self._getparent()
        parent = self._check_parent(parent, name)

        unesc_attributes = unescape_dict(attributes)
        namespaces = self.nsstack[-1][0]
        newspaces = dict(self._gen_newspaces(unesc_attributes))
        new_unesc_attributes = dict(self._gen_new_attrs(unesc_attributes))
        new_namespaces = combine_dicts(namespaces, newspaces)
        gen_attr_args = (new_unesc_attributes, new_namespaces)
        new_attributes = dict(self._gen_attrs(*gen_attr_args))
        el_args = (name, new_attributes, parent, self.filename, self.saveMark())

        kwargs = {
            'case_insensitive': self.case_insensitive,
            'namespace': new_namespaces.get('')}

        el = Element(*el_args, **kwargs)
        revspaces = invert_dict(newspaces)
        el.addPrefixes(revspaces)

        if newspaces:
            rscopy = combine_dicts(self.nsstack[-1][2], revspaces)
            self.nsstack.append((new_namespaces, el, rscopy))

        self.elementstack.append(el)

        if parent:
            parent.appendChild(el)

        if (self.lenient and el.tagName in self.soonClosers):
            self.gotTagEnd(name)

    def _gotStandalone(self, factory, data):
        parent = self._getparent()
        te = factory(data, parent)

        if parent:
            parent.appendChild(te)
        elif self.lenient:
            self.documents.append(te)

    def gotText(self, data):
        if data.strip() or self.shouldPreserveSpace():
            self._gotStandalone(Text, data)

    def gotComment(self, data):
        self._gotStandalone(Comment, data)

    def gotEntityReference(self, entityRef):
        self._gotStandalone(EntityReference, entityRef)

    def gotCData(self, cdata):
        self._gotStandalone(CDATASection, cdata)

    def _check_name(self, name, el):
        pfxdix = self.nsstack[-1][2]
        nsplit = name.split(':', 1)

        if len(nsplit) == 2:
            pfx, newname = nsplit
            ns = pfxdix.get(pfx, None)

            if (el.namespace != ns) and ns and self.strict:
                first = (self.filename, el.tagName, name)
                args = first + self.saveMark() + el._markpos
                raise MismatchedTags(*args)

    def _update_stacks(self, lastEl, nstuple, el, name, cname):
        updated = False

        for idx, element in enumerate(reversed(self.elementstack)):
            if element.tagName == cname:
                element.endTag(name)
                break
        else:
            # this was a garbage close tag; wait for a real one
            self.elementstack.append(el)
            self.nsstack.append(nstuple) if nstuple else None
            updated = True

        if not updated:
            del self.elementstack[-(idx + 1):]

        if not (updated or self.elementstack):
            self.documents.append(lastEl)
            updated = True

        return updated

    def _update_el(self, updated, name, el):
        if not updated:
            el.endTag(name)

        if not (updated or self.elementstack):
            self.documents.append(el)

        if not updated and self.lenient and el.tagName == "script":
            self._fixScriptElement(el)

    def gotTagEnd(self, name):
        self.indentlevel -= 2
        # logger.debug('%s</%s>', ' ' * self.indentlevel, name)

        if self.lenient and not self.elementstack:
            return
        elif not self.elementstack:
            args = (self.filename, "NOTHING", name) + self.saveMark() + (0, 0)
            raise MismatchedTags(*args)

        el = self.elementstack.pop()
        nstuple = self.nsstack.pop() if self.nsstack[-1][1] is el else None
        tn, cname = el.tagName, name

        if self.case_insensitive:
            tn, cname = tn.lower(), cname.lower()

        self._check_name(name, el)
        tn_is_cname = tn == cname
        lenient_stack = self.lenient and self.elementstack

        if not tn_is_cname and lenient_stack:
            lastEl = self.elementstack[0]
            updated = self._update_stacks(lastEl, nstuple, el, name, cname)
        elif not tn_is_cname:
            first = (self.filename, el.tagName, name)
            raise MismatchedTags(*(first + self.saveMark() + el._markpos))
        else:
            updated = False

        self._update_el(updated, name, el)

    def connectionLost(self, reason):
        XMLParser.connectionLost(self, reason)  # This can cause more events!

        if self.elementstack:
            if self.lenient:
                self.documents.append(self.elementstack[0])
            else:
                first = (self.filename, self.elementstack[-1], "END_OF_FILE")
                args = first + self.saveMark() + self.elementstack[-1]._markpos
                raise MismatchedTags(*args)


def parse(f, *args, **kwargs):
    """Parse HTML or XML readable."""
    fp = f.fp if hasattr(f, 'fp') else f
    readable = fp if hasattr(fp, 'read') else open(f, 'rb')
    filename = getattr(readable, 'name', 'unnamed')
    mdp = MicroDOMParser(filename=filename, **kwargs)
    mdp.makeConnection(None)

    try:
        mdp.dataReceived(readable.getvalue())
    except AttributeError:
        sentinel = b'' if 'BufferedReader' in str(type(readable)) else ''
        for r in iter(partial(readable.read, 1024), sentinel):
            mdp.dataReceived(r)

    mdp.connectionLost(None)

    if not mdp.documents:
        raise ParseError(mdp.filename, 0, 0, "No top-level Nodes in document")

    d = mdp.documents[0]
    is_element = isinstance(d, Element)

    if mdp.lenient and len(mdp.documents) == 1 and not is_element:
        el = Element("html")
        el.appendChild(d)
        d = el
    elif mdp.lenient:
        d = Element("html")
        [d.appendChild(child) for child in mdp.documents]

    doc = Document(d)
    doc.doctype = mdp._mddoctype
    return doc


def parseString(content, *args, **kwargs):
    f = BytesIO(encode(content))
    return parse(f, *args, **kwargs)


def parseXML(readable):
    """Parse an XML readable object."""
    return parse(readable, case_insensitive=True)


def parseXMLString(content):
    """Parse an XML readable object."""
    return parseString(content, case_insensitive=True)
