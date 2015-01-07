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
import re
from urllib.parse import urlencode

from .client import GerritClient
from .resources import GerritResources
from .utils import get_labels, error_message, info_message, quick_panel, quick_menu, project_query, git_root, mkdate
from .template import Template
from .settings import Settings, ProjectSettings, ConnectionSettings
from .change_view import ChangeView
from .diff_view import DiffView
from .git import GitPush

resources = GerritResources()

class _DiffCommand(sublime_plugin.WindowCommand):
    callback = False

    def is_enabled(self, **kwargs):
        return self.is_visible(**kwargs)

    def is_visible(self, **kwargs):
        if not isinstance(ChangeView.get_active_instance(), DiffView):
            return False

        self.callback = self.get_callback(**kwargs)

        return self.callback is not False

    def get_callback(self, **kwargs):
        return False

    def run(self, **kwargs):
        if self.callback:
            self.callback(**kwargs)

class _ChangeCommand(sublime_plugin.WindowCommand):
    callback = False

    def is_enabled(self, **kwargs):
        return self.is_visible(**kwargs)

    def is_visible(self, **kwargs):
        if not isinstance(ChangeView.get_active_instance(), ChangeView):
            return False

        self.callback = self.get_callback(**kwargs)

        return self.callback is not False

    def get_callback(self, **kwargs):
        return True

    def run(self, **kwargs):
        if self.callback:
            self.callback(**kwargs)

class _EditorCommand(sublime_plugin.WindowCommand):
    def is_enabled(self):
        return self.is_visible()

    def is_visible(self):
        return ChangeView.get_active_instance() is None


class SublimeGerritMenuCommand(sublime_plugin.WindowCommand):
    def run(self):
        items = Settings.get('main_menu_entries')

        def on_select(index):
            if index > -1:
                self.window.run_command('sublime_gerrit_%s' % items[index]['command'], items[index]['args'])


        self.window.show_quick_panel([item['description'] for item in items], on_select)


# EDITOR COMMANDS
class SublimeGerritDashboardCommand(_EditorCommand):
    def run(self, query='status:open', limit=25):
        query += project_query()

        def display_menu(changes):
            if changes is None:
                return

            if len(changes) > 0:
                items = []

                template = Template('dashboard_item')

                for change in changes:
                    change.update({
                        'updated': mkdate(change['updated']),
                        'created': mkdate(change['created'])
                    })

                    items.append({
                        'caption': template.apply(change) + get_labels(change),
                        'change': change
                    })

                quick_panel(items, lambda selected_item: self.load_change(selected_item['change']))
            else:
                error_message('There are no items to display')

        resources.changes(limit, {'q': query}).then(display_menu)

    def load_change(self, change):
        def display_change(change):
            ChangeView(change)

        instance = ChangeView.get_instance_for_change_id(change['id'])

        if instance and instance.view.window():
            instance.reload()
            instance.focus()
        else:
            resources.change(change['_number']).then(display_change)

    def description(self):
        return 'SublimeGerrit: Dashboard List'


class SublimeGerritSearchCommand(_EditorCommand):
    def run(self, text='', autorun=False):
        if text and autorun:
            self.search(text)
            return

        self.window.show_input_panel('Change #, SHA-1, tr:id or owner:email, etc.', text, self.search, None, None)

    def search(self, text):
        self.window.run_command('sublime_gerrit_dashboard', {
            'query': text,
            'limit': 100
        })


