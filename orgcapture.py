import sublime
import sublime_plugin
import datetime
import re
from pathlib import Path
import os
import fnmatch
from .orgparse.__init__ import *
import OrgExtended.orgparse.node as node
from   OrgExtended.orgparse.sublimenode import * 
import OrgExtended.orgutil.util as util
import OrgExtended.orgutil.navigation as nav
import OrgExtended.orgutil.template as templateEngine
import OrgExtended.orgparse.date as orgdate
import OrgExtended.orgextension as ext
import logging
import sys
import traceback 
import OrgExtended.orgdb as db
import OrgExtended.asettings as sets
import OrgExtended.orgproperties as props
import time

log = logging.getLogger(__name__)
captureBufferName = "*capture*"
lastHeader        = None

# This is a bit hokey. We track the last header so
# if you change the header we can still find it
# in your target file. Every time you swap your
# mouse away from the capture window we auto save
# the capture to your target location.
# TODO: Add more target locations than your refile file.
def onDeactivated(view):
    global captureBufferName
    global lastHeader
    if(view.name() == captureBufferName):
        refilePath = sets.Get("refile","UNKNOWN")
        refile = load(refilePath)
        bufferContents = view.substr(sublime.Region(0, view.size()))
        if not bufferContents.endswith('\n'):
            bufferContents += "\n"
        didInsert = False
        capture = loads(bufferContents)
        if(lastHeader == None):
            lastHeader = str(capture[1].heading)
        for heading in refile:
            if(type(heading) is node.OrgRootNode):
                continue
            if str(heading.heading) == lastHeader:
                #log.debug("REPLACING: " + str(heading.heading))
                heading.replace_node(capture[1])
                didInsert = True
                continue
        if(not didInsert):
            var = capture[1]
            refile.insert_child(var)
        f = open(refilePath,"w+")
        for item in refile:
            f.write(str(item))
        f.close()
        lastHeader = str(capture[1].heading)
        log.debug("***************>>>>> [" + view.name() + "] is no more")

# Respond to panel events. If the panel is hidden we stop
# tracking the last header.
def onPostWindowCommand(window, cmd, args):
    if cmd == "hide_panel":
        global lastHeader
        # This stops the capture refiling
        # From finding an entry across capture
        # window openings
        lastHeader = None


class OrgCopyCommand(sublime_plugin.TextCommand):
    def on_done(self, index):
        file, fileIndex = db.Get().FindFileInfoByAllHeadingsIndex(index)
        node = db.Get().AtInView(self.view)
        if(fileIndex != None):
            #print(str(file.key))
            file.org[fileIndex].insert_child(node)
            file.Save()
        else:
            log.error("Failed to copy, fileindex not found")

    def run(self, edit):
        self.headings = db.Get().AllHeadingsWContext(self.view)
        self.view.window().show_quick_panel(self.headings, self.on_done, -1, -1)

class OrgOpenRefileCommand(sublime_plugin.TextCommand):
    def run(self,edit):
        refile = sets.Get("refile",None)
        log.debug("REFILE: ", refile)
        if(refile):
           self.view.window().open_file(refile) 
        else:
            log.error("Could not find refile file, have you set it in your config?")

# Archiving will push the current item to an archive file (with some tags etc)
class OrgArchiveSubtreeCommand(sublime_plugin.TextCommand):

    def close_tempView(self):
        self.tempView.run_command("close")

    def finish_archive_on_loaded(self):
        while(self.tempView.is_loading()):
            sublime.set_timeout_async(lambda: self.finish_archive_on_loaded(), 100)
        node = self.file.At(self.result.start_row)
        #:ARCHIVE_TIME: 2017-11-30 Thu 18:15
        #:ARCHIVE_FILE: ~/notes/inxile/worklog.org
        #:ARCHIVE_OLPATH: Daily
        #:ARCHIVE_CATEGORY: InXile
        #:ARCHIVE_ITAGS: InXile
        props.UpdateProperty(self.tempView,node, "ARCHIVE_TIME", datetime.datetime.now().strftime("%Y-%m-%d %a %H:%M"))
        props.UpdateProperty(self.tempView,node, "ARCHIVE_FILE", self.view.file_name())
        self.tempView.run_command("save")
        sublime.set_timeout_async(lambda: self.close_tempView(), 1000)
        # Now remove the old node
        self.sourceNode.remove_node()
        fromFile = db.Get().FindInfo(self.view)
        fromFile.Save()
        fromFile.Reload()

    def run(self,edit):
        globalArchive = sets.Get("archive","%s_archive::")
        node          = db.Get().AtInView(self.view)
        archive       = node.archive(globalArchive)
        if(archive == None or archive.strip() == ""):
            node = db.Get().AtInView(self.view)
            node.add_tag("ARCHIVE")
            file = db.Get().FindInfo(self.view)
            file.Save()
            print(str(node))
            return
        (fileTemplate, headingTarget) = archive.split('::')
        filename      = fileTemplate % (self.view.file_name()) 
        log.debug("ARCHIVE FILE:    " + filename)
        log.debug("ARCHIVE HEADING: " + headingTarget)

        # Ensure the file actually exists.
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "a") as f:
            log.debug("  Archive file created...")
        # Okay now open the file.
        file       = db.Get().FindInfo(filename)
        sourceNode = db.Get().AtInView(self.view)
        if(sourceNode != None):
            log.debug("Find or create: " + headingTarget)
            targetNode = file.FindOrCreateNode(headingTarget)
            log.debug("Inserting heading at: " + targetNode.heading)
            log.debug("Inserting: " + sourceNode.heading)
            self.result = targetNode.insert_child(sourceNode)

            self.result.update_property("ARCHIVE_TIME", datetime.datetime.now().strftime("%Y-%m-%d %a %H:%M"))
            self.result.update_property("ARCHIVE_FILE", self.view.file_name())
            for n in file.org[1:]:
                print(n.full_heading)
            log.debug("Saving the source file")
            file.Save()
            file.Reload()


            sourceNode.remove_node()
            fromFile = db.Get().FindInfo(self.view)
            fromFile.Save()
            fromFile.Reload()
            #self.tempView = self.view.window().open_file(file.filename, sublime.ENCODED_POSITION)
            #self.file = file
            #self.sourceNode = sourceNode
            #sublime.set_timeout_async(lambda: self.finish_archive_on_loaded(), 1000)
        else:
            log.error("Failed to archive subtree! Could not find source Node")  


        
