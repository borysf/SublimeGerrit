"""
SublimeGerrit - full-featured Gerrit Code Review for Sublime Text

Copyright (C) 2015 Borys Forytarz <borys.forytarz@gmail.com>

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
"""

import sublime
import os
import re
import base64
from copy import deepcopy

from .git import Command
from .utils import git_root
from .resources import GerritResources
from .settings import Settings

class GutterComments():
    instances = {}
    suspended = False

    @classmethod
    def set_suspended(self, v):
        self.suspended = v

    @classmethod
    def get_view_id(self, view):
        return '%d.%s' % (view.id(), view.file_name())

    @classmethod
    def trigger(self, view):
        return #temporarily disable this feature. to be done better.

        if view.file_name() is None or view.is_scratch() or view.is_read_only():
            return

        view_id = self.get_view_id(view)

        def done(stdout, repo_root):
            for line in stdout:
                matches = re.match('^Change-Id:\s+([a-zA-Z0-9]+)', line)

                if matches:
                    if view_id not in self.instances:
                        self.instances.update({view_id: GutterComments(view, repo_root)})

                    self.instances[view_id].get_data(matches.group(1), stdout[0])
                    return

        def check_view(view):
            if not os.path.exists(view.file_name()):
                return

            if view_id not in self.instances:
                repo_root = git_root(os.path.dirname(view.file_name()))
            else:
                repo_root = self.instances[view_id].repo_root

            if repo_root is not None:
                os.chdir(os.path.dirname(view.file_name()))
                Command(
                    command='git log -n 1 --pretty="%H%n%b" -- "' + os.path.basename(view.file_name()) + '"',
                    on_done=lambda exit_code, stdout, stderr: done(stdout, repo_root),
                    on_failure=lambda exit_code, stdout, stderr: None,
                    silent=True
                )


        sublime.set_timeout(lambda: check_view(view), 1000)

    @classmethod
    def get_instance_for_view(self, view):
        view_id = self.get_view_id(view)

        if view_id in self.instances:
            return self.instances[view_id]

        return None

    @classmethod
    def on_activated(self, view):
        instance = self.get_instance_for_view(view)

        if instance is not None:
            instance.on_selection_modified()

    def __init__(self, view, repo_root):
        self.view = view
        self.repo_root = repo_root.replace('\\', '/')
        self.comments = []
        self.resources = GerritResources()
        self.file_path = self.view.file_name().replace('\\', '/').replace(self.repo_root, '')
        self.file_path = self.file_path[1:] if self.file_path[0] == '/' else self.file_path
        self.revision_file = None
        self.comments_loaded = False
        self.change_id = None
        self.revision_id = None

    def destroy(self):
        if self.view:
            view_id = self.get_view_id(self.view)

            if view_id in GutterComments.instances:
                del GutterComments.instances[view_id]

        self.erase_comments()
        self.change_id = None
        self.revision_id = None
        self.view = []

    def clone_sel(self):
        self.old_sel = [r for r in self.view.sel()]

    def get_data(self, change_id, revision_id):
        if self.change_id != change_id or self.revision_id != revision_id:
            self.change_id = change_id
            self.revision_id = revision_id
            self.erase_comments()

            self.resources.get_content(change_id, revision_id, self.file_path).then(
                lambda data: self.load_revision_file(change_id, revision_id, data)
            )

    def normalize_crlf(self, text):
        text = re.sub('\r\n', '\n', text)
        text = re.sub('\r', '\n', text)

        return text

    def load_revision_file(self, change_id, revision_id, data):
        if data is None:
            return

        self.revision_file = self.normalize_crlf(base64.b64decode(data).decode('utf-8')).split('\n')

        self.resources.get_comments(self.change_id, self.revision_id).then(self.draw_comments)

    def draw_comments(self, data):
        if data is not None:
            self.erase_comments()
            path = self.file_path

            if path in data:
                self.add_comments(data[path])

    def add_comments(self, comments):
        self.comments_loaded = True

        self.erase_comments()
        icon_path = 'Packages/SublimeGerrit/icons/comment.png'

        for comment in comments:
            if 'line' not in comment:
                continue

            lineno = comment['line']

            begin = self.view.text_point(lineno - 1, 0)
            region = self.view.line(sublime.Region(begin, begin))

            comment.update({
                'region': region
            })

            comment.update({'icon': {
                'active': [
                    'comment-%s-icon' % comment['line'],
                    [region],
                    Settings.get('diff.comment_icon_active'),
                    icon_path,
                    # 'bookmark',
                    sublime.DRAW_NO_OUTLINE | sublime.DRAW_NO_FILL
                ],
                'inactive': [
                    'comment-%s-icon' % comment['line'],
                    [region],
                    Settings.get('diff.comment_icon_inactive'),
                    icon_path,
                    # 'bookmark',
                    sublime.DRAW_NO_OUTLINE | sublime.DRAW_NO_FILL
                ]
            }})

            self.comments.append(comment)
            self.view.add_regions(*comment['icon']['inactive'])

    def erase_comments(self):
        for comment in self.comments:
            self.view.erase_regions(comment['icon']['active'][0])

        self.comments = []

    def activate_comment(self, comment):
        for i in range(0, 3):
            if i % 2 == 0:
                icon = 'active'
            else:
                icon = 'inactive'

            sublime.set_timeout(lambda: self.view.add_regions(*comment['icon'][icon]), i * 20)


    def deactivate_comment(self, comment):
        self.view.add_regions(*comment['icon']['inactive'])

    def clear_comments_panel(self):
        panel_name = 'sublimegerrit-comments-%d' % self.view.window().id()

        panel = self.view.window().get_output_panel(panel_name)
        panel.run_command('sublime_gerrit_clear')

    def on_selection_modified(self, view):
        if GutterComments.suspended:
            return

        sel = self.view.sel()
        panel_name = 'sublimegerrit-comments-%d' % self.view.window().id()

        panel = self.view.window().get_output_panel(panel_name)
        panel.run_command('sublime_gerrit_clear')

        comments = []

        if len(sel) == 1:
            for comment in self.comments:
                comment['region'] = self.view.get_regions(comment['icon']['inactive'][0])[0]
                comment['icon']['inactive'][1] = [comment['region']]
                comment['icon']['active'][1] = [comment['region']]

                self.deactivate_comment(comment)

                comment['region'] = self.view.get_regions(comment['icon']['inactive'][0])[0]

                if comment['region'].contains(sel[0]):
                    comments.append(
                        '%s:\n\n%s' % (
                            comment['author']['name'] if 'author' in comment else 'Me',
                            comment['message']
                        )
                    )

                    self.activate_comment(comment)

            if len(comments) > 0:
                panel.run_command('sublime_gerrit_insert', {
                    'content': '\n\n\n'.join(comments),
                    'pos': 0
                })

                self.view.window().run_command('show_panel', {
                    'panel': 'output.' + panel_name
                })

                return


    def on_modified(self):
        for comment in self.comments:
            regions = self.view.get_regions(comment['icon']['active'][0])

            if regions and len(regions) == 1:
                comment['icon']['active'][1][0] = comment['icon']['inactive'][1][0] = comment['region'] = regions[0]

