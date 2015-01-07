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
import imp
import sys
import re
import codecs
from os import makedirs
from os.path import exists, join
import zipfile

from .settings import Settings
from .version import VERSION
from .notifier import Notifier

def errmsg(msg, estr):
    sublime.set_timeout(lambda: sublime.error_message('%s\n\n%s' % (msg, estr)), 3000)

class Reloader():
    cleanup_settings = 'SublimeGerrit.cleanup-info.sublime-settings'
    notifier = None

    @classmethod
    def load_ssl(self):
        self.unpack()

        libssl_path = join(sublime.packages_path(), 'SublimeGerrit', 'libssl')
        libssl_versions = ['1.0.0', '10', '0.9.8']

        # Try to load ssl module. Thanks to Will Bond for permission to use this solution!
        if sublime.platform() == 'linux':
            for libssl_version in libssl_versions:
                sys.path.append(join(libssl_path, 'libssl-%s-%s' % (libssl_version, sublime.arch())))

                try:
                    import _ssl
                    print('SublimeGerrit: Loaded _ssl module: libssl.so.%s' % libssl_version)
                    break
                except (ImportError) as e:
                    print('SublimeGerrit: _ssl module import error: ' + str(e))

            if '_ssl' in sys.modules:
                try:
                    import ssl
                except (ImportError) as e:
                    print('SublimeGerrit: ssl module import error: ' + str(e))

    @classmethod
    def reload(self):
        self.load_ssl()

        for i in range(0, 2):
            for name in dir(sys.modules['SublimeGerrit.core']):
                if name[0:2] != '__' and name != 'settings':
                    imp.reload(sys.modules['SublimeGerrit.core.' + name])

        Settings.load_all()
        self.cleanup_restore()

        if self.notifier is not None:
            self.notifier.destroy()

        self.notifier = Notifier()

    @classmethod
    def unpack(self):
        theme_path = join(sublime.packages_path(), "Theme - Default")

        if not exists(theme_path):
            makedirs(theme_path)

        pack_path = join(sublime.installed_packages_path(), "SublimeGerrit.sublime-package")
        unpack_path = join(sublime.packages_path(), "SublimeGerrit")

        if exists(pack_path):
            if not exists(unpack_path):
                makedirs(unpack_path)

            version_path = join(unpack_path, 'version')
            unpack = True

            if exists(version_path):
                try:
                    f = open(version_path, 'r')
                    unpack = f.read() != VERSION
                    f.close()
                except LookupError:
                    f = codecs.open(version_path, 'r', 'utf-8')
                    unpack = f.read() != VERSION
                    f.close()

            if unpack:
                try:
                    resources = [
                        'icons/comment.png',
                        'icons/draft.png',
                        'SublimeGerrit.sublime-settings',
                        'Default (Linux).sublime-keymap',
                        'Default (Windows).sublime-keymap',
                        'Default (OSX).sublime-keymap',
                        'syntax/SublimeGerrit.tmLanguage',
                        'syntax/SublimeGerritConsole.tmLanguage'
                    ]

                    if sublime.platform() == 'linux':
                        resources += [
                            'libssl/libssl-0.9.8-%s/_ssl.cpython-33m.so' % sublime.arch(),
                            'libssl/libssl-1.0.0-%s/_ssl.cpython-33m.so' % sublime.arch(),
                            'libssl/libssl-10-%s/_ssl.cpython-33m.so' % sublime.arch()
                        ]


                    z = zipfile.ZipFile(pack_path, 'r')
                    for resource in resources:
                        z.extract(resource, unpack_path)

                    z.close()

                    try:
                        f = open(version_path, 'w')
                        f.write(VERSION)
                        f.close()
                    except LookupError:
                        f = codecs.open(version_path, 'w', 'utf-8')
                        f.write(VERSION)
                        f.close()
                except Exception as e:
                    estr = str(e)

                    if estr.find('zlib') != -1:
                        errmsg('There is a problem with zlib in your Sublime Text Python\'s distribution. You may try to re-install Sublime Text.', estr)
                    elif estr.find('denied') != -1:
                        errmsg('Unable to unpack resources. Please correct access rights and restart Sublime Text.', estr)
                    else:
                        raise

    @classmethod
    def cleanup_set_name(self, name):
        s = sublime.load_settings(self.cleanup_settings)
        v = s.get('names') or []
        v.append(name)
        s.set('names', v)
        sublime.save_settings(self.cleanup_settings)

    @classmethod
    def cleanup_set_layout(self):
        s = sublime.load_settings(self.cleanup_settings)

        if s.get('layout'):
            return

        v = s.set('layout', sublime.active_window().get_layout())
        sublime.save_settings(self.cleanup_settings)

    @classmethod
    def cleanup_restore(self):
        s = sublime.load_settings(self.cleanup_settings)

        layout = s.get('layout')
        names = s.get('names') or []

        for window in sublime.windows():
            for view in window.views():
                if re.match('^\*GERRIT\*', view.name()) or view.name() in names:
                    window.focus_view(view)
                    window.run_command('close')

            if layout:
                window.set_layout(layout)

        s.set('layout', None)
        s.set('names', None)

        sublime.save_settings(self.cleanup_settings)
