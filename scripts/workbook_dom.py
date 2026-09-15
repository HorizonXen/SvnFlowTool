"""Low-memory OOXML DOM adapter used by the application merge engine."""
import copy
from lxml import etree as E

class Attr:
 def __init__(self,node,key):self.node=node;self.key=key
 @property
 def namespaceURI(self):return E.QName(self.key).namespace
 @property
 def localName(self):return E.QName(self.key).localname
 @property
 def name(self):
  ns=self.namespaceURI
  prefix=next((p for p,u in self.node.e.nsmap.items() if p and u==ns),None) if ns else None
  return prefix+':'+self.localName if prefix else self.localName
 @property
 def value(self):return self.node.e.attrib[self.key]
class Attributes:
 def __init__(self,node):self.node=node
 @property
 def length(self):return len(self.node.e.attrib)
 def item(self,i):return Attr(self.node,list(self.node.e.attrib)[i])
class Text:
 ELEMENT_NODE=1;TEXT_NODE=3;nodeType=3
 def __init__(self,value,parent=None):self.data=value;self.parentNode=parent
 @property
 def nodeValue(self):return self.data
 def cloneNode(self,deep):return Text(self.data)
class Node:
 ELEMENT_NODE=1;TEXT_NODE=3
 def __init__(self,e):self.e=e
 @property
 def nodeType(self):return 1 if isinstance(self.e.tag,str) else 8
 @property
 def namespaceURI(self):return E.QName(self.e).namespace if self.nodeType==1 else None
 @property
 def localName(self):return E.QName(self.e).localname if self.nodeType==1 else None
 @property
 def nodeValue(self):return None if self.nodeType==1 else self.e.text
 @property
 def attributes(self):return Attributes(self)
 @property
 def parentNode(self):return Node(self.e.getparent()) if self.e.getparent() is not None else None
 @property
 def childNodes(self):
  out=[Text(self.e.text,self)] if self.e.text else []
  for c in self.e:
   out.append(Node(c))
   if c.tail:out.append(Text(c.tail,self))
  return out
 @property
 def firstChild(self):return next(iter(self.childNodes),None)
 def key(self,name):
  if ':' in name and not name.startswith('{'):
   prefix,local=name.split(':',1);return '{'+self.e.nsmap[prefix]+'}'+local
  return name
 def getAttribute(self,name):return self.e.get(self.key(name),'')
 def getAttributeNS(self,ns,name):return self.e.get('{'+ns+'}'+name,'')
 def hasAttribute(self,name):return self.key(name) in self.e.attrib
 def setAttribute(self,name,value):self.e.set(self.key(name),str(value))
 def setAttributeNS(self,ns,name,value):self.e.set('{'+ns+'}'+name.split(':')[-1],str(value))
 def removeAttribute(self,name):self.e.attrib.pop(self.key(name),None)
 def cloneNode(self,deep):return Node(copy.deepcopy(self.e))
 def appendChild(self,node):
  if isinstance(node,Text):
   if len(self.e):self.e[-1].tail=(self.e[-1].tail or '')+node.data
   else:self.e.text=(self.e.text or '')+node.data
  else:self.e.append(node.e)
  return node
 def removeChild(self,node):
  if isinstance(node,Text):
   if self.e.text==node.data:self.e.text=None
   else:
    for c in self.e:
     if c.tail==node.data:c.tail=None;break
  else:self.e.remove(node.e)
 def replaceChild(self,new,old):self.e.replace(old.e,new.e);return old
 def insertBefore(self,node,following):
  if following is None:self.appendChild(node)
  else:self.e.insert(self.e.index(following.e),node.e)
 def getElementsByTagNameNS(self,ns,tag):return [Node(n) for n in self.e.iter('{'+ns+'}'+tag)]
 def toxml(self,encoding=None):return E.tostring(self.e,encoding=encoding or 'unicode',with_tail=False)
class Document:
 def __init__(self,e):self.e=e
 @property
 def documentElement(self):return Node(self.e)
 def createElementNS(self,ns,name):return Node(E.Element('{'+ns+'}'+name.split(':')[-1]))
 def createElement(self,name):return Node(E.Element(name))
 def createTextNode(self,value):return Text(value)
 def importNode(self,node,deep):return node.cloneNode(deep)
 def getElementsByTagNameNS(self,ns,tag):return self.documentElement.getElementsByTagNameNS(ns,tag)
 def toxml(self,encoding=None):return E.tostring(self.e,encoding=encoding or 'unicode',xml_declaration=encoding is not None)
 def unlink(self):self.e=None

def parseString(data):return Document(E.fromstring(data,parser=E.XMLParser(huge_tree=True,remove_blank_text=False,resolve_entities=False,no_network=True)))
