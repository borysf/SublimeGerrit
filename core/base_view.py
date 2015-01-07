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

class BaseView():
    instances = {}

    @classmethod
    def find_instance_by_view(self, view):
        window_id = view.window().id() if view.window() else None

        if window_id is not None and window_id in BaseView.instances:
            for instance in BaseView.instances[window_id]:
                if view in instance.views():
                    return instance
        else:
            for window_id in BaseView.instances:
                for instance in BaseView.instances[window_id]:
                    if view in instance.views():
                        return instance


    @classmethod
    def get_active_instance(self):
        window = sublime.active_window()

        if window:
            view = window.active_view()

            if view:
                return BaseView.find_instance_by_view(view)

        return None


    @classmethod
    def destroy_all(self):
        for window_id in self.instances:
            while len(BaseView.instances) > 0:
                BaseView.instances.pop().destroy()


    def __init__(self):
        self.window = sublime.active_window()
        window_id = self.window.id()

        if window_id not in BaseView.instances:
            BaseView.instances.update({window_id: [self]})
        else:
            BaseView.instances[window_id].append(self)


    def destroy(self):
        window_id = self.window.id()

        if window_id in BaseView.instances:
            BaseView.instances[window_id].remove(self)
        else:
            for window_id in BaseView.instances:
                for instance in BaseView.instances[window_id]:
                    if instance is self:
                        BaseView.instances[window_id].remove(self)
                        return