class OrgRefileCommand(sublime_plugin.TextCommand):
    def on_done(self, index):
        file, fileIndex = db.Get().FindFileInfoByAllHeadingsIndex(index)
        view = self.view
        (curRow,curCol) = view.curRowCol()
        node = db.Get().At(view, curRow)

        #print(str(file.key))
        if(node == None):
            log.error("COULD NOT REFILE: Node at line " + str(curRow) + " not found")
            return
        if(fileIndex == None):
            log.error("Could not refile file index is out of bounds")
            return 
        log.debug("Inserting child into: " + str(fileIndex) + " vs " + str(len(file.org)) + " in file: " + file.filename)

        file.org[fileIndex].insert_child(node)
        file.Save()
        file.Reload()

        node.remove_node()
        fromFile = db.Get().FindInfo(view)
        fromFile.Save()
        fromFile.Reload()

    def run(self, edit):
        self.headings = db.Get().AllHeadingsWContext(self.view)
        self.view.window().show_quick_panel(self.headings, self.on_done, -1, -1)



# Capture some text into our refile org file
class OrgCaptureCommand(sublime_plugin.TextCommand):
    def insert_template(self, template, panel):
        #template          = templates[index]['template']
        startPos = -1
        template, startPos = templateEngine.ExpandTemplate(self.view, template)

        panel.run_command("insert",{"characters": template})
        if(startPos >= 0):
            startPos = sublime.Region(startPos)
        else:
            startPos = panel.sel()[0]
        return startPos

    def on_done(self, index):
        if(index < 0):
            return
        global captureBufferName
        captureBufferName = sets.Get("captureBufferName", captureBufferName)
        templates         = sets.Get("captureTemplates",[])
        window = self.view.window()
        panel = window.create_output_panel("orgcapture")
        startPos = -1
        if('template' in templates[index]):
            startPos = self.insert_template(templates[index]['template'], panel)
            window.run_command('show_panel', args={'panel': 'output.orgcapture'})
            panel.sel().clear()
            panel.sel().add(startPos)
            window.focus_view(panel)
        elif('snippet' in templates[index]):
            window.run_command('show_panel', args={'panel': 'output.orgcapture'})
            ai = sublime.active_window().active_view().settings().get('auto_indent')
            panel.settings().set('auto_indent',False)
            snippet = templates[index]['snippet']
            snipName = ext.find_extension_file('snippets',snippet,'.sublime-snippet')
            window.focus_view(panel)
            #panel.meta_info("shellVariables", 0)[0]['TM_EMAIL'] = "Trying to set email value"
            panel.run_command('_enter_insert_mode', {"count": 1, "mode": "mode_internal_normal"})
            now = datetime.datetime.now()
            inow = orgdate.OrgDate.format_date(now, False)
            anow = orgdate.OrgDate.format_date(now, True)
            # "Packages/OrgExtended/snippets/"+snippet+".sublime-snippet"
            panel.run_command("insert_snippet", 
                { "name" : snipName
                , "ORG_INACTIVE_DATE": inow
                , "ORG_ACTIVE_DATE":   anow})
            sublime.active_window().active_view().settings().set('auto_indent',ai)
        panel.set_syntax_file('Packages/OrgExtended/orgextended.sublime-syntax')
        panel.set_name(captureBufferName)

    def run(self, edit):
        templates = sets.Get("captureTemplates",[])
        temps = []
        for temp in templates:
            log.debug("TEMPLATE: ", temp)
            temps.append(temp['name'])

        self.view.window().show_quick_panel(temps, self.on_done, -1, -1)

