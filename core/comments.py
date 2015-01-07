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
from time import sleep

from .resources import GerritResources
from .utils import mkdate, sort_num, quick_panel, is_in_viewport, get_reviewer_name, ellipsis
from .settings import Settings

class Comment():
    ICON = 'comment.png'
    ICON_PATH = 'Packages/SublimeGerrit/icons/'
    REGION_NAME_PATTERN = '1-comment-%d-icon'

    def __init__(self, comment, collection):
        self.id = comment['id']
        if 'line' in comment and comment['line'] > 0:
            self.original_line = self.line = comment['line']
        else:
            self.line = 1
            self.original_line = 0

        self.message = comment['message']
        self.updated = mkdate(comment['updated'])
        self.author = comment['author'] if 'author' in comment else None
        self.region = None
        self.region_name = None
        self.collection = collection
        self.destroyed = False
        self.editing = False

        self.draw()

    def destroy(self):
        self.destroyed = True
        self.collection.view.erase_regions(self.region_name)

    def draw(self, active=False):
        if self.destroyed:
            return

        view_line = self.collection.real_to_view[self.line]

        if self.region is None:
            point = self.collection.view.text_point(view_line, 0)
            self.region = self.collection.view.line(sublime.Region(point, point))
            self.region_name = self.REGION_NAME_PATTERN % view_line

        def draw():
            if self.destroyed: # when destroyed during timeouts, clear region and dont draw
                self.destroy()
                return

            self.collection.view.add_regions(
                self.region_name,
                [self.region],
                Settings.get('diff.comment_icon_inactive' if not active else 'diff.comment_icon_active'),
                self.ICON_PATH + self.ICON,
                sublime.HIDDEN
            )

        for i in range(0, 7): # redraw a few times to make sure it will be painted... damn st gutter issue
            sublime.set_timeout(lambda: draw(), 10 * i)


    def update_message(self, message, in_reply_to = None):
        def update_message(data):
            self.message = message

        resources = GerritResources()

        if not message:
            resources.delete_draft_comment(
                self.collection.change_id,
                self.collection.alternate_revision_id if self.collection.revision_id is None else self.collection.revision_id,
                self.get_id()
            ).then(lambda data: self.collection.erase_comment(self))
        else:
            resources.update_draft_comment(
                self.collection.change_id,
                self.collection.alternate_revision_id if self.collection.revision_id is None else self.collection.revision_id,
                self.collection.side,
                self.get_id(),
                self.collection.file_name,
                self.get_line(),
                message,
                in_reply_to
            ).then(update_message)

    def hide(self):
        self.collection.view.erase_regions(self.region_name)

    def show(self):
        self.draw()

    def scroll_to(self):
        if not is_in_viewport(self.collection.view, self.region):
            self.collection.view.show_at_center(sublime.Region(self.region.begin(), self.region.begin()))

    def get_id(self):
        return self.id

    def get_line(self):
        return self.line

    def get_original_line(self):
        return self.original_line

    def get_author(self):
        return get_reviewer_name(self.author) if self.author is not None else 'Me'

    def get_message(self):
        return self.message

    def get_updated(self):
        return self.updated


class DraftComment(Comment):
    ICON = 'draft.png'
    REGION_NAME_PATTERN = '1-comment-%d-icon'

    def destroy(self):
        line = self.get_line()
        comments = self.collection.get_comments(real_line=line)

        Comment.destroy(self)

        if comments is not None:
            comments[line][0].draw()

