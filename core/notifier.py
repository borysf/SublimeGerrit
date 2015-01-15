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

from .settings import Settings, ProjectSettings, ConnectionSettings
from .resources import GerritResources
from .utils import project_query
import sublime
import re

class Notifier():
    last_value = {}
    blinks = {}
    key = 'aaaaaaaaaaaaa_SublimeGerrit'

    @classmethod
    def message(self, size):
        if size > 0:
            return 'Gerrit: %d open changes' % (size)
        else:
            return 'Gerrit: no changes open'

    @classmethod
    def clone_status(self, onto_view):
        if onto_view.window():
            window_id = onto_view.window().id()

            if window_id not in Notifier.blinks or Notifier.blinks[window_id] != 0:
                return

            if window_id in Notifier.last_value:
                onto_view.set_status(self.key, self.message(Notifier.last_value[window_id]))

    @classmethod
    def propagate_status(self):
        for window in sublime.windows():
            if window.id() in Notifier.last_value:
                message = Notifier.message(Notifier.last_value[window.id()])

                for view in window.views():
                    view.set_status(self.key, message)

    def __init__(self):
        self.resources = GerritResources()
        self.destroyed = False
        Settings.on('connection.url', lambda *args: self.check(False))
        Settings.on('connection.username', lambda *args: self.check(False))
        Settings.on('connection.password', lambda *args: self.check(False))
        Settings.on('notifications.check_interval', lambda *args: self.check(False))
        Settings.on('notifications.check_limit', lambda *args: self.check(False))
        Settings.on('notifications.check_query', lambda *args: self.check(False))

        sublime.set_timeout(self.check, 5000)

    def destroy(self):
        self.destroyed = True
        Settings.un('connection.url')
        Settings.un('connection.username')
        Settings.un('connection.password')
        Settings.un('notifications.check_interval')
        Settings.un('notifications.check_limit')
        Settings.un('notifications.check_query')

    def check(self, schedule=True):
        if not self.destroyed and ConnectionSettings.is_connectable():
            s = {
                'check_interval': int(Settings.get('notifications.check_interval')),
                'check_limit': int(Settings.get('notifications.check_limit')),
                'check_query': Settings.get('notifications.check_query')
            }

            if s['check_interval'] == 0 or s['check_limit'] == 0:
                return

            query = s['check_query']
            query += project_query()

            self.resources.check_changes(
                s['check_limit'],
                {'q': query}
            ).then(lambda data: self.notify(data, schedule))

    def notify(self, data, schedule):
        window_id = sublime.active_window().id()
        view = sublime.active_window().active_view()
        size = 0 if data is None else len(data)

        if window_id not in Notifier.last_value or Notifier.last_value[window_id] != size:
            view.set_status(Notifier.key, '')

            Notifier.last_value.update({window_id: size})

            if size > 0:
                self.blink(Notifier.message(size), size, schedule)
                return # blink -> schedule()
            else:
                self.propagate_status()

        if schedule:
            self.schedule()

    def blink(self, text, size, schedule):
        window_id = sublime.active_window().id()
        view = sublime.active_window().active_view()

        if window_id not in Notifier.blinks:
            Notifier.blinks.update({window_id: 0})

        if Notifier.blinks[window_id] % 2 == 0:
            sublime.status_message(text)
        else:
            sublime.status_message('')

        Notifier.blinks[window_id] += 1

        if Notifier.blinks[window_id] <= 16:
            sublime.set_timeout(lambda: self.blink(text, size, schedule), 500)
        else:
            Notifier.blinks[window_id] = 0
            sublime.status_message('')

            Notifier.last_value.update({window_id: size})

            self.propagate_status()

            if schedule:
                self.schedule()

    def schedule(self):
        if not self.destroyed:
            sublime.set_timeout(self.check, int(Settings.get('notifications.check_interval')) * 1000)
