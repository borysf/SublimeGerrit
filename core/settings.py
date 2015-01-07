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
import codecs
import os
from copy import deepcopy


class ProjectSettings():
    data = None
    temp = {}

    @classmethod
    def load(self):
        if self.data is None and sublime.active_window().project_file_name() is not None:
            self.data = sublime.active_window().project_data()

    @classmethod
    def persistable(self):
        return not not sublime.active_window().project_file_name()

    @classmethod
    def save(self, key, values):
        self.load()

        if self.data is None:
            target = self.temp
        else:
            target = self.data

        root = self.get_key()

        if key not in target:
            target.update({root: {}})

        for name in values:
            target[root].update({key + '.' + name: values[name]})

        if self.data is not None:
            sublime.active_window().set_project_data(self.data)

    @classmethod
    def get_key(self):
        window = sublime.active_window()

        return 'sublimegerrit:%s' % (window.project_file_name() or str(window.id()))

    @classmethod
    def get(self, subkey):
        self.load()

        key = self.get_key()

        if self.data is None:
            target = self.temp
        else:
            target = self.data

        return deepcopy(target[key][subkey]) if key in target and subkey in target[key] else {}


class Settings():
    plugin_loaded = False
    instances = {}
    settings = None

    @classmethod
    def load_all(self):
        pass

    @classmethod
    def load(self):
        if self.settings is None:
            self.settings = sublime.load_settings('SublimeGerrit.sublime-settings')

    @classmethod
    def get(self, name):
        self.load()
        return self.settings.get(name)

    @classmethod
    def set(self, name, value):
        self.load()
        return self.settings.set(name, value)

    @classmethod
    def save(self, key, values):
        for name in values:
            self.set(key + '.' + name, values[name])

        return sublime.save_settings('SublimeGerrit.sublime-settings')

    @classmethod
    def erase(self, key):
        self.settings.erase(key)

        return sublime.save_settings('SublimeGerrit.sublime-settings')

    @classmethod
    def on(self, key, callback):
        self.load()
        self.settings.add_on_change(key, callback)

    @classmethod
    def un(self, key):
        self.load()
        self.settings.clear_on_change(key)


class ConnectionSettings():

    @classmethod
    def get(self, key):
        if key == 'url':
            return self.get_url()

        return Settings.get('connection.' + key)


    @classmethod
    def get_url(self):
        url = Settings.get('connection.url')

        if not url:
            host = Settings.get('connection.host')
            port = Settings.get('connection.port')

            if host:
                expl = host.strip('/').split('/')
                host = expl[0]
                path = ('/' + '/'.join(expl[1:])) if len(expl) > 1 else ''
                port = int(port or '80')

                url = "%s://%s:%d/%s" % (
                    'https' if port == 443 else 'http',
                    host,
                    port,
                    path
                )

                Settings.erase('connection.host')
                Settings.erase('connection.port')

                Settings.save('connection', {'url': url.strip('/')})

        url = url or ''

        url = url.strip('/')

        return url

    @classmethod
    def is_connectable(self, conn=None):
        if not conn:
            conn = {
                'username': Settings.get('connection.username'),
                'password': Settings.get('connection.password'),
                'url': self.get_url(),
                'timeout': Settings.get('connection.timeout')
            }

        if 'username' in conn and conn['username'] or 'password' in conn and conn['password']:
            required = ['username', 'password', 'url']
        else:
            required = ['url']

        for field in required:
            if field not in conn or not conn[field]:
                return False

        return True

