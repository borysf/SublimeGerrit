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
import sublime_plugin
import os

from .reloader import Reloader
from .notifier import Notifier
from .gutter_comments import GutterComments
from .base_view import BaseView
from .settings import Settings


class Listener(sublime_plugin.EventListener):
    def on_activated(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is not None:
            instance.on_activated(view)
        else:
            GutterComments.trigger(view)

        Notifier.clone_status(view)

    def on_deactivated(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is not None:
            instance.on_deactivated(view)

    def on_modified(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is not None:
            instance.on_modified(view)

    def on_selection_modified(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is not None:
            instance.on_selection_modified(view)
        else:
            instance = GutterComments.get_instance_for_view(view)

            if instance:
                instance.on_selection_modified(view)

    def on_close(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is not None:
            instance.on_close(view)

    def on_open(self, view):
        instance = BaseView.find_instance_by_view(view)

        if instance is None:
            GutterComments.trigger(view)


    def on_post_save(self, view):
        try:
            if Settings.get('__devel__') and view.file_name().index('SublimeGerrit'):
                Reloader.reload()

                path = os.path.join(sublime.packages_path(), 'SublimeGerrit', 'SublimeGerrit.py')

                f = open(path, 'r')
                content = f.read()
                f.close()

                f = open(path, 'w')
                f.write(content)
                f.close()
        except:
            pass
