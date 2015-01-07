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
import tempfile
import re

import time
import datetime
import textwrap

from urllib.parse import urlsplit

from .version import VERSION
from .template import Template
from .settings import Settings, ProjectSettings

def cmp(a, b):
    return (a > b) - (a < b)

def version_compare(version1, version2):
    def normalize(v):
        matches = re.match('^(\d+\.?)+', v)

        if matches:
            v = matches.group(0)

        return [int(x) for x in re.sub(r'(\.0+)*$','', v).split(".")]

    return cmp(normalize(version1), normalize(version2))

def log(*args):
    if Settings.get('debug'):
        print(*args)

def fopen(path, mode):
    try:
        return open(path, mode)
    except LookupError:
        return codecs.open(path, mode, 'utf-8')

def ellipsis(text):
    text = text or ''

    if len(text) > 70:
        text = textwrap.wrap(text, 70)[0] + '...'

    return text

def git_root(file_path=None):
    def down(path):
        if os.path.exists(path + '/.git'):
            return path

        sp = os.path.split(path)

        if sp[0] != path and sp[0] != '':
            return down(sp[0])
        else:
            return None

    if file_path is None:
        return None

    return down(file_path)

def create_tmpfile_path(file_name):
    f = tempfile.NamedTemporaryFile(suffix=os.path.basename(file_name))
    path = f.name
    f.close()

    return path


def get_reviewer_name(reviewer):
    if 'name' in reviewer and reviewer['name']:
        return reviewer['name']
    elif 'username' in reviewer and reviewer['username']:
        return reviewer['username']
    elif 'email' in reviewer and reviewer['email']:
        return reviewer['email']
    else:
        return 'Anonymous (%d)' % (reviewer['_account_id'])


def get_labels(change):
    labels = []

    for label_name in change['labels']:
        label = change['labels'][label_name]

        data = {'label': label_name, 'score': get_opinion(label)}

        labels.append(Template('change_label').applystr(data))

    return labels


def get_opinion(label):
    value = 0

    icon_ok = Settings.get('icon_approved')
    icon_failed = Settings.get('icon_rejected')

    if 'rejected' in label:
        return icon_failed
    elif 'approved' in label:
        return icon_ok
    elif 'disliked' in label:
        return str(label['value'])
    elif 'recommended' in label:
        return '+' + str(label['value'])

    return '0'

    return {'value': 'No score', 'icon': '    ', 'points': '0'}

def error_message(text):
    sublime.error_message('SublimeGerrit\n\n%s' % text)

def info_message(text):
    sublime.message_dialog('SublimeGerrit\n\n%s' % text)

current_over = None

def quick_panel(items, on_select=None, on_cancel=None, on_over=None, on_out=None, selected_index=-1):

    def callback_on_done(index):
        global current_over

        if current_over is not None and 'on_out' in current_over and current_over['on_out']:
            current_over['on_out'](current_over)

        current_over = None

        if index > -1:
            if 'on_select' in items[index] and items[index]['on_select']:
                items[index]['on_select'](items[index])

            if on_select is not None:
                on_select(items[index])
        elif on_cancel is not None:
            on_cancel()

    def callback_on_highlight(index):
        global current_over

        if current_over is not None and 'on_out' in current_over and current_over['on_out']:
            current_over['on_out'](current_over)

        current_over = items[index]

        if 'on_over' in current_over and current_over['on_over']:
            current_over['on_over'](current_over)

        if 'on_over' in items[index] and items[index]['on_over']:
            items[index]['on_over'](items[index])

        if on_over is not None:
            on_over(items[index])

    max_len = 0

    index = 0
    for item in items:
        max_len = max(max_len, len(item['caption']))

        if 'selected' in item and item['selected']:
            selected_index = index

        for i in range(0, len(item['caption'])):
            item['caption'][i] = str(item['caption'][i])

        index += 1

    for item in items:
        item['caption'] += [''] * (max_len - len(item['caption']))

    sublime.set_timeout(lambda: sublime.active_window().show_quick_panel(
        items=[item['caption'] for item in items],
        on_select=callback_on_done,
        on_highlight=callback_on_highlight,
        flags=0,
        selected_index=selected_index
    ), 0)


