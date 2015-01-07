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
import re

class Template():
    settings = None

    def __init__(self, name):
        if Template.settings is None:
            Template.settings = sublime.load_settings('SublimeGerritTemplates.sublime-settings')

        template = Template.settings.get(name)

        if isinstance(template, str):
            self.template = [template]
        elif isinstance(template, list):
            self.template = template[:]
        else:
            raise ValueError('Template `%s` must be an array or string' % name)

    def apply(self, data):
        ret = []

        for row in self.template:
            for variable in re.finditer('(\${[_a-zA-Z][a-zA-Z0-9_\.-]+})', row):
                root = data
                path = variable.group(1)[2:-1].split('.')

                for var in path:
                    if re.match('^\d+$', var):
                        var = int(var)

                    try:
                        root = root[var]
                    except:
                        root = '<NOT FOUND>'
                        break

                row = row.replace(variable.group(1), str(root))

            ret.append(row)

        return ret

    def applystr(self, data):
        return "\n".join(self.apply(data))
