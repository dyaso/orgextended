import sublime
import sublime_plugin
import datetime
import re
import regex
from pathlib import Path
import os
import fnmatch
import OrgExtended.orgparse.node as node
from   OrgExtended.orgparse.sublimenode import * 
import OrgExtended.orgutil.util as util
import OrgExtended.orgutil.navigation as nav
import OrgExtended.orgutil.template as templateEngine
import logging
import sys
import traceback 
import OrgExtended.orgfolding as folding
import OrgExtended.orgdb as db
import OrgExtended.asettings as sets
import OrgExtended.orgcapture as capture
import OrgExtended.orgproperties as props
import OrgExtended.orgutil.temp as tf
import OrgExtended.pymitter as evt
import OrgExtended.orgnotifications as notice
import OrgExtended.orgextension as ext
import OrgExtended.orgsourceblock as src
import OrgExtended.orgexporter as exp
import OrgExtended.orgplist as plist
import yaml
import sys
import subprocess
import html

log = logging.getLogger(__name__)

langMap = {
    "cpp": "C++",
    "python": "Python",
    "C": "C",
    "perl": "Perl",
    "bash": "bash",
    "sh": "sh",
    "lua": "[5.0]Lua",
    "java": "Java",
    "php": "PHP",
    "xml": "XML",
    "lisp": "Lisp",
    "sql": "SQL",
    "r": "R",
    "html": "HTML",
    "go": "Go",
    "make": "make",
    "pascal": "Pascal",
    "ruby": "Ruby",
    "xsl": "XSLT",
    "scala": "Scala",
    "erlang": "erlang",
    "gnuplot": "Gnuplot",
}

# overriding it by users settings
langMap.update(sets.Get("latexListingPackageLang",langMap))

def haveLang(lang):
    return lang in langMap

def mapLanguage(lang):
    if(lang in langMap):
        return langMap[lang]
    return lang

RE_ATTR = regex.compile(r"^\s*[#][+]ATTR_HTML[:](?P<params>\s+[:](?P<name>[a-zA-Z0-9._-]+)\s+(?P<value>([^:]|((?<! )[:]))+))+$")
RE_ATTR_ORG = regex.compile(r"^\s*[#][+]ATTR_ORG[:] ")
RE_LINK = re.compile(r"\[\[(?P<link>[^\]]+)\](\[(?P<desc>[^\]]+)\])?\]")
RE_UL   = re.compile(r"^(?P<indent>\s*)(-|[+])\s+(?P<data>.+)")
RE_FN_MATCH = re.compile(r"\s*[:]([a-zA-Z0-9-_]+)\s+([^: ]+)?\s*")
RE_STARTSRC = re.compile(r"^\s*#\+(BEGIN_SRC|begin_src)\s+(?P<lang>[a-zA-Z0-9]+)")
RE_STARTDYN = re.compile(r"^\s*#\+(BEGIN:|begin:)\s+(?P<lang>[a-zA-Z0-9]+)")
RE_ENDSRC = re.compile(r"^\s*#\+(END_SRC|end_src)")
RE_ENDDYN = re.compile(r"^\s*#\+(end:|END:)")
RE_RESULTS = re.compile(r"^\s*#\+RESULTS.*")
RE_TABLE_SEPARATOR = re.compile(r"^\s*[|][-]")
RE_CHECKBOX         = re.compile(r"^\[ \] ")
RE_CHECKED_CHECKBOX = re.compile(r"^\[[xX]\] ")
RE_PARTIAL_CHECKBOX = re.compile(r"^\[[-]\] ")
RE_EMPTY_LINE = re.compile(r"^\s*$")


# <!-- multiple_stores height="50%" width="50%" --> 
RE_COMMENT_TAG = re.compile(r"^\s*[<][!][-][-]\s+(?P<name>[a-zA-Z0-9_-]+)\s+(?P<props>.*)\s+[-][-][>]")

#\documentclass{article}
# PREAMBLE
#\begin{document}
#Hello, \LaTeX\ world.
#\end{document}

sectionTypes = [
r"\chapter{{{heading}}}",
r"\section{{{heading}}}",
r"\subsection{{{heading}}}",
r"\subsubsection{{{heading}}}",
r"\paragraph{{{heading}}}",
r"\subparagraph{{{heading}}}"
]