class CommentsStore():
    def __init__(self, view_parent, view_revision, lines_parent, lines_revision, file_name, change_id, revision_id, base, load_callback=None):
        self.change_id = change_id
        self.revision_id = revision_id
        self.base = base
        self.file_name = file_name
        self.resources = GerritResources()
        self.loaded_comments = False
        self.loaded_drafts = False
        self.load_callback = load_callback
        self.count_by_file = {}

        self.sides = {
            'PARENT': CommentsCollection('PARENT', view_parent, lines_parent, file_name, change_id, self),
            'REVISION': CommentsCollection('REVISION', view_revision, lines_revision, file_name, change_id, self)
        }

        self.load()

    def destroy(self):
        self.sides['PARENT'].destroy()
        self.sides['REVISION'].destroy()

    def load(self):
        if self.base is None:
            self.resources.get_comments(self.change_id, self.revision_id).then(self.on_load_comments)
            self.resources.get_draft_comments(self.change_id, self.revision_id).then(self.on_load_drafts)
        else:
            self.sides['PARENT'].load(self.base, self.revision_id, load_callback=lambda collection: self.load_callback is not None and self.load_callback(self))
            self.sides['REVISION'].load(self.revision_id, load_callback=lambda collection: self.load_callback is not None and self.load_callback(self))

    def get_collection_by_view(self, view):
        if view in [self.sides['PARENT'].get_view()]:
            return self.sides['PARENT']
        elif view in [self.sides['REVISION'].get_view()]:
            return self.sides['REVISION']

        return None

    def get_comments(self, view, view_line = None):
        collection = self.get_collection_by_view(view)

        if collection is None:
            return None

        return collection.get_comments(view_line)

    def has_comments(self, view):
        collection = self.get_collection_by_view(view)

        if collection is None:
            return False

        return collection.has_comments()

    def get_drafts(self, view, view_line = None):
        collection = self.get_collection_by_view(view)

        if collection is None:
            return None

        return collection.get_drafts(view_line)

    def has_drafts(self, view):
        collection = self.get_collection_by_view(view)

        if collection is None:
            return False

        return collection.has_drafts()

    def on_load_comments(self, data):
        self.sides['PARENT'].alternate_revision_id = self.revision_id
        self.sides['REVISION'].revision_id = self.revision_id
        self.loaded_comments = data

        self.on_load_complete()

    def on_load_complete(self):
        if self.loaded_comments is not False and self.loaded_drafts is not False:
            data = self.loaded_comments

            if data is not None:
                self.count_comments_from_set(data)

                if self.file_name in data:
                    for comment in data[self.file_name]:
                        if not 'side' in comment or comment['side'] in ['REVISION', '']:
                            self.sides['REVISION'].add_comment(comment)
                        else:
                            self.sides['PARENT'].add_comment(comment)


            data = self.loaded_drafts

            if data is not None:
                self.count_drafts_from_set(data)

                if self.file_name in data:
                    for comment in data[self.file_name]:
                        if not 'side' in comment or comment['side'] in ['REVISION', '']:
                            self.sides['REVISION'].add_draft(comment)
                        else:
                            self.sides['PARENT'].add_draft(comment)

            if self.load_callback is not None:
                self.load_callback(self)

    def count_comments_from_set(self, data):
        for file_name in data:
            cnt = len(data[file_name])

            if file_name not in self.count_by_file:
                self.count_by_file.update({file_name: {'comments': cnt, 'drafts': 0}})
            else:
                self.count_by_file[file_name]['comments'] += cnt

    def count_drafts_from_set(self, data):
        for file_name in data:
            cnt = len(data[file_name])

            if file_name not in self.count_by_file:
                self.count_by_file.update({file_name: {'comments': 0, 'drafts': cnt}})
            else:
                self.count_by_file[file_name]['drafts'] += cnt

    def on_load_drafts(self, data):
        self.sides['PARENT'].alternate_revision_id = self.revision_id
        self.sides['REVISION'].revision_id = self.revision_id
        self.loaded_drafts = data

        self.on_load_complete()

    def get_count_for_file(self, file_name):
        # this is buggy!
        if file_name == self.file_name:
            return {
                'comments': self.sides['REVISION'].count_comments() + self.sides['PARENT'].count_comments(),
                'drafts': self.sides['REVISION'].count_drafts() + self.sides['PARENT'].count_drafts()
            }

        else:
            if file_name in self.count_by_file:
                return self.count_by_file[file_name]

        return {'comments': 0, 'drafts': 0}


