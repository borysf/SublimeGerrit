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
import webbrowser

from urllib.parse import urlparse

from .base_view import BaseView
from .template import Template
from .utils import quick_panel, capwords, sort, sort_alpha, error_message, info_message, fix_download_command, git_root, mkdate, get_reviewer_name, ellipsis
from .resources import GerritResources
from .settings import Settings
from .reader import DataReader
from .diff_view import DiffView
from .reloader import Reloader
from .git import Git

class ChangeView(BaseView):
    window = None
    detached = False

    @classmethod
    def get_instance_for_change_id(self, change_id):
        for window_id in BaseView.instances:
            for instance in BaseView.instances[window_id]:
                if instance.change_id() == change_id:
                    return instance

        return None

    def __init__(self, change):
        self.opener = sublime.active_window()

        if ChangeView.window is None or ChangeView.window not in sublime.windows():
            if Settings.get('change.separate_window'):
                sublime.run_command('new_window')
                ChangeView.window = sublime.active_window()
                ChangeView.detached = True
            else:
                ChangeView.window = self.opener

        self.view = ChangeView.window.new_file()
        self.view.settings().set('is_sublimegerrit_change_view', True)

        if ChangeView.detached:
            sublime.set_timeout(lambda: self.opener.focus_view(self.view), 200)

        BaseView.__init__(self)

        syntax_file = "/".join(['Packages', 'SublimeGerrit', 'syntax', 'SublimeGerrit.tmLanguage'])
        self.view.set_scratch(True)
        self.view.set_read_only(True)
        self.view.set_syntax_file(syntax_file)
        self.diff_view = None
        self.destroying = False
        self.draft_comments = None
        self.comments = None
        self.resources = GerritResources()
        self.links = []
        self.loading = False
        self.change = None

        view_settings = self.view.settings()
        settings_to_apply = Settings.get('change_view')

        view_settings.set('line_numbers', False)
        view_settings.set('highlight_line', False)
        view_settings.set('gutter', False)
        view_settings.set('caret_extra_top', 0)
        view_settings.set('caret_extra_bottom', 0)
        view_settings.set('caret_extra_width', 0)
        view_settings.set('sublimerge_off', True)

        for name in settings_to_apply:
            view_settings.set(name, settings_to_apply[name])

        self.git = Git(
            change[0]['project'],
            change[0]['branch'],
            change[0]['change_id'],
            self.opener,
            ChangeView.window
        )

        self.prepare(change)
        self.get_comments(self.render)


    def views(self):
        return [self.view]


    def get_comments(self, callback):
        self.comments = self.draft_comments = None

        def done(data, regular):
            if regular:
                store = self.comments = {}
            else:
                store = self.draft_comments = {}

            if data is not None:
                for fname in data:
                    store.update({fname: len(data[fname])})

            if self.comments is not None and self.draft_comments is not None:
                callback()

        revision = self.get_current_rev()

        self.resources.get_comments(self.change['_number'], revision['_number']).then(lambda data: done(data, True))
        self.resources.get_draft_comments(self.change['_number'], revision['_number']).then(lambda data: done(data, False))


    def focus(self):
        if self.view:
            win = self.view.window()
            if win:
                win.focus_view(self.view)


    def change_id(self):
        return self.change['id']


    def prepare(self, change):
        self.render_loader()

        self.loading = True
        self.change = change[0]
        self.change['created'] = mkdate(self.change['created'])
        self.change['updated'] = mkdate(self.change['updated'])

        self.review = {'__MSG__': None}
        self.review_selected = {}

        self_data = self.resources.get_self()

        for label_name in self.change['permitted_labels'].keys():
            self.review.update({label_name: ' 0'})
            self.review_selected.update({label_name: True})

            if label_name in self.change['labels'] and 'all' in self.change['labels'][label_name]:

                for vote in self.change['labels'][label_name]['all']:
                    if self_data is not None and vote['_account_id'] == self_data['_account_id']:
                        value = vote['value']

                        if value > 0:
                            value = '+%d' % value
                        elif value < 0:
                            value = '%d' % value
                        else:
                            value = ' 0'

                        self.review.update({label_name: value})

        self.to_render = []
        self.longest_line = 0

    def render_loader(self):
        if self.change is None:
            self.view.set_name('*GERRIT* Loading...')

        self.view.run_command('sublime_gerrit_clear')
        self.view.run_command('sublime_gerrit_insert', {
            'content': 'Loading...',
            'pos': 0
        })

    def render(self):
        def do_render(submit_type):
            if submit_type is not None:
                self.change.update({'submit_type': capwords(submit_type, '_')})
            else:
                self.change.update({'submit_type': ''})

            self.view.set_name(Template('change_title').applystr(self.change))

            current_rev = self.get_current_rev()
            if self.has_action('rebase'):
                self.insert(['NOTICE: THIS CHANGE IS OUTDATED AND NEEDS REBASE!', '', ''])

            self.render_header()
            self.render_reviewers()
            self.render_depends()
            self.render_current_rev()
            self.render_comments()
            self.finish_render()

            self.loading = False

        self.resources.submit_type(self.change['_number'], self.get_current_rev()['_number']).then(do_render)

    def render_header(self):
        self.change['status'] = 'SUBMITTED, Merge Pending' if self.change['status'] == 'SUBMITTED' else self.change['status']
        self.insert(Template('change_commit_message').apply(self.get_current_rev()))
        self.insert(Template('change_summary').apply(self.change))

    def render_reviewers(self):
        items = {}
        longest = {'name': 0}

        for label_name in self.change['labels']:
            if not label_name in longest:
                longest.update({label_name: 0})

            if 'all' in self.change['labels'][label_name]:
                for reviewer in self.change['labels'][label_name]['all']:
                    name = get_reviewer_name(reviewer)

                    if name not in items:
                        items.update({name: {}})
                        longest['name'] = max(longest['name'], len(name))

                    if 'value' in reviewer:
                        value = ('+' if reviewer['value'] > 0 else '') + str(reviewer['value'])
                    else:
                        value = ''

                    items[name].update({label_name: value})


                    longest[label_name] = max(longest[label_name], len(value))

        if longest['name'] > 0:
            lines = ['Reviewer' + (' ' * (longest['name'] - 8))]
            for label_name in self.change['labels']:
                lines[0] += '  ' + label_name

            for name in items:
                line = name + (' ' * (longest['name'] - len(name)))
                for label_name in items[name]:
                    value = items[name][label_name]
                    value = (' ' * (longest[label_name] - len(value))) + value

                    pad_left = int((len(label_name) - longest[label_name]) / 2)

                    line += '  ' + (' ' * pad_left)
                    line += value

                    line += ' ' * (len(label_name) - len(value) - pad_left)

                lines.append(line)

            lines.append('')

            self.insert(lines)

    def render_depends(self):
        current_rev = self.get_current_rev()

        if 'commit' in current_rev and 'parents' in current_rev['commit'] and len(current_rev['commit']['parents']) > 0:
            self.insert(Template('change_depends_header').apply({}))

            for parent in current_rev['commit']['parents']:
                self.insert(Template('change_depends_item').apply(parent))


    def render_current_rev(self):
        ordered = sort(self.change['revisions'], lambda a, b: self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number'])
        current_rev = self.get_current_rev()

        self.insert(Template('change_patch_sets_header').apply({}))

        for rev in ordered:
            self.change['revisions'][rev].update({'revision': rev})
            self.insert(Template('change_patch_set_header').apply(self.change['revisions'][rev]))

            if 'commit' in current_rev and self.change['revisions'][rev] is current_rev:
                current_rev['commit']['author']['date'] = mkdate(current_rev['commit']['author']['date'])
                current_rev['commit']['committer']['date'] = mkdate(current_rev['commit']['committer']['date'])

                self.insert(Template('change_patch_set_commit').apply(current_rev))

                longest = 0

                ordered_files = sort_alpha(current_rev['files'])

                for filename in current_rev['files']:
                    item = current_rev['files'][filename]
                    filename = ((item['old_path'] + ' -> ') if 'old_path' in item else '') + filename
                    longest = max(longest, len(filename))

                for filename in ordered_files:
                    item = current_rev['files'][filename]
                    lines = []

                    if 'status' not in item:
                        item.update({'status': 'M'})

                    if 'lines_inserted' in item:
                        lines.append('+%d' % item['lines_inserted'])
                    else:
                        lines.append('+0')

                    if 'lines_deleted' in item:
                        lines.append('-%d' % item['lines_deleted'])
                    else:
                        lines.append('-0')

                    name = ((item['old_path'] + ' -> ') if 'old_path' in item else '') + filename

                    comments = self.comments_count_text(filename)
                    item.update({
                        'lines_total': ', '.join(lines),
                        'filename': name + (' ' * (longest - len(name))),
                        'draft_comments': '(' + comments + ')' if comments else ''
                    })

                    self.insert(Template('change_patch_set_file').apply(item))


    def comments_count_text(self, filename):
        comments = []

        if self.draft_comments is not None:
            if filename in self.draft_comments:
                count = self.draft_comments[filename]
                comments.append('%d draft%s' % (count, 's' if count > 1 else ''))

        if self.comments is not None:
            if filename in self.comments:
                count = self.comments[filename]
                comments.append('%d comment%s' % (count, 's' if count > 1 else ''))

        return ', '.join(comments)


    def render_comments(self):
        self.insert(Template('change_comments_header').apply({}))

        for msg in reversed(self.change['messages']) if Settings.get('change.reverse_comments') else self.change['messages']:
            msg['author_name'] = msg['author_name'] or msg['author_username'] or msg['author_email'] or 'Gerrit Code Review'
            msg['date'] = mkdate(msg['date'])
            self.insert(Template('change_comment_message').apply(msg))


    def insert(self, content, pos=None):
        for part in content:
            for line in part.split('\n'):
                self.longest_line = max(self.longest_line, len(line))

        self.to_render += content

    def finish_render(self):
        self.view.run_command('sublime_gerrit_clear')

        for i in range(0, len(self.to_render)):
            if self.to_render[i] == '--':
                self.to_render[i] = '-' * self.longest_line

        self.view.run_command('sublime_gerrit_insert', {
            'pos': 0,
            'content': "\n".join(self.to_render)
        })

        self.find_links()


    def display_download_menu(self):
        current_rev = self.get_current_rev()
        items = []

        if 'fetch' in current_rev:
            command = None

            tries = [
                Settings.get('git.quick_checkout_default_protocol'),
                'git',
                'ssh',
                'http',
                'anonymous http'
            ]

            for proto in tries:
                if proto in current_rev['fetch']:
                    commands = current_rev['fetch'][proto]['commands']

                    if 'Checkout' in commands:
                        command = commands['Checkout']
                    elif 'Pull' in commands:
                        command = commands['Pull']

                    if command is not None:
                        break

            if command is not None:
                items = [{
                    'caption': ['Quick Checkout'],
                    'command': fix_download_command(command),
                    'on_select': lambda selected: self.git.checkout(selected['command'])
                }]

            for via in self.get_current_rev()['fetch']:
                items.append({
                    'caption': ['Download via %s' % via.upper()],
                    'via': via,
                    'on_select': lambda selected: self.display_download_menu_via(selected['via'])
                })

        if len(items) == 0:
            error_message('No download commands could be found. Check if Gerrit server has installed `download-commands` plugin.');
            return

        quick_panel(items)


    def display_download_menu_via(self, via):
        def set_clipboard(data):
            sublime.set_clipboard(data)
            sublime.status_message('Copied to clipboard: `%s`' % data)
            sublime.set_timeout(lambda: sublime.status_message(''), 4000)

        def sorter(a, b):
            a = a.upper()
            b = b.upper()

            return (a > b) - (a < b)

        current_rev = self.get_current_rev()

        items = []

        for command_name in sort(current_rev['fetch'][via]['commands'].keys(), sorter):
            command = fix_download_command(current_rev['fetch'][via]['commands'][command_name])

            items.append({
                'caption': [command_name, command],
                'command_name': command_name.lower(),
                'command': command,
                'on_select': lambda selected: set_clipboard(selected['command'])
            })

        quick_panel(items)


    def display_switch_ps_menu(self):
        def switch_ps(change, revision_id):
            change[0]['current_revision'] = revision_id
            self.refresh(change)

        items = []

        ordered = sort(self.change['revisions'], lambda a, b: self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number'])

        for rev in ordered:
            revision = self.change['revisions'][rev]

            if revision is not self.get_current_rev():
                items.append({
                    'caption': ['Patch Set %d' % revision['_number']],
                    'rev': rev,
                    'on_select': lambda item: self.resources.change(self.change['_number']).then(lambda data: switch_ps(data, item['rev']))
                })

        quick_panel(items)


    def is_current_ps(self):
        if 'current_revision' not in self.change or not self.change['current_revision']:
            return True

        ordered = sort(self.change['revisions'], lambda a, b: self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number'])

        return self.change['current_revision'] == ordered[-1]


    def display_review_menu(self, only_label=None):
        if self.destroying:
            return

        items = []

        def on_select(item, erase):
            self.review[item['label']] = item['value']
            self.review_selected[item['label']] = not erase
            self.display_review_menu(
                only_label=item['label'] if erase else None
            )

        def add_cover_message(text):
            self.review['__MSG__'] = text
            self.display_review_menu()

        show_submission = True

        if self.is_current_ps():
            for label_name in self.review:
                if label_name != '__MSG__' and (only_label is None or only_label == label_name):
                    if self.review_selected[label_name]:
                        try:
                            current_label_text = self.change['labels'][label_name]['values'][self.review[label_name]]
                        except:
                            self.review[label_name] = ' 0'
                            current_label_text = self.change['labels'][label_name]['values'][self.review[label_name]]

                        items.append({
                            'caption': [
                                '%s: %s' % (label_name, self.review[label_name].strip()),
                                current_label_text
                            ],
                            'value': self.review[label_name],
                            'label': label_name,
                            'on_select': lambda item: on_select(item, True)
                        })
                    else:
                        show_submission = False

                        for value in reversed(self.change['permitted_labels'][label_name]):
                            items.append({
                                'caption': [
                                    '%s: %s' % (label_name, value.strip()),
                                    self.change['labels'][label_name]['values'][value]
                                ],
                                'selected': (
                                    label_name in self.review and value == self.review[label_name]
                                ),
                                'value': value,
                                'label': label_name,
                                'on_select': lambda item: on_select(item, False)
                            })

                    self.review_selected[label_name] = True

        if show_submission:
            items.append({
                'caption': [
                    'Add Cover Message' if self.review['__MSG__'] is None else 'Change Cover Message',
                    ellipsis(self.review['__MSG__']) or '<Message not set>'
                ],
                'on_select': lambda item:
                    sublime.set_timeout(
                        lambda: ChangeView.window.show_input_panel(
                            'Cover Message',
                            self.review['__MSG__'] or '',
                            add_cover_message,
                            None,
                            self.display_review_menu
                        )
                    , 100)
            })

            items.append({
                'caption': ['Publish Comments', 'Publishes comments only, does not merge into repository'],
                'on_select': self.publish_comments
            })

            if self.has_action('submit'): # and self.change['status'] in ['NEW']:
                items.append({
                    'caption': ['Publish and Submit', 'Publishes comments and merges into repository'],
                    'on_select': self.publish_and_submit
                })

        quick_panel(items)


    def publish_comments(self, item, then=None):
        review = {'labels': {}}

        for label in self.review:
            if label != '__MSG__':
                review['labels'].update({label: int(self.review[label].strip())})
            elif self.review[label] and self.review[label].strip():
                review['message'] = self.review[label].strip()

        if then is None:
            then = lambda data: self.reload()

        def submit(comments):
            review.update({'comments': comments})

            self.resources.review(
                self.change['_number'],
                self.get_current_rev()['_number'],
                review
            ).then(then)

        self.resources.get_draft_comments(
            self.change['_number'],
            self.get_current_rev()['_number']
        ).then(submit)




    def publish_and_submit(self, item):
        def on_done(data):
            self.reload()

            if data is not None and 'status' in data:
                info_message('Change status: ' + data['status'])

        self.publish_comments(item, lambda data: self.resources.submit(
            self.change['_number'],
            self.get_current_rev()['_number']
        ).then(on_done))


    def rebase(self):
        self.resources.rebase(
            self.change['_number'],
            self.get_current_rev()['_number'],
        ).then(lambda data: self.reload())


    def abandon(self):
        if sublime.ok_cancel_dialog('SublimeGerrit\n\nAre you sure you want to abandon this change?'):
            self.resources.abandon(
                self.change['_number']
            ).then(lambda data: self.reload())

    def publish(self):
        self.resources.publish(
            self.change['_number']
        ).then(lambda data: self.reload())

    def delete(self):
        if sublime.ok_cancel_dialog('SublimeGerrit\n\nAre you sure you want to delete this draft change?'):
            self.resources.delete(
                self.change['_number']
            ).then(lambda data: self.destroy())

    def restore(self):
        self.resources.restore(
            self.change['_number']
        ).then(lambda data: self.reload())


    def reload(self):
        if self.loading:
            return

        self.render_loader()
        self.resources.change(self.change['_number']).then(self.refresh)


    def refresh(self, data=None):
        if self.loading:
            return

        if data is None:
            data = [self.change]

        self.prepare(data)

        self.get_comments(self.render)

    def get_current_rev_id(self):
        if self.change['current_revision']:
            return self.change['current_revision']
        else:
            ordered = sort(self.change['revisions'],
                lambda a, b: self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number']
            )

            return ordered[0]

    def get_current_rev(self):
        if self.change['current_revision']:
            return self.change['revisions'][self.change['current_revision']]
        else:
            ordered = sort(self.change['revisions'],
                lambda a, b: self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number']
            )

            return self.change['revisions'][ordered[0]]

    def has_action(self, action):
        current_rev = self.get_current_rev()

        if 'actions' in current_rev and action in current_rev['actions'] and current_rev['actions'][action]['enabled']:
            return current_rev['actions'][action]

        if (
            len(self.change['actions']) == 1 and
            action in self.change['actions'][0] and
            self.change['actions'][0][action] and
            'enabled' in self.change['actions'][0][action] and
            self.change['actions'][0][action]['enabled']
        ):
            return self.change['actions'][0][action]

        return False

    def delete_topic(self):
        pass

    def set_topic(self):
        def submit(topic):
            if topic:
                self.resources.set_topic(self.change['_number'], topic).then(
                    lambda data: self.reload()
                )
            else:
                self.resources.delete_topic(self.change['_number']).then(
                    lambda data: self.reload()
                )

        ChangeView.window.show_input_panel('Topic', self.change['topic'], submit, None, None)

    def display_remove_reviewers_menu(self):
        items = []
        for reviewer in self.change['removable_reviewers']:
            item = [get_reviewer_name(reviewer)]

            if 'email' in reviewer:
                item.append(reviewer['email'])

            items.append({
                'caption': item,
                'account_id': reviewer['_account_id'],
                'on_select': lambda selected: self.remove_reviewer(selected['account_id'])
            })

        quick_panel(items)

    def remove_reviewer(self, account_id):
        self.resources.remove_reviewer(self.change['_number'], account_id).then(lambda data: self.reload())


    def display_add_reviewer_menu(self):
        def menu(data, text):
            if len(data) > 0:
                items = []

                for reviewer in data:
                    items.append({
                        'caption': [reviewer['group_name'] or reviewer['account_name'], reviewer['email']],
                        'id': reviewer['group_id'] or reviewer['account_id'],
                        'on_select': lambda selected: self.add_reviewer(selected['id'])
                    })

                quick_panel(items, on_cancel=lambda: prompt(text))
            else:
                error_message('No reviewer match your query.')
                prompt(text)

        def get_suggestions(text):
            if text:
                self.resources.suggest_reviewers(self.change['id'], text, 10).then(lambda data: menu(data, text))

        def prompt(text=''):
            ChangeView.window.show_input_panel('Name or Email or Group', text, get_suggestions, None, None)

        prompt()


    def add_reviewer(self, account_id):
        self.resources.add_reviewer(self.change['_number'], account_id).then(lambda data: self.reload())


    def display_changes_menu(self):
        current_rev = self.get_current_rev()
        items = []

        ordered = sort_alpha(current_rev['files'])

        for filename in ordered:
            f = current_rev['files'][filename]

            if 'binary' in f:
                continue

            comments = self.comments_count_text(filename)

            items.append({
                'caption': [filename, f['status'] + ' ' + f['lines_total'] + ((', ' + comments) if comments else '')],
                'filename': filename,
                'status': f['status'],
                'on_select': lambda selected: self.open_diff(selected['status'], selected['filename'])
            })

        quick_panel(items)

    def open_diff(self, status, filename):
        if self.diff_view is not None:
            self.diff_view.destroy()

        ordered = sort(self.change['revisions'], lambda a, b:
            self.change['revisions'][a]['_number'] - self.change['revisions'][b]['_number']
        )

        revisions = [self.change['revisions'][rev] for rev in ordered]

        self.diff_view = DiffView(
            self.view,
            self.change['_number'],
            self.get_current_rev(),
            filename,
            revisions
        )

    def edit_commit_message(self):
        current_rev = self.get_current_rev()

        text = current_rev['commit']['message'] if 'commit' in current_rev and 'message' in current_rev['commit'] else ''

        ChangeView.window.show_input_panel(
            'Commit Message',
            text,
            lambda text:
                self.resources.edit_commit_message(
                    self.change['_number'],
                    current_rev['revision'],
                    text
                ).then(lambda data: self.reload()),
            None,
            None
        )

    def cherry_pick(self):
        current_rev = self.get_current_rev()

        def on_done(data):
            if data is not None:
                if sublime.ok_cancel_dialog('SublimeGerrit\n\nCherry Pick successful!\nWould you like to view the cherry picked change now?'):
                    self.resources.change(data[0]['_number']).then(lambda change: ChangeView(change))

        def submit(ref, message):
            self.resources.cherry_pick_to(self.change['_number'], current_rev['_number'], ref, message).then(on_done)

        def display_branches_menu(data):
            items = []
            for branch in data:
                matches = re.match('^refs/heads/(.+)$', branch['ref'])

                if matches and matches.group(1) != self.change['branch']:
                    items.append({
                        'caption': [matches.group(1), branch['revision']],
                        'ref': matches.group(1),
                        'on_select': prompt
                    })

            if len(items) > 0:
                quick_panel(items)
            else:
                error_message('No other branches than `%s` known to Gerrit.' % self.change['branch'])

        def prompt(selected):
            text = current_rev['commit']['message'] if 'commit' in current_rev and 'message' in current_rev['commit'] else ''

            ChangeView.window.show_input_panel('Cherry Pick Commit Message', text, lambda text: submit(selected['ref'], text), None, None)

        self.resources.project_branches(self.change['project']).then(display_branches_menu)


    def find_links(self):
        self.links = []
        regex = re.compile("\\bhttps?://[-a-z0-9+&@#/%?=~_()|!:,.;]*[-a-z0-9+&@#/%=~_(|]", re.IGNORECASE)

        for match in regex.finditer(self.view.substr(sublime.Region(0, self.view.size()))):
            link = {
                'region': sublime.Region(match.start(), match.start() + len(match.group())),
                'link': match.group()
            }

            self.links.append(link)
            self.view.add_regions(
                'link-%d' % match.start(),
                [link['region']],
                self.view.scope_name(match.start()),
                '',
                sublime.DRAW_SOLID_UNDERLINE | sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE | sublime.HIDE_ON_MINIMAP
            )


    def destroy(self, unloading=False):
        if self.destroying:
            return

        self.destroying = True

        # forces all panels that could be left by the view to be closed
        ChangeView.window.get_output_panel('fake-close')
        ChangeView.window.run_command('show_panel', {'panel': 'output.fake-close'})
        ChangeView.window.run_command('hide_panel', {'panel': 'output.fake-close'})

        if self.view.window():
            w = self.view.window()

            w.focus_view(self.view)
            w.run_command('close')

        if not unloading and self.git.is_applied():
            self.git.revert()

        if self.diff_view is not None:
            self.diff_view.destroy()
            self.diff_view = None

        BaseView.destroy(self)

        if ChangeView.detached:
            if len(ChangeView.window.views()) == 0:
                ChangeView.window.run_command('close_window')



    def download_cmd(self):
        return self.display_download_menu if not self.git.is_applied() else False

    def revert_checkout_cmd(self):
        return self.git.revert if self.git.is_applied() else False

    def review_cmd(self):
        return self.display_review_menu if self.has_action('submit') or len(self.change['permitted_labels'].keys()) > 0 else False

    def view_changes_cmd(self):
        cr = self.get_current_rev()

        return self.display_changes_menu if len([f for f in cr['files'] if 'binary' not in cr['files'][f] or not cr['files'][f]['binary']]) > 0 else False

    def switch_patch_set_cmd(self):
        return self.display_switch_ps_menu if len(self.change['revisions'].keys()) > 1 else False

    def add_reviewer_cmd(self):
        return self.display_add_reviewer_menu if self.change['status'] not in ['ABANDONED', 'MERGED'] else False

    def remove_reviewer_cmd(self):
        return self.display_remove_reviewers_menu if self.change['status'] not in ['ABANDONED', 'MERGED'] and len(self.change['removable_reviewers']) > 0 else False

    def rebase_cmd(self):
        return self.rebase if self.has_action('rebase') else False

    def abandon_cmd(self):
        return self.abandon if self.has_action('abandon') else False

    def publish_draft_cmd(self):
        return self.publish if self.has_action('publish') and self.change['status'] not in ['ABANDONED'] else False

    def delete_draft_cmd(self):
        del_action = self.has_action('/')

        return self.delete if del_action and del_action['method'] == 'DELETE' and re.match('^Delete draft change', del_action['title']) else False

    def restore_cmd(self):
        return self.restore if self.has_action('restore') else False

    def edit_commit_message_cmd(self):
        return self.edit_commit_message if self.has_action('message') else False

    def edit_topic_cmd(self):
        return self.set_topic

    def cherry_pick_cmd(self):
        return self.cherry_pick if self.has_action('cherrypick') else False

    def refresh_cmd(self):
        return self.reload



    def on_selection_modified(self, view):
        def switch_ps(change, revision_id):
            change[0]['current_revision'] = revision_id
            self.refresh(change)

        sel = self.view.sel()

        if len(sel) == 1:
            text = self.view.substr(sel[0])

            if sel[0].size() > 0:
                for link in self.links:
                    if link['region'].contains(sel[0]):
                        sel.clear()
                        webbrowser.open(link['link'], autoraise=True)
                        return

            if re.match('^[a-zA-Z0-9]{40,}$', text):
                if text in self.change['revisions']:
                    if not self.loading:
                        self.resources.change(self.change['_number']).then(lambda data: switch_ps(data, text))

                    return

                ChangeView.window.run_command('sublime_gerrit_search', {
                    'text': text,
                    'autorun': True
                })

    def on_modified(self, view):
        pass

    def on_activated(self, view):
        if self.diff_view is not None:
            self.diff_view.focus()

    def on_deactivated(self, view):
        pass

    def on_close(self, view):
        self.destroy()