class LatexSourceBlockState(exp.SourceBlockState):
    def __init__(self,doc):
        super(LatexSourceBlockState,self).__init__(doc)
        self.skipSrc = False

    def HandleOptions(self):
        attr = self.e.GetAttrib("attr_latex")
        optionsOp = ""
        floatOp = None
        if(attr):
            p = plist.PList.createPList(attr)
        else:
            p = plist.PList.createPList("")
        ops = p.Get("options",None)
        if(ops):
            optionsOp = ops
        caption = self.e.GetAttrib("caption")
        cc = p.Get("caption",None)
        if(cc):
            caption = cc
        floatOp = GetOption(p,"float",None)
        if(caption and not floatOp):
            floatOp = "t"
        if(floatOp and floatOp != "nil"):
            if(floatOp == "multicolumn"):
                figure = "figure*"
            elif(floatOp == "sideways"):
                figure = "sidewaysfigure" 
            elif(floatOp == "wrap"):
                figure = "wrapfigure"
                figureext = "{l}"
        if(optionsOp.strip() != ""):
            optionsOp = "[" + optionsOp + "]"
        # There is a discrepancy between orgmode docs and
        # actual emacs export.. I need to figure this out so
        # nuke it for now till I understand it
        optionsOp = ""
        return (optionsOp,floatOp,caption)

    def HandleEntering(self, m, l, orgnode):
        self.skipSrc = False
        language = m.group('lang')
        paramstr = l[len(m.group(0)):]
        p = type('', (), {})() 
        src.BuildFullParamList(p,language,paramstr,orgnode)
        exp = p.params.Get("exports",None)
        # Have to pass on parameter to the results block
        self.e.sparams = p
        if(isinstance(exp,list) and len(exp) > 0):
            exp = exp[0]
        if(exp == 'results' or exp == 'none'):
            self.skipSrc = True
            return
        # Some languages we skip source by default
        skipLangs = sets.Get("latexDefaultSkipSrc",[])
        if(exp == None and language == skipLangs):
            self.skipSrc = True
            return
        attribs = ""
        self.options, self.float, self.caption = self.HandleOptions()
        self.e.doc.append(r"  \begin{center}")
        self.e.doc.append(r"  \centering")
        if(haveLang(language)):
            self.e.doc.append(r"  \begin{options}{{lstlisting}}[language={{{lang}}}]".format(options=self.options,lang=mapLanguage(language)))
        else:
            self.e.doc.append(r"  \begin{options}{{lstlisting}}".format(options=self.options))

    def HandleExiting(self, m, l , orgnode):
        if(not self.skipSrc):
            self.e.doc.append(r"  \end{lstlisting}")
            self.e.doc.append(r"  \end{center}")
        skipSrc = False

    def HandleIn(self,l, orgnode):
        if(not self.skipSrc):
            self.e.doc.append(l)

# Skips over contents not intended for a latex buffer
class LatexExportBlockState(exp.ExportBlockState):
    def __init__(self,doc):
        super(LatexExportBlockState,self).__init__(doc)
        self.skipExport = False

    def HandleEntering(self, m, l, orgnode):
        self.skipExport = False
        language = m.group('lang').strip().lower()
        if(language != "latex"):
            self.skipExport = True
            return
        # We will probably need this in the future.
        #paramstr = l[len(m.group(0)):]
        #p = type('', (), {})() 
        #src.BuildFullParamList(p,language,paramstr,orgnode)

    def HandleExiting(self, m, l , orgnode):
        self.skipExport = False

    def HandleIn(self,l, orgnode):
        if(not self.skipExport):
            self.e.doc.append(l)


class LatexDynamicBlockState(exp.DynamicBlockState):
    def __init__(self,doc):
        super(LatexDynamicBlockState,self).__init__(doc)
        self.skip = False
    def HandleEntering(self,m,l,orgnode):
        self.skip = False
        language = m.group('lang')
        paramstr = l[len(m.group(0)):]
        p = type('', (), {})() 
        src.BuildFullParamList(p,language,paramstr,orgnode)
        exp = p.params.Get("exports",None)
        if(isinstance(exp,list) and len(exp) > 0):
            exp = exp[0]
        if(exp == 'results' or exp == 'none'):
            self.skip = True
            return
        self.e.doc.append(r"  \begin{verbatim}")
    def HandleExiting(self, m, l , orgnode):
        if(not self.skip):
            self.e.doc.append(r"  \end{verbatim}")
        self.skip = False
    def HandleIn(self,l, orgnode):
        if(not self.skip):
            self.e.doc.append(l)

class LatexQuoteBlockState(exp.QuoteBlockState):
    def __init__(self,doc):
        super(LatexQuoteBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.e.doc.append(r"  \begin{displayquote}")
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"  \end{displayquote}")
    def HandleIn(self,l, orgnode):
        self.e.doc.append(l)

class LatexExampleBlockState(exp.ExampleBlockState):
    def __init__(self,doc):
        super(LatexExampleBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.e.doc.append(r"  \begin{verbatim}")
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"  \end{verbatim}")
    def HandleIn(self,l, orgnode):
        self.e.doc.append(l)

class LatexGenericBlockState(exp.GenericBlockState):
    def __init__(self,doc):
        super(LatexGenericBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.data = m.group('data').strip().lower()
        self.e.doc.append(r"  \begin{{{data}}}".format(data=self.data))
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"  \end{{{data}}}".format(data=self.data))
    def HandleIn(self,l, orgnode):
        self.e.doc.append(l)


class LatexUnorderedListBlockState(exp.UnorderedListBlockState):
    def __init__(self,doc):
        super(LatexUnorderedListBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.e.doc.append(r"    \begin{itemize}")
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"     \end{itemize}")
    def StartHandleItem(self,m,l, orgnode):
        #data = self.e.Escape(m.group('data'))
        #self.e.doc.append(r"     \item {content}".format(content=data))
        definit = m.group('definition')
        if(definit):
            self.e.doc.append(r"     \item``{definition}'' ".format(definition=definit))
        else:
            self.e.doc.append(r"     \item ")