class CommentsCollection():
    def __init__(self, side, view, lines, file_name, change_id, store):
        self.side = side
        self.view = view
        self.change_id = change_id
        self.revision_id = None
        self.comments = {}
        self.drafts = {}
        self.resources = GerritResources()
        self.real_to_view, self.view_to_real = lines
        self.file_name = file_name
        self.alternate_revision_id = None
        self.loaded_comments = False
        self.loaded_drafts = False
        self.comments_count = 0
        self.drafts_count = 0
        self.load_callback = None
        self.add_draft_callback = None
        self.remove_draft_callback = None
        self.store = store

    def destroy(self):
        for line in self.comments:
            for comment in self.comments[line]:
                comment.destroy()

        for line in self.drafts:
            for comment in self.drafts[line]:
                comment.destroy()

        self.comments = {}
        self.drafts = {}

        self.load_callback = None
        self.add_draft_callback = None
        self.remove_draft_callback = None

    def load(self, revision_id, alternate_revision_id = None, load_callback = None):
        self.revision_id = revision_id
        self.alternate_revision_id = alternate_revision_id
        self.load_callback = load_callback

        if alternate_revision_id is None:
            self.resources.get_comments(self.change_id, revision_id).then(self.on_load_comments)
            self.resources.get_draft_comments(self.change_id, revision_id).then(self.on_load_drafts)

        else:
            count_loads = {'comments': 0, 'drafts': 0}
            target_data = {'comments': {}, 'drafts': {}}

            def loaded(target, data, switch_side, on_load):
                if data is not None:
                    for file_name in data:
                        for comment in data[file_name]:
                            if 'side' not in comment or comment['side'] in ['REVISION', '']:
                                if switch_side:
                                    comment.update({'side': 'PARENT'})

                                if file_name not in target_data[target]:
                                    target_data[target].update({file_name: [comment]})
                                else:
                                    target_data[target][file_name].append(comment)

                count_loads[target] += 1

                if count_loads[target] == 2:
                    on_load(target_data[target])


            self.resources.get_comments(
                self.change_id,
                revision_id
            ).then(
                lambda data: loaded(
                    'comments',
                    data,
                    True,
                    self.on_load_comments
                )
            )

            self.resources.get_comments(
                self.change_id,
                alternate_revision_id
            ).then(
                lambda data: loaded(
                    'comments',
                    data,
                    False,
                    self.on_load_comments
                )
            )


            self.resources.get_draft_comments(
                self.change_id,
                revision_id
            ).then(
                lambda data: loaded(
                    'drafts',
                    data,
                    True,
                    self.on_load_drafts
                )
            )

            self.resources.get_draft_comments(
                self.change_id,
                alternate_revision_id
            ).then(
                lambda data: loaded(
                    'drafts',
                    data,
                    False,
                    self.on_load_drafts
                )
            )

    def is_valid(self, comment):
        if 'side' in comment:
            return self.side == comment['side'] or (self.side == 'REVISION' and comment['side'] == '')
        else:
            return self.side == 'REVISION'


    def add_comment(self, comment):
        if not self.is_valid(comment):
            return

        comment = Comment(
            comment,
            self
        )

        self.comments_count += 1

        if comment.get_line() not in self.comments:
            self.comments.update({
                comment.get_line(): [comment]
            })
        else:
            self.comments[comment.get_line()].append(comment)

    def count_comments(self):
        return self.comments_count

    def count_drafts(self):
        return self.drafts_count

    def add_draft(self, comment):
        if not self.is_valid(comment):
            return

        comment = DraftComment(
            comment,
            self
        )

        self.drafts_count += 1

        if comment.get_line() not in self.drafts:
            self.drafts.update({
                comment.get_line(): [comment]
            })
        else:
            self.drafts[comment.get_line()].append(comment)

        if self.add_draft_callback is not None:
            self.add_draft_callback(comment)

    def on_load_comments(self, data):
        self.loaded_comments = data
        self.on_load_complete()

    def on_load_drafts(self, data):
        self.loaded_drafts = data
        self.on_load_complete()

    def on_load_complete(self):
        if self.loaded_comments is not False and self.loaded_drafts is not False:
            data = self.loaded_comments

            if data is not None and self.file_name in data:
                for comment in data[self.file_name]:
                    self.add_comment(comment)

            self.store.count_comments_from_set(data)

            data = self.loaded_drafts

            if data is not None and self.file_name in data:
                for comment in data[self.file_name]:
                    self.add_draft(comment)

            self.store.count_drafts_from_set(data)

            if self.load_callback is not None:
                self.load_callback(self)

    def get_view(self):
        return self.view

    def get_comments(self, view_line = None, real_line = None):
        if view_line is None and real_line is None:
            return self.comments

        if real_line is None:
            real_line = self.view_to_real[view_line]

        if real_line in self.comments:
            return {real_line: self.comments[real_line]}

        return None

    def has_comments(self):
        return len(self.comments) > 0

    def get_drafts(self, view_line = None, real_line = None):
        if view_line is None and real_line is None:
            return self.drafts

        if real_line is None:
            real_line = self.view_to_real[view_line]

        if real_line in self.drafts:
            return {real_line: self.drafts[real_line]}

        return None

    def has_drafts(self):
        return len(self.drafts) > 0

    def erase_comment(self, comment):
        line = comment.get_line()

        if isinstance(comment, DraftComment):
            self.drafts_count -= 1

            if self.remove_draft_callback is not None:
                self.remove_draft_callback(comment)
        else:
            self.comments_count -= 1

        if line in self.drafts:
            self.drafts[line].remove(comment)
            if len(self.drafts[line]) == 0:
                del self.drafts[line]

        comment.destroy()

    def get_draft_at_line(self, real_line):
        drafts = self.get_drafts(real_line=real_line)

        if drafts is not None:
            if real_line in drafts:
                for draft in drafts[real_line]:
                    return draft

        return None

    def create_comment(self, real_lines, message, in_reply_to=None):
        # PARENT None 2    base         -> PARENT, 2
        # REVISION 2 None    current    -> REVISION, 2

        # PARENT 1 2    ps 1            -> REVISION, 1
        # REVISION 2 None    ps 2       -> REVISION, 2

        if self.side == 'PARENT':
            if self.revision_id is None:
                side = 'PARENT'
                revision_id = self.alternate_revision_id
            else:
                side = 'REVISION'
                revision_id = self.revision_id
        else:
            side = self.side
            revision_id = self.revision_id

        def on_add(data):
            if data is not None:
                data[0].update({'side': self.side})
                self.add_draft(data[0])

        for line in real_lines:
            self.resources.create_draft_comment(
                self.change_id,
                revision_id,
                side,
                self.file_name,
                line,
                message,
                in_reply_to
            ).then(on_add)

    def reply_comment(self, comment, message):
        draft = self.get_draft_at_line(comment.get_line())

        if draft is not None:
            draft.update_message(message, comment.get_id())
        else:
            self.create_comment(
                [comment.get_line()],
                message,
                comment.get_id()
            )