def quick_menu(root, on_cancel=None):
    entries = []

    for item in root:
        if 'items' in item:
            entries.append({
                'caption': item['caption'],
                'sub_root': item['items'],
                'on_select': lambda selected: quick_menu(selected['sub_root'], lambda: quick_menu(root, on_cancel))
            })
        else:
            entries.append({
                'caption': item['caption'],
                'self': item,
                'on_select': lambda selected: selected['self']['on_select'](selected['self'], lambda: quick_menu(root, on_cancel)) if 'on_select' in item else None,

            })

    quick_panel(entries, on_cancel=on_cancel)

def capwords(text, delim=" "):
    return " ".join([word.capitalize() if len(word) > 2 else word.lower() for word in text.split(delim)])

def sort(what, mycmp):
    return sorted(what, key=cmp_to_key(mycmp))

def sort_alpha(what):
    return sort(what, lambda a, b: (a.upper() > b.upper()) - (a.upper() < b.upper()))

def sort_num(what):
    return sort(what, lambda a, b: int(a) - int(b))

def cmp_to_key(mycmp):
    class K(object):
        def __init__(self, obj, *args):
            self.obj = obj
        def __lt__(self, other):
            return mycmp(self.obj, other.obj) < 0
        def __gt__(self, other):
            return mycmp(self.obj, other.obj) > 0
        def __eq__(self, other):
            return mycmp(self.obj, other.obj) == 0
        def __le__(self, other):
            return mycmp(self.obj, other.obj) <= 0
        def __ge__(self, other):
            return mycmp(self.obj, other.obj) >= 0
        def __ne__(self, other):
            return mycmp(self.obj, other.obj) != 0
    return K


def project_query():
    query = ''

    project = {
        'name': ProjectSettings.get('project.name'),
        'branch': ProjectSettings.get('project.branch')
    }

    anded = []

    if project and 'name' in project and project['name']:
        projects = re.split(',\s*', project['name'])

        anded += [' OR '.join(['project:%s' % name for name in projects])]

    if project and 'branch' in project and project['branch']:
        query += ' '

        branches = re.split(',\s*', project['branch'])

        anded += [' OR '.join(['branch:%s' % name for name in branches])]

    if len(anded) > 0:
        query += ' AND (' + ') AND ('.join(anded) + ')'

    return query


def fix_download_command(command):
    matches = re.match("^(.*)([a-z]+)://([^@]+@)([^:]*):(\d+.*)$", command)

    if matches:
        if not matches.group(4) or matches.group(4) == '/':
            command = '%s%s://%s%s:%s' % (
                matches.group(1),
                matches.group(2),
                matches.group(3),
                urlsplit(Settings.get('connection.url')).netloc.split(':')[0],
                matches.group(5)
            )
        elif matches.group(4)[0] == '/':
            command = '%s%s://%s%s:%s' % (
                matches.group(1),
                matches.group(2),
                matches.group(3),
                matches.group(4)[1:],
                matches.group(5)
            )

    return command

def mkdate(text):
    datestr = re.sub('\.\d+$', '', text)

    return datetime.datetime.fromtimestamp(time.mktime(time.strptime(datestr, "%Y-%m-%d %H:%M:%S")) - time.altzone).strftime("%Y-%m-%d %H:%M:%S")


def is_in_viewport(view, region):
    visible = view.visible_region()
    begin_row, _ = view.rowcol(visible.begin())
    end_row, _ = view.rowcol(visible.end())

    return sublime.Region(view.text_point(begin_row + 1, 0), view.text_point(end_row - 1, 0)).contains(region)