class LatexOrderedListBlockState(exp.OrderedListBlockState):
    def __init__(self,doc):
        super(LatexOrderedListBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.e.doc.append(r"    \begin{enumerate}")
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"     \end{enumerate}")
    def StartHandleItem(self,m,l, orgnode):
        #data = self.e.Escape(m.group('data'))
        #self.e.doc.append(r"     \item {content}".format(content=data))
        definit = m.group('definition')
        if(definit):
            self.e.doc.append(r"     \item``{definition}'' ".format(definition=definit))
        else:
            self.e.doc.append(r"     \item ")

class LatexCheckboxListBlockState(exp.CheckboxListBlockState):
    def __init__(self,doc):
        super(LatexCheckboxListBlockState,self).__init__(doc)
    def HandleEntering(self,m,l,orgnode):
        self.e.doc.append(r"    \begin{todolist}")
    def HandleExiting(self, m, l , orgnode):
        self.e.doc.append(r"     \end{todolist}")
    def StartHandleItem(self,m,l, orgnode):
        #data = self.e.Escape(m.group('data'))
        state = m.group('state')
        if(state == 'x'):
            self.e.doc.append(r"     \item[\wontfix] ")
        elif(state == '-'):
            self.e.doc.append(r"     \item ")
            #self.e.doc.append(r"     \item[\inp] {content}".format(content=data))
        else:
            self.e.doc.append(r"     \item ")
        #if(state == 'x'):
        #    self.e.doc.append(r"     \item[\wontfix] {content}".format(content=data))
        #elif(state == '-'):
        #    self.e.doc.append(r"     \item {content}".format(content=data))
        #    #self.e.doc.append(r"     \item[\inp] {content}".format(content=data))
        #else:
        #    self.e.doc.append(r"     \item {content}".format(content=data))

class LatexTableBlockState(exp.TableBlockState):
    def __init__(self,doc):
        super(LatexTableBlockState,self).__init__(doc)
        self.tablecnt = 1
    def HandleEntering(self,m,l,orgnode):
        attr = self.e.GetAttrib("attr_latex")
        floatOp = None
        align  = "center"
        self.modeDelimeterStart = ""
        self.modeDelimeterEnd   = ""
        self.environment = "tabular"
        self.figure = "center"
        figureext = ""
        if(attr):
            p = plist.PList.createPList(attr)
        else:
            p = plist.PList.createPList("")
        caption = self.e.GetAttrib("caption")
        cc = p.Get("caption",None)
        if(cc):
            caption = cc
        self.environment = GetOption(p,"environment",self.environment)
        mode = GetOption(p,"mode",None)
        if(mode == "math"):
            self.modeDelimeterStart = r"\["
            self.modeDelimeterEnd   = r"\]"
        if(mode == "inline-math"):
            self.modeDelimeterStart = r"\("
            self.modeDelimeterEnd   = r"\)"
        val = p.Get("center",None)
        if(val and val == "nil"):
            align = None
        floatOp = GetOption(p,"float",None)
        if(caption and not floatOp):
            floatOp = "t"
        if(floatOp and floatOp != "nil"):
            if(floatOp):
                self.figure = "table"
                figureext = "[!htp]"
            if(floatOp == "multicolumn"):
                self.figure = "table*"
            elif(floatOp == "sideways"):
                self.figure = "sidewaysfigure" 
            elif(floatOp == "wrap"):
                self.figure = "wrapfigure"
                figureext = "{l}"
            placement = p.Get("placement",None)
            if(placement):
                figureext = placement
        tabledef = ""
        tds = None
        if(not RE_TABLE_SEPARATOR.search(l)):
            tds = l.split('|')
            if(len(tds) > 1):
                if(mode == "math"):
                    tabledef = ""
                else:
                    tabledef = "{" + ("|c" * (len(tds)-2)) + "|}" 
        self.e.doc.append(r"    \begin{{{figure}}}{figureext}".format(figure=self.figure,figureext=figureext))
        if(caption):
            self.e.doc.append(r"    \caption{{{caption}}}".format(caption=self.e.GetAttrib('caption')))
            #self.fs.write("    <caption class=\"t-above\"><span class=\"table-number\">Table {index}:</span>{caption}</caption>".format(index=self.tableIndex,caption=self.caption))
            #self.tableIndex += 1
        if(align == "center" and self.environment == 'tabular'):
            self.e.doc.append(r"    \centering\renewcommand{\arraystretch}{1.2}")
        self.e.doc.append(self.modeDelimeterStart)
        self.e.doc.append(r"    \begin{{{environment}}}{tabledef}".format(tabledef=tabledef,environment=self.environment))
        self.e.ClearAttrib()
        if(self.environment == 'tabular'):
            self.e.doc.append(r"    \hline") 
        if(tds):
            self.HandleData(tds,True)
    def HandleExiting(self, m, l , orgnode):
        if(self.environment == 'tabular'):
            self.e.doc.append(r"    \hline") 
        self.e.doc.append(r"    \end{{{environment}}}".format(environment=self.environment))
        self.e.doc.append(self.modeDelimeterEnd)
        self.e.doc.append(r"    \label{{table:{cnt}}}".format(cnt=self.tablecnt))
        self.e.doc.append(r"    \end{{{figure}}}".format(figure=self.figure))
        self.tablecnt += 1

    def HandleData(self,tds,head=False): 
        if(len(tds) > 3):
            # An actual table row, build a row
            first = True
            line = "    "
            for td in tds[1:-1]:
                if(not first):
                    line += " & "
                first = False
                if(head and self.environment == 'tabular'):
                    line += r"\textbf{{{data}}}".format(data=self.e.Escape(td))
                else:
                    line += self.e.Escape(td)
            line += " \\\\"
            self.e.doc.append(line)
            haveTableHeader = True

    def HandleIn(self,l, orgnode):
        if(RE_TABLE_SEPARATOR.search(l)):
            self.e.doc.append(r'    \hline')
        else:
            tds = l.split('|')
            self.HandleData(tds)