class SublimeGerritSetupCommand(_EditorCommand):
    def run(self, confirm=False):
        if not confirm or sublime.ok_cancel_dialog('SublimeGerrit\n\nWould you like to perform basic setup now?'):
            self.project_settings = ProjectSettings()

            self.dirty_settings = {
                'connection': {
                    'username': ConnectionSettings.get('username'),
                    'password': ConnectionSettings.get('password'),
                    'url': ConnectionSettings.get('url'),
                    'timeout': ConnectionSettings.get('timeout')
                },

                'project': {
                    'name': ProjectSettings.get('project.name') or '',
                    'branch': ProjectSettings.get('project.branch') or ''
                },

                'notifications': {
                    'check_interval': Settings.get('notifications.check_interval'),
                    'check_limit': Settings.get('notifications.check_limit'),
                    'check_query': Settings.get('notifications.check_query')
                },

                'git': {
                    'executable_path': Settings.get('git.executable_path'),
                    'default_args': Settings.get('git.default_args')
                }
            }

            connection = self.dirty_settings['connection']
            project = self.dirty_settings['project']
            notifications = self.dirty_settings['notifications']
            git = self.dirty_settings['git']

            def set_value(data, key, value):
                data[key] = value

            def validate_url(url):
                url = url.strip('/')

                if not re.match('^https?://[^:]+(:\d+)?(/.*)?', url):
                    raise Exception('Invalid Url')

                return url

            items = [{
                'caption': ['General'],
                'items': [{
                    'caption': ['Connection'],
                    'items': [{
                        'caption': ['Username', connection['username'] if 'username' in connection and connection['username'] else '<empty> - connect anonymously'],
                        'default': '<empty> - connect anonymously',
                        'on_select': lambda selected, restore: self.edit('connection', 'username', selected, restore)
                    }, {
                        'caption': ['Password', connection['password'] if 'password' in connection and connection['password'] else '<empty> - connect anonymously'],
                        'default': '<empty> - connect anonymously',
                        'on_select': lambda selected, restore: self.edit('connection', 'password', selected, restore)
                    }, {
                        'caption': ['Url', connection['url'] if 'url' in connection else ''],
                        'on_select': lambda selected, restore: self.edit('connection', 'url', selected, restore),
                        'value': validate_url
                    }, {
                        'caption': ['Timeout', connection['timeout'] if 'timeout' in connection else ''],
                        'on_select': lambda selected, restore: self.edit('connection', 'timeout', selected, restore),
                        'value': lambda value: int(value)
                    }]
                }, {
                    'caption': ['Notifications'],
                    'items': [{
                        'caption': ['Check Interval (seconds)', str(notifications['check_interval'])],
                        'on_select': lambda selected, restore: self.edit('notifications', 'check_interval', selected, restore),
                        'value': lambda value: int(value)
                    }, {
                        'caption': ['Limit', str(notifications['check_limit'])],
                        'on_select': lambda selected, restore: self.edit('notifications', 'check_limit', selected, restore),
                        'value': lambda value: int(value)
                    }, {
                        'caption': ['Query', str(notifications['check_query'])],
                        'on_select': lambda selected, restore: self.edit('notifications', 'check_query', selected, restore)
                    }]
                }, {
                    'caption': ['Git'],
                    'items': [{
                        'caption': ['Git Executable Path', git['executable_path']],
                        'on_select': lambda selected, restore: self.edit('git', 'executable_path', selected, restore)
                    }, {
                        'caption': ['Git Default Arguments', git['default_args']],
                        'on_select':  lambda selected, restore: self.edit('git', 'default_args', selected, restore)
                    }]
                }]
            }, {
                'caption': ['Project'],
                'items': [{
                    'caption': ['Project Name', project['name'] if 'name' in project and project['name'] else '<empty> - all accessible projects will be listed'],
                    'default': '<empty> - all accessible projects will be listed',
                    'on_select': lambda selected, restore: self.edit('project', 'name', selected, restore)
                }, {
                    'caption': ['Branch Name', project['branch'] if 'branch' in project and project['branch'] else '<empty> - all branches will be listed'],
                    'default': '<empty> - all branches will be listed',
                    'on_select': lambda selected, restore: self.edit('project', 'branch', selected, restore)
                }]
            }]

            quick_menu(items)

    def save_config(self, config):
        Settings.save('connection', config['connection'])
        Settings.save('notifications', config['notifications'])
        Settings.save('git', config['git'])
        ProjectSettings.save('project', config['project'])

        # if not ProjectSettings.persistable():
        #     error_message('Project-specific settings saved for current session only. To have these settings stored permanently, please create a new project and save it to a file first.')

    def edit(self, key, name, selected, restore):
        def save(value):
            if 'value' in selected:
                try:
                    value = selected['value'](value)
                except:
                    restore()
                    return

            self.dirty_settings[key].update({name: value})
            # Settings.set(key, self.dirty_settings[key])

            if not value and 'default' in selected:
                selected['caption'][1] = selected['default']
            else:
                selected['caption'][1] = value


            def on_connect(data):
                if isinstance(data, list):
                    self.save_config(self.dirty_settings)
                    info_message('Connection successful! Connection settings saved.')

                restore()

            if key == 'connection':
                if ConnectionSettings.is_connectable(self.dirty_settings['connection']):
                    resources.test(self.dirty_settings['connection']).then(on_connect)
                    return

            else:
                self.save_config(self.dirty_settings)

            restore()

        value = selected['caption'][1]

        if 'default' in selected and value == selected['default']:
            value = ''


        sublime.set_timeout(lambda: self.window.show_input_panel(selected['caption'][0], value, save, None, restore), 10)

class SublimeGerritPush(_EditorCommand):
    def run(self, drafts=False):
        GitPush().push(drafts)

# DIFF VIEW COMMANDS
class SublimeGerritDiffNextFileCommand(_DiffCommand):
    def get_callback(self, direction):
        return DiffView.get_active_instance().load_next_file_cmd(direction)

    def description(self, direction):
        return 'Gerrit: Next File' if direction == 1 else 'Gerrit: Previous File'

class SublimeGerritDiffNextChangeCommand(_DiffCommand):
    def get_callback(self, direction):
        return DiffView.get_active_instance().show_next_change_cmd(direction)

    def description(self, direction):
        return 'Gerrit: Next Change' if direction == 1 else 'Gerrit: Previous Change'

class SublimeGerritDiffToggleIntralinesCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().toggle_intralines_cmd()

    def description(self):
        return 'Gerrit: Toggle Intralines'

class SublimeGerritDiffBaseChangeMenuCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().show_base_change_menu_cmd()

    def description(self):
        return 'Gerrit: Base Patch Set: %s' % DiffView.get_active_instance().get_base_name()

class SublimeGerritDiffCommentsMenuCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().view_comments_cmd()

    def description(self):
        return 'Gerrit: View Comments'

class SublimeGerritDiffDraftsMenuCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().view_drafts_cmd()

    def description(self):
        return 'Gerrit: View Drafts'

class SublimeGerritDiffFilesMenuCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().show_file_change_menu_cmd()

    def description(self):
        return 'Gerrit: Switch File'

class SublimeGerritDiffExploreChangesCommand(_DiffCommand):
    def get_callback(self):
        return DiffView.get_active_instance().show_changes_menu_cmd()

    def description(self):
        return 'Gerrit: Explore Changes'


#CHANGE VIEW COMMANDS
class SublimeGerritChangedFilesMenuCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().view_changes_cmd()

    def description(self):
        return 'Gerrit: View Changed Files'

class SublimeGerritEditTopicCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().edit_topic_cmd()

    def description(self):
        return 'Gerrit: Edit Topic'

class SublimeGerritDownloadMenuCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().download_cmd()

    def description(self):
        return 'Gerrit: Download'

class SublimeGerritSwitchPatchSetCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().switch_patch_set_cmd()

    def description(self):
        return 'Gerrit: Switch Patch Set'

class SublimeGerritReviewChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().review_cmd()

    def description(self):
        return 'Gerrit: Review'

class SublimeGerritRevertCheckoutCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().revert_checkout_cmd()

    def description(self):
        return 'Gerrit: Revert Checkout'

class SublimeGerritRebaseChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().rebase_cmd()

    def description(self):
        return 'Gerrit: Rebase'

class SublimeGerritAbandonChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().abandon_cmd()

    def description(self):
        return 'Gerrit: Abandon'

class SublimeGerritPublishDraftCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().publish_draft_cmd()

    def description(self):
        return 'Gerrit: Publish Draft'

class SublimeGerritDeleteDraftCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().delete_draft_cmd()

    def description(self):
        return 'Gerrit: Delete Draft'

class SublimeGerritRestoreChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().restore_cmd()

    def description(self):
        return 'Gerrit: Restore'

class SublimeGerritEditCommitMessageCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().edit_commit_message_cmd()

    def description(self):
        return 'Gerrit: Edit Commit Message'

class SublimeGerritCherryPickChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().cherry_pick_cmd()

    def description(self):
        return 'Gerrit: Cherry Pick To...'

class SublimeGerritRefreshChangeCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().refresh_cmd()

    def description(self):
        return 'Gerrit: Refresh'

class SublimeGerritAddReviewerCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().add_reviewer_cmd()

    def description(self):
        return 'Gerrit: Add Reviewer'

class SublimeGerritRemoveReviewerCommand(_ChangeCommand):
    def get_callback(self):
        return ChangeView.get_active_instance().remove_reviewer_cmd()

    def description(self):
        return 'Gerrit: Remove Reviewer'


# OTHER COMMANDS
class SublimeGerritInsertCommand(sublime_plugin.TextCommand):
    def run(self, edit, content, pos):
        self.view.set_read_only(False)
        self.view.insert(edit, int(pos), content)
        self.view.set_read_only(True)

class SublimeGerritClearCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), '')
        self.view.set_read_only(True)


class SublimeGerritMainCommand(sublime_plugin.WindowCommand):
    def run(self):
        if not ConnectionSettings.is_connectable():
            self.window.run_command('sublime_gerrit_setup', {'confirm': True})
        else:
            instance = DiffView.get_active_instance() or ChangeView.get_active_instance()

            if instance is None:
                command = Settings.get('main_command')

                self.window.run_command('sublime_gerrit_%s' % command['command'], command['args'])
            else:
                self.window.run_command('show_overlay', {'overlay': 'command_palette', 'text': 'Gerrit: '})
                # self.display_commands_menu()


    def get_class(self):
        name = Settings.get('main_command')['command']
        try:
            return globals()['SublimeGerrit' + name[0].upper() + name[1:] + 'Command']
        except:
            error_message('Unknown command: %s' % name)

    def description(self):
        Class = self.get_class()
        if Class:
            return Class(self.window).description()

    def is_enabled(self):
        Class = self.get_class()
        if Class:
            return Class(self.window).is_enabled()

        return False

    def is_visible(self):
        Class = self.get_class()
        if Class:
            return Class(self.window).is_visible()

        return False