class CommentsBrowser():
    last_active_comment = None
    current_comment_text = ''
    clear_current_comment_text = True

    def __init__(self, store, view, view_lines = None):
        self.store = store
        self.view = view
        self.view_lines = view_lines
        self.active_comment = None
        self.window = sublime.active_window()
        self.editing = False

    def prompt(self, edited_comment = None):
        self.editing = True
        CommentsBrowser.clear_current_comment_text = False
        tmp_text = CommentsBrowser.current_comment_text

        collection = self.store.get_collection_by_view(self.view)

        if isinstance(edited_comment, DraftComment):
            sublime.set_timeout(lambda: self.activate_comment(edited_comment), 100)
            self.view_lines = [collection.real_to_view[edited_comment.get_line()]]
        elif isinstance(edited_comment, Comment):
            self.view_lines = [collection.real_to_view[edited_comment.get_line()]]
            edited_comment = None
        else:
            edited_comment = None

        real_lines = []

        for line in self.view_lines:
            real_lines.append('%d' % collection.view_to_real[line])

        caption = '%s: Comment line%s %s' % (
            'Left' if collection.side == 'PARENT' else 'Right',
            's' if len(real_lines) > 1 else '',
            ', '.join(real_lines)
        )

        def update_current_text(text):
            CommentsBrowser.current_comment_text = text

        self.window.show_input_panel(
            caption,
            edited_comment.get_message() if edited_comment is not None else CommentsBrowser.current_comment_text,
            lambda text: (self.create_or_update_draft(collection, edited_comment, real_lines, text), self.clear_current_text()),
            update_current_text,
            lambda: (self.deactivate_comment(self.active_comment), self.clear_current_text())
        )

        CommentsBrowser.clear_current_comment_text = True

        sublime.set_timeout(lambda: update_current_text(tmp_text), 110)

    def clear_current_text(self):
        def clear():
            if self.clear_current_comment_text:
                CommentsBrowser.current_comment_text = ''

        sublime.set_timeout(clear, 100)

    def create_or_update_draft(self, collection, edited_comment, real_lines, text):
        collection.create_comment(real_lines, text) if edited_comment is None else edited_comment.update_message(text)
        self.deactivate_comment(edited_comment)
        self.editing = False

    def cancel(self):
        self.deactivate_comment(self.active_comment)
        self.window.run_command('hide_panel', {'cancel': True})
        self.clear_current_text()

    def show(self, comments = True, drafts = True):
        comments = self.prepare(comments, drafts)

        items = []

        if self.view_lines is not None and comments and comments[0].collection.get_draft_at_line(comments[0].get_line()) is None:
            items.append({
                'caption': ['Add Draft Here'],
                'comment': comments[0],
                'on_over': lambda item: self.deactivate_comment(self.active_comment) or self.display_full_comment(),
                'on_select': lambda item: sublime.set_timeout(lambda: self.prompt(item['comment']), 10)
            })

        quick_panel(
            items + [self.create_comment_menu_item(comment, comments and drafts, comment == comments[0]) for comment in comments],
            on_cancel=self.cancel
        )

    def create_comment_menu_item(self, comment, append_draft_suffix = False, default_selected = False):
        message = ellipsis(comment.get_message())

        return {
            'caption': [
                "%d: %s @ %s%s" % (
                    comment.get_original_line(),
                    comment.get_author(),
                    comment.get_updated(),
                    ' [DRAFT]' if isinstance(comment, DraftComment) and append_draft_suffix else ''
                ),
                message
            ],
            'comment': comment,
            'selected': comment == CommentsBrowser.last_active_comment or default_selected,
            'on_over': lambda item:
                self.activate_comment(item['comment']),
            'on_out': lambda item:
                self.deactivate_comment(item['comment']),
            'on_select': lambda item:
                sublime.set_timeout(
                    lambda: self.prompt(item['comment']),
                    10
                ) if isinstance(item['comment'], DraftComment) else sublime.set_timeout(
                    lambda: self.display_reply_menu(item['comment']),
                    10
                )
        }

    def display_reply_menu(self, comment):
        self.activate_comment(comment)

        def prompt():
            draft = comment.collection.get_draft_at_line(comment.get_line())

            self.window.show_input_panel(
                'Reply at line %d' % comment.get_line(),
                draft.get_message() if draft is not None else '',
                lambda message: comment.collection.reply_comment(comment, message) or self.cancel(),
                None,
                self.cancel
            )

        replies = Settings.get('comment_quick_replies')
        items = [{
            'caption': ['Reply...'],
            'on_select': lambda selected: sublime.set_timeout(prompt, 10)
        }]

        for reply in replies:
            items.append({
                'caption': ['Reply "%s"' % reply],
                'on_select': lambda selected: comment.collection.reply_comment(comment, selected['caption'][0]) or self.cancel()
            })

        quick_panel(items, on_cancel=self.cancel)

    def display_full_comment(self, comment = None):
        if self.editing:
            return

        panel = self.window.get_output_panel('comment')
        panel.run_command('sublime_gerrit_insert', {
            'pos': 0,
            'content': comment.get_message() if comment is not None else ''
        })
        panel.set_syntax_file('Packages/Text/Plain text.tmLanguage')
        panel.settings().set('gutter', False)
        panel.settings().set('line_numbers', False)
        self.window.run_command('show_panel', {'panel': 'output.comment'})

    def activate_comment(self, comment, scroll_to=True):
        if self.active_comment is not None:
            self.deactivate_comment(self.active_comment)

        self.display_full_comment(comment)

        self.active_comment = comment
        CommentsBrowser.last_active_comment = comment

        comment.draw(True)

        if scroll_to:
            sublime.set_timeout(comment.scroll_to, 10)

    def deactivate_comment(self, comment):
        self.active_comment = None
        # self.editing = False
        if comment is not None:
            if not isinstance(comment, DraftComment):
                drafts = comment.collection.get_drafts(real_line=comment.get_line())
                if drafts is not None:
                    drafts[comment.get_line()][0].draw()
                    return

            comment.draw(False)


    def activate_next_comment(self, direction):
        active_comment = CommentsBrowser.last_active_comment

        comments = self.prepare(True, True, False)

        if comments is None or len(comments) == 0:
            return False

        next_comment = None

        if active_comment:
            try:
                index = comments.index(active_comment)

                if direction == 1 and index < len(comments) - 1:
                    next_comment = comments[index + 1]
                elif direction == -1 and index > 0:
                    next_comment = comments[index - 1]
            except ValueError:
                next_comment = comments[0]

        else:
            next_comment = comments[0]

        if next_comment is not None:
            if active_comment:
                self.deactivate_comment(active_comment)

            self.activate_comment(next_comment)


    def has_next_comment(self, direction):
        active_comment = CommentsBrowser.last_active_comment

        comments = self.prepare(True, True, False)

        if comments is None or len(comments) == 0:
            return False

        next_comment = None

        if active_comment:
            try:
                index = comments.index(active_comment)

                if direction == 1 and index < len(comments) - 1:
                    next_comment = comments[index + 1]
                elif direction == -1 and index > 0:
                    next_comment = comments[index - 1]
            except ValueError:
                next_comment = comments[0]

        else:
            next_comment = comments[0]

        return next_comment is not None


    def prepare(self, comments = True, drafts = True, cancel = True):
        collection = self.store.get_collection_by_view(self.view)

        if cancel:
            self.cancel()

        if self.view_lines is not None:
            if len(self.view_lines) > 1: # multiple lines selected
                return self.prompt()

            elif len(self.view_lines) == 0: # none selected
                return None

        result = []
        items = {}

        if drafts:
            data = collection.get_drafts(self.view_lines[0] if self.view_lines is not None else None)

            if data is not None:
                for real_line in data:
                    if real_line not in items:
                        items.update({real_line: []})

                    for comment in data[real_line]:
                        items[real_line].append(comment)

        if comments:
            data = collection.get_comments(self.view_lines[0] if self.view_lines is not None else None)

            if data is not None:
                for real_line in data:
                    if real_line not in items:
                        items.update({real_line: []})

                    for comment in data[real_line]:
                        items[real_line].append(comment)

        if len(items) == 0:
            return self.prompt()

        ordered = sort_num(items)

        for real_line in ordered:
            for comment in items[real_line]:
                result.append(comment)

        if len(result) == 1 and isinstance(result[0], DraftComment):
            CommentsBrowser.last_active_comment = result[0]
            return self.prompt(result[0])

        return result