class LatexHrParser(exp.HrParser):
    def __init__(self,doc):
        super(LatexHrParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.doc.append(r"\newline\noindent\rule{\textwidth}{0.5pt}")

class LatexNameParser(exp.NameParser):
    def __init__(self,doc):
        super(LatexNameParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.doc.append(r"\label{{{data}}}".format(data=m.group('data')))


class LatexMathParser(exp.MathParser):
    def __init__(self,doc):
        super(LatexMathParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(r"\({data}\)".format(data=m.group('data')))

class LatexInlineMathParser(exp.InlineMathParser):
    def __init__(self,doc):
        super(LatexInlineMathParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(r"\({data}\)".format(data=m.group('data')))

class LatexEqMathParser(exp.EqMathParser):
    def __init__(self,doc):
        super(LatexEqMathParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(r"\[{data}\]".format(data=m.group('data')))

class LatexEmptyParser(exp.EmptyParser):
    def __init__(self,doc):
        super(LatexEmptyParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.doc.append(r"\leavevmode\newline")

class LatexActiveDateParser(exp.EmptyParser):
    def __init__(self,doc):
        super(LatexActiveDateParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.doc.append(r"\textit{{{date}}}".format(date=m.group()))

class LatexBoldParser(exp.BoldParser):
    def __init__(self,doc):
        super(LatexBoldParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\textbf{\g<data>}",m.group()))

class LatexItalicsParser(exp.ItalicsParser):
    def __init__(self,doc):
        super(LatexItalicsParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\textit{\g<data>}",m.group()))

class LatexUnderlineParser(exp.UnderlineParser):
    def __init__(self,doc):
        super(LatexUnderlineParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\underline{\g<data>}",m.group()))

class LatexStrikethroughParser(exp.StrikethroughParser):
    def __init__(self,doc):
        super(LatexStrikethroughParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\sout{\g<data>}",m.group()))

class LatexCodeParser(exp.CodeParser):
    def __init__(self,doc):
        super(LatexCodeParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\texttt{\g<data>}",m.group()))

class LatexVerbatimParser(exp.VerbatimParser):
    def __init__(self,doc):
        super(LatexVerbatimParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(self.sre.sub(r"\\texttt{\g<data>}",m.group()))

RE_LATEXKEYWORD = regex.compile(r"^\s*\\newline\s*$")
class LatexKeywordParser(exp.SubLineParser):
    def __init__(self,doc):
        super(LatexKeywordParser,self).__init__(RE_LATEXKEYWORD,doc)
    def HandleSegment(self,m,l,orgnode):
        self.e.doc.append(m.group().strip())

def FindImageFile(view, url):
    # ABS
    if(os.path.isabs(url)):
        return url
    # Relative
    if(view != None):
        curDir = os.path.dirname(view.file_name())
        filename = os.path.join(curDir, url)
        if(os.path.isfile(filename)):
            return filename
    # In search path
    searchHere = sets.Get("imageSearchPath",[])
    for direc in searchHere:
        filename = os.path.join(direc, url)
        if(os.path.isfile(filename)):
            return filename
    searchHere = sets.Get("orgDirs",[])
    for direc in searchHere:
        filename = os.path.join(direc, "images", url) 
        if(os.path.isfile(filename)):
            return filename

def IsImageFile(fn):
    # Todo make this configurable
    if(fn.endswith(".gif") or fn.endswith(".png") or fn.endswith(".jpg") or fn.endswith(".svg")):
        return True
    return False

def AddOption(p,name,ops):
    val = p.Get(name,None)
    if(val):
        if(ops != ""):
            ops += ","
        ops += name + "=" + val.strip() 
    return ops

def GetOption(p,name,ops):
    val = p.Get(name,None)
    if(val):
        return val.strip()
    return ops

# Simple links are easy. The hard part is images, includes and results
class LatexLinkParser(exp.LinkParser):
    def __init__(self,doc):
        super(LatexLinkParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        link = m.group('link').strip()
        desc = m.group('desc')
        if(desc):
            desc = self.e.Escape(desc.strip())
        if(link.startswith("file:")):
            link = re.sub(r'^file:','',link)
        view = sublime.active_window().active_view()
        imgFile = FindImageFile(view,link)
        if(imgFile and os.path.isfile(imgFile) and IsImageFile(imgFile)):
            relPath = view.MakeRelativeToMe(imgFile)
            imagePath = os.path.dirname(relPath)
            imageToken = os.path.splitext(os.path.basename(relPath))[0]
            # The figures let this float around to much. I can't control the positioning with
            # that. Also the scale is crazy at 1.0. So I auto scale to .5? Probably not the best choice.
            # Attributes will solve this at some point.
            attr = self.e.GetAttrib("attr_latex")
            optionsOp = ""
            floatOp = None
            figure = "figure"
            align  = "center"
            figureext = ""
            if(attr):
                p = plist.PList.createPList(attr)
            else:
                p = plist.PList.createPList("")
            ops = p.Get("options",None)
            if(ops):
                optionsOp = ops
            caption = self.e.GetAttrib("caption")
            cc = p.Get("caption",None)
            if(cc):
                caption = cc
            optionsOp = AddOption(p,"width",optionsOp)
            optionsOp = AddOption(p,"height",optionsOp)
            optionsOp = AddOption(p,"scale",optionsOp)
            val = p.Get("center",None)
            if(val and val == "nil"):
                align = None
            if(optionsOp == ""):
                optionsOp = r"width=.8\linewidth"
            if(caption and not floatOp):
                floatOp = "t"
            if(floatOp and floatOp != "nil"):
                if(floatOp == "multicolumn"):
                    figure = "figure*"
                elif(floatOp == "sideways"):
                    figure = "sidewaysfigure" 
                elif(floatOp == "wrap"):
                    figure = "wrapfigure"
                    figureext = "{l}"
                placement = p.Get("placement",None)
                if(placement):
                    figureext = placement
                self.e.doc.append(r"\begin{{{figure}}}{figureext}".format(figure=figure,figureext=figureext))
                if(align == "center"):
                    self.e.doc.append(r"\centering")
            self.e.doc.append(r"\includegraphics[{options}]{{{name}}}".format(name=imageToken,options=optionsOp))
            if(caption):
                self.e.doc.append(r"\caption{{{caption}}}".format(caption=caption))
            if(floatOp and floatOp != "nil"):
                self.e.doc.append(r"\end{{{figure}}}".format(figure=figure))
            if(not imagePath in self.e.imagepaths):
                self.e.imagepaths.append(imagePath)
        else:
            if(link.startswith("http")):
                if(desc):
                    self.e.doc.append(r"\href{{{link}}}{{{desc}}}".format(link=link,desc=desc))
                else:
                    self.e.doc.append(r"\url{{{link}}}".format(link=link))
            elif("/" not in link and "\\" not in link and "." not in link):
                if(desc):
                    self.e.doc.append(r"\hyperref[{link}]{{{desc}}}".format(link=link,desc=desc))
                else:
                    self.e.doc.append(r"\hyperref[{link}]{{{desc}}}".format(link=link,desc=self.e.Escape(link)))
            else:
                link = re.sub(r"[:][:][^/].*","",link)
                link = link.replace("\\","/")
                text = m.group()
                if(desc):
                    self.e.doc.append(r"\href{{{link}}}{{{desc}}}".format(link=link,desc=desc))
                else:
                    self.e.doc.append(r"\url{{{link}}}".format(link=link))
        self.e.ClearAttrib()

# <<TARGET>>
class LatexTargetParser(exp.TargetParser):
    def __init__(self,doc):
        super(LatexTargetParser,self).__init__(doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(r"\label{{{data}}}".format(data=m.group('data')))

class LatexLatexHeaderParser(exp.LatexHeaderParser):
    def __init__(self,doc):
        super(LatexLatexHeaderParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.pre.append(m.group('data').strip())

class LatexLatexClassOptionsParser(exp.LatexClassOptionsParser):
    def __init__(self,doc):
        super(LatexLatexClassOptionsParser,self).__init__(doc)
    def HandleLine(self,m,l,n):
        self.e.documentclass += m.group('data').strip()

# Outputs latex verbatim but in a line
RE_LATEX_SUBLATEX = regex.compile(r"[@][@](?P<data>.*)[@][@]")
class LatexLatexSubLatexParser(exp.SubLineParser):
    def __init__(self,doc):
        super(LatexLatexSubLatexParser,self).__init__(RE_LATEX_SUBLATEX, doc)
    def HandleSegment(self,m,l,n):
        self.e.doc.append(m.group('data').strip())

# Line of latex gets emitted
RE_LATEX_LATEX = regex.compile(r"^\s*[#][+]LATEX[:]\s*(?P<data>.*)")
class LatexLatexLatexParser(exp.LineParser):
    def __init__(self,doc):
        super(LatexLatexLatexParser,self).__init__(RE_LATEX_LATEX, doc)
    def HandleLine(self,m,l,n):
        self.e.doc.append(m.group('data').strip())

RE_ATTR_LATEX = regex.compile(r"^\s*[#][+]ATTR_LATEX[:]\s*(?P<data>.*)")
class LatexAttributeParser(exp.AttributeParser):
    def __init__(self,doc):
        super(LatexAttributeParser,self).__init__('attr_latex',RE_ATTR_LATEX,doc)

class LatexDoc(exp.OrgExporter):
    def __init__(self,filename,file,**kwargs):
        super(LatexDoc, self).__init__(filename, file, **kwargs)
        self.file = file
        self.sparams = None
        self.documentclass = r'\documentclass{article}'
        self.imagepaths = []
        self.pre      = []
        self.doc      = []
        self.attribs  = {}
        self.amInBlock = False
        # TODO: Make this configurable
        self.pre.append(r"\usepackage[utf8]{inputenc}")
        self.pre.append(r"\usepackage{listings}")
        self.pre.append(r"\usepackage{hyperref}")
        self.pre.append(r"\usepackage{csquotes}")
        self.pre.append(r"\usepackage{makecell, caption}")
        self.pre.append(r"\usepackage[T1]{fontenc}")
        self.pre.append(r"\usepackage[greek,english]{babel}")
        self.pre.append(r"\usepackage{CJKutf8}")
        self.pre.append(r"\usepackage{graphicx}")
        self.pre.append(r"\usepackage{grffile}")
        self.pre.append(r"\usepackage{longtable}")
        self.pre.append(r"\usepackage{wrapfig}")
        self.pre.append(r"\usepackage{rotating}")
        self.pre.append(r"\usepackage{textcomp}")
        self.pre.append(r"\usepackage{capt-of}")
        self.pre.append(r"\usepackage{amsmath}")
        self.pre.append(r"\usepackage{amssymb}")
        # Needed for strikethrough
        self.pre.append(r"\usepackage[normalem]{ulem}")
        # Checkbox Setup
        self.pre.append(r"\usepackage{enumitem,amssymb}")
        self.pre.append(r"\newlist{todolist}{itemize}{2}")
        self.pre.append(r"\setlist[todolist]{label=$\square$}")
        self.pre.append(r"\usepackage{pifont}")
        self.pre.append(r"\newcommand{\cmark}{\ding{51}}%")
        self.pre.append(r"\newcommand{\xmark}{\ding{55}}%")
        self.pre.append(r"\newcommand{\tridot}{\ding{213}}%")
        self.pre.append(r"\newcommand{\inp}{\rlap{$\square$}{\large\hspace{1pt}\tridot}}")
        self.pre.append(r"\newcommand{\done}{\rlap{$\square$}{\raisebox{2pt}{\large\hspace{1pt}\cmark}}%")
        self.pre.append(r"\hspace{-2.5pt}}")
        self.pre.append(r"\newcommand{\wontfix}{\rlap{$\square$}{\large\hspace{1pt}\xmark}}")
        #self.pre.append(r"\usepackage{flafter}") 
        self.nodeParsers = [
        exp.SetupFileParser(self),
        exp.CaptionAttributeParser(self),
        LatexAttributeParser(self),
        exp.ResultsParser(self),
        LatexTableBlockState(self),
        LatexSourceBlockState(self),
        LatexDynamicBlockState(self),
        LatexQuoteBlockState(self),
        LatexExampleBlockState(self),
        LatexCheckboxListBlockState(self),
        LatexUnorderedListBlockState(self),
        LatexOrderedListBlockState(self),
        LatexExportBlockState(self),
        LatexGenericBlockState(self),
        exp.DrawerBlockState(self),
        exp.SchedulingStripper(self),
        exp.TblFmStripper(self),
        exp.AttrHtmlStripper(self),
        exp.AttrOrgStripper(self),
        exp.KeywordStripper(self),
        LatexEmptyParser(self),
        LatexLinkParser(self),
        LatexHrParser(self),
        LatexNameParser(self),
        LatexLatexHeaderParser(self),
        LatexLatexClassOptionsParser(self),
        LatexLatexLatexParser(self),
        LatexActiveDateParser(self),
        LatexMathParser(self),
        LatexLatexSubLatexParser(self),
        LatexInlineMathParser(self),
        LatexEqMathParser(self),
        LatexBoldParser(self),
        LatexItalicsParser(self),
        LatexUnderlineParser(self),
        LatexStrikethroughParser(self),
        LatexCodeParser(self),
        LatexVerbatimParser(self),
        LatexKeywordParser(self),
        LatexTargetParser(self)
        ]

    def SetAmInBlock(self,inBlock):
        self.amInBlock = inBlock

    def AmInBlock(self):
        return self.amInBlock

    def AddAttrib(self,name,val):
        self.attribs[name] = val.strip()
    
    def GetAttrib(self,name):
        if(name in self.attribs):
            return self.attribs[name]
        return None

    def ClearAttrib(self):
        self.attribs.clear()

    def setClass(self,className):
        self.documentclass = r'\documentclass{{{docclass}}}'.format(docclass=className)

    def BuildDoc(self):
        imagepaths = ""
        if(len(self.imagepaths) > 0):
            imagepaths = r"\graphicspath{"
            for i in self.imagepaths:
                item = i.replace("\\","/").strip()
                if(not item.endswith("/")):
                    item += "/"
                if(not item.startswith(".")):
                    item = "./" + item
                imagepaths += "{" + item + "}"
            imagepaths += "}"
        toc = [r"\maketitle",r"\tableofcontents"]
        # Use our options to control the title and toc
        ops = self.file.org.get_comment("OPTIONS",None)
        if(ops):
            ops = " ".join(ops)
            ops = ops.strip().split(" ")
            if("toc:nil" in ops):
                toc.remove(r"\tableofcontents")
            if("title:nil" in ops):
                toc.remove(r"\maketitle")
            if("author:nil" in ops):
                for l in self.pre:
                    if(l.startswith("\\author")):
                        self.pre.remove(l)
                        break
            if("date:nil" in ops):
                for l in self.pre:
                    if(l.startswith("\\date")):
                        self.pre.remove(l)
                        break
                self.pre.append("\\date{}")
            for t in ops:
                if(t.startswith("toc:")):
                    v = t.split(":")[1].strip()
                    try:
                        v = int(v)
                        if(v > 0):
                            toc.insert(0,"\\setcounter{{tocdepth}}{{{num}}}".format(num=v))
                    except:
                        pass
        out = self.documentclass + '\n' + '\n'.join(self.pre) + '\n'+ imagepaths +"\n" +  r'\begin{document}' + '\n' + "\n".join(toc) + '\n' + '\n'.join(self.doc) + '\n' + r'\end{document}' + '\n'
        return out

    # Document header metadata should go in here
    def AddExportMetaCustom(self):
        if(self.author):
            self.pre.append(r"\author{{{data}}}".format(data=self.author))
        if(self.title):
            self.pre.append(r"\title{{{data}}}".format(data=self.title))
        if(self.date):
            self.pre.append(r"\date{{{data}}}".format(data=self.date))
        pass

    # Setup to start the export of a node
    def StartNode(self, n):
        pass 

    def Escape(self,str):
        str,cnt = self.SingleLineReplacements(str)
        if(0 == cnt):
            return self.TexFullEscape(str)
        elif(1 == cnt):
            return self.TexCommandEscape(str)
        else:
            return str

    def TexFullEscape(self,text):
        conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        '\\': r'\textbackslash{}',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
        }



        cleanre = re.compile(r'([^\\])(\%|\&|\$|\#|\_|\{|\}|\~|\^|\\|\>|\<)')
        #print("AAA: " + '|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key = lambda item: - len(item))))

        #cleanre = re.compile('(.)(' + '|'.join(re.escape(str(key)) for key in sorted(conv.keys(), key = lambda item: - len(item))) + ")")
        result = cleanre.sub(lambda match: (match.group(1) if match.group(1) else "") + conv[match.group(2)] if (match.group(1) and match.group(1) != "\\") else match.group(), text)        
        return result

    
    def TexCommandEscape(self,text):
        conv = {
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '_': r'\_',
        '~': r'\textasciitilde{}',
        '^': r'\^{}',
        '<': r'\textless{}',
        '>': r'\textgreater{}',
        }
        cleanre = re.compile(r'([^\\])(\%|\&|\$|\#|\_|\~|\^|\>|\<)')
        result = cleanre.sub(lambda match: (match.group(1) if match.group(1) else "") + conv[match.group(2)] if (match.group(1) and match.group(1) != "\\") else match.group(), text)        
        return result
        #return cleanre.sub(lambda match: conv[match.group()], text)        

    def SingleLineReplace(self,reg,rep,text,ok):
        nt = reg.sub(rep,text)
        ok = ok or nt != text
        return (nt,ok)

    def SingleLineReplacements(self,text):
        didRep = 0
        text = exp.RE_TITLE.sub("",text)
        text = exp.RE_AUTHOR.sub("",text)
        text = exp.RE_LANGUAGE.sub("",text)
        text = exp.RE_EMAIL.sub("",text)
        text = exp.RE_DATE.sub("",text)
        m = RE_LINK.search(text)
        if(m):
            link = m.group('link').strip()
            desc = m.group('desc')
            if(desc):
                desc = self.TexFullEscape(desc.strip())
            if(False and (link.endswith(".png") or link.endswith(".jpg") or link.endswith(".jpeg") or link.endswith(".gif"))):
                if(link.startswith("file:")):
                    link = re.sub(r'^file:','',link)  
                extradata = ""  
                if(self.commentName and self.commentName in link):
                    extradata =  " " + self.commentData
                    self.commentName = None
                if(hasattr(self,'attrs')):
                    for key in self.attrs:
                        extradata += " " + str(key) + "=\"" + str(self.attrs[key]) + "\""
                preamble = ""
                postamble = ""
                if(hasattr(self,'caption') and self.caption):
                    pass
                    #preamble = "<div class=\"figure\"><p>"
                    #postamble = "</p><p><span class=\"figure-number\">Figure {index}: </span>{caption}</p></div>".format(index=self.figureIndex,caption=self.caption)
                    self.figureIndex += 1
                #text = RE_LINK.sub("{preamble}<img src=\"{link}\" alt=\"{desc}\"{extradata}>{postamble}".format(preamble=preamble,link=link,desc=desc,extradata=extradata,postamble=postamble),line)
                didRep = True
                #self.ClearAttributes()
                return (text,2)
            else:
                if(link.startswith("file:")):
                    link = re.sub(r'^file:','',link)  
                link = re.sub(r"[:][:][^/].*","",link)
                #link = self.TexFullEscape(link)
                link = link.replace("\\","/")
                if(desc):
                    traceback.print_stack()
                    text = RE_LINK.sub(r"\\ref{{{link}}}{{{desc}}}".format(link=link,desc=desc),text)
                else:
                    text = RE_LINK.sub(r"\\ref{{{link}}}".format(link=link),text)
                didRep = 2
                #self.ClearAttributes()
                return (text,2)

        text,didRep = self.SingleLineReplace(exp.RE_NAME,r"\label{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_BOLD,r"\\textbf{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_ITALICS,r"\\textit{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_UNDERLINE,r"\underline{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_CODE,r"\\texttt{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_VERBATIM,r"\\texttt{\g<data>}",text,didRep)
        text,didRep = self.SingleLineReplace(exp.RE_HR,r"\hrulefill",text,didRep)
        return (text,1 if didRep else 0)

    # Export the heading of this node
    def NodeHeading(self,n):
        heading = self.Escape(n.heading)
        level = n.level
        if(level >= len(sectionTypes)):
            level = len(sectionTypes)-1
        self.doc.append(sectionTypes[level].format(heading=heading))

    # We are about to start exporting the nodes body
    def StartNodeBody(self,n):
        pass

    def AttributesGather(self, l):
        return False


    def NodeBody(self,n):
        ilines = n._lines[1:]
        for parser in self.nodeParsers:
            ilines = parser.Handle(ilines,n)
        for line in ilines:
            self.doc.append(self.TexFullEscape(line))

    # We are done exporting the nodes body so finish it off
    def EndNodeBody(self,n):
        pass

    # We are now done the node itself so finish that off
    def EndNode(self,n):
        pass

    # def about to start exporting nodes
    def StartNodes(self):
        pass

    # done exporting nodes
    def EndNodes(self):
        pass

    def StartDocument(self, file):
        pass

    def EndDocument(self):
        pass

    def InsertScripts(self,file):
        pass

    def StartHead(self):
        pass

    def EndHead(self):
        pass

    def StartBody(self):
        pass

    def EndBody(self):
        pass

    def FinishDocCustom(self):
        self.fs.write(self.BuildDoc())

    def Execute(self):
        cmdStr = sets.Get("latex2Pdf","C:\\texlive\\2021\\bin\\win32\\pdflatex.exe")
        commandLine = [cmdStr, self.outputFilename]
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        except:
            startupinfo = None
        # cwd=working_dir, env=my_env,
        #cwd = os.path.join(sublime.packages_path(),"User") 
        view = sublime.active_window().active_view()
        cwd = os.path.dirname(view.file_name())
        popen = subprocess.Popen(commandLine, universal_newlines=True, cwd=cwd, startupinfo=startupinfo, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        #popen.wait()
        (o,e) = popen.communicate()
        log.debug(o)
        log.debug(e)
        #log.debug(o.split('\n') + e.split('\n'))

# ============================================================
class OrgExportFileAsPdfCommand(sublime_plugin.TextCommand):

    def OnDoneSourceBlockExecution(self):
        # Reload if necessary
        self.file = db.Get().FindInfo(self.view)
        self.doc  = None
        self.docClass = exp.GetGlobalOption(self.file,"LATEX_CLASS","latexClass","article").lower()
        try:
            outputFilename = exp.ExportFilename(self.view,".tex",self.suffix)
            self.doc       = LatexDoc(outputFilename,self.file)
            self.doc.setClass(self.docClass)
            self.helper    = exp.OrgExportHelper(self.view,self.index)
            self.helper.Run(outputFilename, self.doc)
            self.doc.Execute()
            # TODO: Delete the tex file
        finally:    
            evt.EmitIf(self.onDone)


    def run(self,edit, onDone=None, index=None, suffix=""):
        self.file = db.Get().FindInfo(self.view)
        self.onDone = onDone
        self.suffix = suffix
        if(index != None):
            self.index = index
        else:
            self.index = None
        if(None == self.file):
            log.error("Not an org file? Cannot build reveal document")
            evt.EmitIf(onDone)  
            return
        if(sets.Get("latexExecuteSourceOnExport",False)):
            self.view.run_command('org_execute_all_source_blocks',{"onDone":evt.Make(self.OnDoneSourceBlockExecution),"amExporting": True})
        else:
            self.OnDoneSourceBlockExecution()

# ============================================================
class OrgExportFileAsLatexCommand(sublime_plugin.TextCommand):

    def OnDoneSourceBlockExecution(self):
        # Reload if necessary
        self.file = db.Get().FindInfo(self.view)
        self.doc  = None
        self.docClass = exp.GetGlobalOption(self.file,"LATEX_CLASS","latexClass","article").lower()
        try:
            outputFilename = exp.ExportFilename(self.view,".tex",self.suffix)
            self.doc       = LatexDoc(outputFilename,self.file)
            self.doc.setClass(self.docClass)
            self.helper    = exp.OrgExportHelper(self.view,self.index)
            self.helper.Run(outputFilename, self.doc)
        finally:    
            evt.EmitIf(self.onDone)


    def run(self,edit, onDone=None, index=None, suffix=""):
        self.file = db.Get().FindInfo(self.view)
        self.onDone = onDone
        self.suffix = suffix
        if(index != None):
            self.index = index
        else:
            self.index = None
        if(None == self.file):
            log.error("Not an org file? Cannot build reveal document")
            evt.EmitIf(onDone)  
            return
        if(sets.Get("latexExecuteSourceOnExport",False)):
            self.view.run_command('org_execute_all_source_blocks',{"onDone":evt.Make(self.OnDoneSourceBlockExecution),"amExporting": True})
        else:
            self.OnDoneSourceBlockExecution()

def SetupDnd():
    import OrgExtended.orgutil.webpull as wp
    wp.DownloadDnd()

class OrgExportFileAsDndPdfCommand(sublime_plugin.TextCommand):
    def run(self,edit, onDone=None, index=None, suffix=""):
        self.file = db.Get().FindInfo(self.view)
        self.onDone = onDone
        self.suffix = suffix
        SetupDnd()

