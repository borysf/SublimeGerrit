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

from .base_view import BaseView
from .scroll_sync import ScrollSync
from .utils import create_tmpfile_path, quick_panel, sort_alpha, sort_num, info_message, is_in_viewport, error_message
from .resources import GerritResources
from .reader import DataReader
from .settings import Settings
from .reloader import Reloader
from .comments import CommentsStore, CommentsBrowser

def increment_if_greater_or_equal(x, threshold):
    if x >= threshold:
        return x+1
    return x

class DiffView(BaseView):
    a = None
    b = None

    def __init__(self, opener, change_id, revision, filename, revisions):
        BaseView.__init__(self)

        self.base = None
        self.revisions = revisions
        self.data = None
        self.change_id = change_id
        self.revision = revision
        self.file_name = None
        self.active = None
        self.destroying = None
        self.handling_selection = None
        self.comments = None
        self.regions_a = None
        self.regions_b = None
        self.change_selected_index = None
        self.sync = None
        self.created = False
        self.old_layout = None
        self.current_file_index = 0
        self.toggled_side_bar = False

        self.resources = GerritResources()
        self.opener = opener
        self.files_list = {}
        self.loading = True
        self.real_to_view = {}
        self.view_to_real = {}
        self.view_to_focus = None
        self.intralines_visible = True

        self.load_diff(filename)
        self.opener.settings().set('is_sublimegerrit_diff_view', True)

    def views(self):
        return [self.a, self.b]

    def render_loader(self, view):
        view.set_name('Loading...')
        view.run_command('sublime_gerrit_clear')
        view.run_command('sublime_gerrit_insert', {
            'content': 'Loading...',
            'pos': 0
        })

    def load_diff(self, filename, base=None):
        self.loading = True
        self.intralines_visible = True

        if self.sync:
            self.sync.destroy()

        if self.comments is not None:
            self.comments.destroy()
            self.comments = None

        current_ext = os.path.splitext(filename)[1].lower()
        syntax = None
        # hack to load a proper syntax file... find a better way to obtain a syntax by extension
        if self.file_name is not None and os.path.splitext(self.file_name)[1].lower() != current_ext:
            path = create_tmpfile_path(filename)
            tmp_view = self.window.open_file(path, sublime.TRANSIENT)

            syntax = tmp_view.settings().get('syntax')
            self.window.focus_view(tmp_view)
            self.window.run_command('close')

            self.a.set_syntax_file(syntax)
            self.b.set_syntax_file(syntax)

        self.file_name = filename
        self.active = True
        self.destroying = False
        self.handling_selection = False
        self.regions_a = []
        self.regions_b = []
        self.change_selected_index = -1
        self.created = True
        self.revision_id = self.revision['_number']
        self.files_list = {}
        self.real_to_view = {'a': {}, 'b': {}}
        self.view_to_real = {'a': {}, 'b': {}}

        for f in self.revision['files']:
            if 'binary' in self.revision['files'][f]:
                continue

            self.files_list.update({f: self.revision['files'][f]})

        self.base = base
        self.current_rev_num = self.revision['_number']

        def sync():
            self.sync = ScrollSync(self.a, self.b)

        def insert_diff(data):
            # data = data[0]

            if data is None:
                self.destroy()
                return

            if 'meta_a' not in data and 'meta_b' not in data:
                error_message('Could not process diff. Server sent incomplete response' + (':\n\n' + sublime.encode_value(data) if data is not None else '.'))
                self.destroy()
                return

            self.data = DataReader('gerritcodereview#diff').read(data)
            self.change_layout()

            self.render_loader(self.a)
            self.render_loader(self.b)

            self.insert_diff()
            self.get_comments()
            self.resources.set_reviewed(self.change_id, self.revision_id, self.file_name).start()

            # hack to load proper syntax from fallback definitions, i.e. for xul files
            syntax = self.a.settings().get('syntax') or self.b.settings().get('syntax')
            fallbacks = Settings.get('diff.fallback_syntaxes')
            if current_ext in fallbacks:
                syntax = fallbacks[current_ext]

            self.a.set_syntax_file(syntax)
            self.b.set_syntax_file(syntax)

            if len(self.regions_a) == 0:
                info_message('There are no differences')

            sublime.set_timeout(sync, 500)

            self.loading = False

        self.resources.diff(self.change_id, self.revision_id, filename, base).then(insert_diff)


    def is_my_view(self, view):
        return view in [self.opener, self.a, self.b]

    def restore_layout(self):
        self.window.set_layout(self.old_layout)

        if self.toggled_side_bar:
            self.window.run_command('toggle_side_bar')

    def change_layout(self):
        if self.old_layout is not None:
            return

        if Settings.get('diff.toggle_side_bar'):
            self.window.run_command('toggle_side_bar')
            self.toggled_side_bar = True

        self.old_layout = self.window.get_layout()

        Reloader.cleanup_set_layout()

        XMIN, YMIN, XMAX, YMAX = list(range(4))

        #split vertically
        l = self.window.get_layout()
        cols = l['cols']
        cells = l['cells']
        rows = l['rows']

        main_group = current_group = self.window.active_group()
        old_cell = cells.pop(current_group)
        new_cell = []


        cells = [[x0,increment_if_greater_or_equal(y0, old_cell[YMAX]), x1,increment_if_greater_or_equal(y1, old_cell[YMAX])] for (x0,y0,x1,y1) in cells]
        rows.insert(old_cell[YMAX], (rows[old_cell[YMIN]] + rows[old_cell[YMAX]]) * 0.15)
        new_cell = [old_cell[XMIN], old_cell[YMAX], old_cell[XMAX], old_cell[YMAX]+1]
        old_cell = [old_cell[XMIN], old_cell[YMIN], old_cell[XMAX], old_cell[YMAX]]

        if new_cell:
            focused_cell = old_cell
            unfocused_cell = new_cell
            cells.insert(current_group, focused_cell)
            cells.append(unfocused_cell)
            self.set_layout({"cols": cols, "rows": rows, "cells": cells})

        if not self.a:
            self.a = self.window.open_file(create_tmpfile_path((self.data[0]['meta_a'] or self.data[0]['meta_b'])['name'])) #hack: loads apropriate syntax for file by its extension.
            self.setup_view(self.a)
            self.window.set_view_index(self.a, len(cells)-1, 0)
            self.a.settings().set('is_sublimegerrit_diff_view', True)

        # split horizontally
        l = self.window.get_layout()
        cols = l['cols']
        cells = l['cells']
        rows = l['rows']

        current_group = self.window.active_group()
        old_cell = cells.pop(current_group)
        new_cell = []

        cells = [[increment_if_greater_or_equal(x0, old_cell[XMAX]),y0, increment_if_greater_or_equal(x1, old_cell[XMAX]),y1] for (x0,y0,x1,y1) in cells]
        cols.insert(old_cell[XMAX], (cols[old_cell[XMIN]] + cols[old_cell[XMAX]]) / 2)
        new_cell = [old_cell[XMAX], old_cell[YMIN], old_cell[XMAX]+1, old_cell[YMAX]]
        old_cell = [old_cell[XMIN], old_cell[YMIN], old_cell[XMAX], old_cell[YMAX]]

        if new_cell:
            focused_cell = old_cell
            unfocused_cell = new_cell
            cells.insert(current_group, focused_cell)
            cells.append(unfocused_cell)
            self.set_layout({"cols": cols, "rows": rows, "cells": cells})

        if not self.b:
            self.b = self.window.open_file(create_tmpfile_path((self.data[0]['meta_b'] or self.data[0]['meta_a'])['name'])) #hack: loads apropriate syntax for file by its extension.
            self.setup_view(self.b)
            self.window.set_view_index(self.b, len(cells)-1, 0)
            self.b.settings().set('is_sublimegerrit_diff_view', True)

        self.window.focus_group(main_group)
        self.window.focus_view(self.opener)

    def set_layout(self, layout):
        active_group = self.window.active_group()
        self.window.set_layout(layout)
        num_groups = len(layout['cells'])
        self.window.focus_group(min(active_group, num_groups-1))


    def setup_view(self, view):
        settings = Settings.get('diff_view') or {}

        settings.update({
            'translate_tabs_to_spaces': False,
            'line_numbers': False,
            'word_wrap': False,
            'scroll_past_end': False,
            'highlight_line': True,
            'draw_white_space': 'all',
            'save_on_focus_lost': False,
            'scroll_past_end': False,
            'sublimerge_off': True
        })

        for name in settings:
            view.settings().set(name, settings[name])

        view.set_scratch(True)

    def insert_diff(self):
        def insert(view, data):
            view.run_command('sublime_gerrit_clear')
            content = []
            regions = []
            line_regions = []
            change_regions = []
            intralines = []

            i = 0
            begin = 0
            size = 0

            for item in data:
                begin = size

                if len(item['lines']) > 0:
                    content += item['lines']
                    size += sum([len(line) + 1 for line in item['lines']])

                    if item['type'] in ['change', 'missing']:
                        region = sublime.Region(begin, size)

                        if item['type'] == 'missing':
                            color = Settings.get('diff.block_missing')
                            if Settings.get('diff.block_draw_outlined'):
                                flags = 0
                            else:
                                flags = sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE

                        else:
                            if Settings.get('diff.block_draw_outlined'):
                                flags = sublime.DRAW_NO_FILL
                            else:
                                flags = sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE

                            if view in [self.a]:
                                color = Settings.get('diff.block_deleted')
                            else:
                                color = Settings.get('diff.block_inserted')

                        definition = ['region-%d' % i, [region], color, '', flags]

                        regions.append(definition)

                        if not Settings.get('diff.block_draw_outlined'):
                            ends = 0
                            for j in range(0, len(item['lines'])):
                                line_region = sublime.Region(begin + ends, begin + ends)
                                line_regions.append(['region-%d-%d' % (i, j), [line_region], color, '', sublime.DRAW_EMPTY])
                                ends += len(item['lines'][j]) + 1

                        if item['type'] == 'change' or (item['type'] == 'missing' and item['removal']):
                            change_regions.append(definition)

                        if item['type'] == 'change':
                            for intraline in item['intraline']:
                                intralines.append(
                                    sublime.Region(begin + intraline[0], begin + intraline[1])
                                )

                i += 1

            view.run_command('sublime_gerrit_insert', {
                'content': '\n'.join(content) + '\n',
                'pos': 0
            })

            if Settings.get('diff.block_intraline_draw_outlined'):
                flags = sublime.DRAW_NO_FILL | sublime.HIDE_ON_MINIMAP
            else:
                flags = sublime.DRAW_NO_OUTLINE | sublime.HIDE_ON_MINIMAP

            regions.append([
                'intralines',
                intralines,
                Settings.get('diff.block_intraline'),
                '',
                flags
            ])

            for region in regions:
                view.add_regions(*region)

            for region in line_regions:
                view.add_regions(*region)

            return change_regions


        a = []
        b = []

        # self.update_title_a()
        # self.update_title_b()

        def intralines(edit, change):
            result = []
            last_edit = {
                'edit_a': 0,
                'edit_b': 0
            }
            if self.data[0]['intraline_status'] == 'OK':
                for intra in change[edit]:
                    begin = last_edit[edit] + intra[0]
                    end = begin + intra[1]
                    last_edit[edit] = end

                    result.append([begin, end])

            return result

        missing_a = missing_b = 0
        line_a = line_b = 0

        for change in self.data[0]['content']:
            if change['ab']:
                a.append({'lines': change['ab'], 'type': 'common'})
                b.append({'lines': change['ab'], 'type': 'common'})

                for i in range(len(change['ab'])):
                    self.real_to_view['a'].update({line_a + 1: line_a + missing_a})
                    self.view_to_real['a'].update({line_a + missing_a: line_a + 1})

                    self.real_to_view['b'].update({line_b + 1: line_b + missing_b})
                    self.view_to_real['b'].update({line_b + missing_b: line_b + 1})
                    line_a += 1
                    line_b += 1
            else:
                a.append({'lines': change['a'], 'type': 'change', 'intraline': intralines('edit_a', change)})
                b.append({'lines': change['b'], 'type': 'change', 'intraline': intralines('edit_b', change)})

                for i in range(len(change['a'])):
                    self.real_to_view['a'].update({line_a + 1: line_a + missing_a})
                    self.view_to_real['a'].update({line_a + missing_a: line_a + 1})
                    line_a += 1

                for i in range(len(change['b'])):
                    self.real_to_view['b'].update({line_b + 1: line_b + missing_b})
                    self.view_to_real['b'].update({line_b + missing_b: line_b + 1})
                    line_b += 1

                miss_a = len(change['b']) - len(change['a'])
                miss_b = len(change['a']) - len(change['b'])

                a.append({'lines': [''] * miss_a, 'type': 'missing', 'removal': len(change['a']) == 0})
                b.append({'lines': [''] * miss_b, 'type': 'missing', 'removal': len(change['b']) == 0})

                missing_a += miss_a if miss_a > 0 else 0
                missing_b += miss_b if miss_b > 0 else 0

        self.regions_a = insert(self.a, a)
        self.regions_b = insert(self.b, b)

        self.window.focus_view(self.a)
        self.window.focus_view(self.b)

        self.a.set_read_only(True)
        self.b.set_read_only(True)

        if len(self.regions_a) > 0:
            self.a.show_at_center(sublime.Region(self.regions_a[0][1][0].begin(), self.regions_a[0][1][0].begin()))
            self.b.show_at_center(sublime.Region(self.regions_b[0][1][0].begin(), self.regions_b[0][1][0].begin()))


        self.a.sel().clear()
        self.b.sel().clear()
        self.window.run_command('hide_panel', {'cancel': True})

    def select_rows_in(self, view, rows):
        self.window.focus_view(view)
        sel = view.sel()
        sel.clear()

        for row in rows:
            b = view.text_point(row, 0)
            sel.add(sublime.Region(b, b))

    def update_title_a(self, comments_store=None):
        comments = []

        if comments_store is not None:
            collection = comments_store.get_collection_by_view(self.a)

            count_drafts = collection.count_drafts()
            count_comments = collection.count_comments()

            if count_drafts > 0:
                comments.append('%d draft%s' % (count_drafts, 's' if count_drafts > 1 else ''))

            if count_comments > 0:
                comments.append('%d comment%s' % (count_comments, 's' if count_comments > 1 else ''))


        self.a.set_name('%s @ %s%s' % (
            os.path.basename((self.data[0]['meta_a'] or {'name': '<missing>'})['name']),
            'Base' if self.base is None else ('Patch Set %d' % self.base),
            (' (' + ', '.join(comments) + ')') if len(comments) > 0 else ''
        ))

        Reloader.cleanup_set_name(self.a.name())


    def update_title_b(self, comments_store=None):
        comments = []

        if comments_store is not None:
            collection = comments_store.get_collection_by_view(self.b)

            count_drafts = collection.count_drafts()
            count_comments = collection.count_comments()

            if count_drafts > 0:
                comments.append('%d draft%s' % (count_drafts, 's' if count_drafts > 1 else ''))

            if count_comments > 0:
                comments.append('%d comment%s' % (count_comments, 's' if count_comments > 1 else ''))

        self.b.set_name('%s @ Patch Set %d%s' % (
            os.path.basename((self.data[0]['meta_b'] or {'name': '<missing>'})['name']),
            self.current_rev_num,
            (' (' + ', '.join(comments) + ')') if len(comments) > 0 else ''
        ))

        Reloader.cleanup_set_name(self.b.name())


    def get_comments(self):
        if self.comments is not None:
            self.comments.destroy()

        self.comments = CommentsStore(
            self.a,
            self.b,
            (self.real_to_view['a'], self.view_to_real['a']),
            (self.real_to_view['b'], self.view_to_real['b']),
            self.file_name,
            self.change_id,
            self.revision_id,
            self.base,
            self.on_load_comments
        )

    def on_load_comments(self, comments_store):
        self.update_title_a(comments_store)
        self.update_title_b(comments_store)

        comments_store.get_collection_by_view(self.a).add_draft_callback = lambda draft: self.update_title_a(comments_store)
        comments_store.get_collection_by_view(self.b).add_draft_callback = lambda draft: self.update_title_b(comments_store)

        comments_store.get_collection_by_view(self.a).remove_draft_callback = lambda draft: self.update_title_a(comments_store)
        comments_store.get_collection_by_view(self.b).remove_draft_callback = lambda draft: self.update_title_b(comments_store)

    def display_base_change_menu(self):
        items = []

        items.append({
            'caption': ['Base'],
            'on_select': lambda selected: self.load_diff(self.file_name),
            'selected': self.base is None
        })

        for revision in self.revisions:
            if revision['_number'] != self.current_rev_num:
                items.append({
                    'caption': ['Patch Set %d' % revision['_number']],
                    'number': revision['_number'],
                    'selected': self.base == revision['_number'],
                    'on_select': lambda selected: self.load_diff(self.file_name, selected['number'])
                })

        quick_panel(items)



    def has_many_files(self):
        return len(self.files_list.keys()) > 1


    def get_base_name(self):
        return 'Base' if self.base is None else str(self.base)


    def switch_side(self):
        self.window.focus_view(self.a if self.window.active_view() in [self.b] else self.b)


    def comments_count_text(self, filename):
        comments = []

        counts = self.comments.get_count_for_file(filename)

        if counts['drafts'] > 0:
            comments.append('%d draft%s' % (counts['drafts'], 's' if counts['drafts'] > 1 else ''))

        if counts['comments'] > 0:
            comments.append('%d comment%s' % (counts['comments'], 's' if counts['comments'] > 1 else ''))

        return ', '.join(comments)


    def load_next_file(self, direction = 1):
        file_names = sort_alpha(list(self.files_list.keys()))

        self.current_file_index = file_names.index(self.file_name)

        next_file = None

        if direction == 1 and self.current_file_index + 1 < len(file_names):
            self.current_file_index += 1
            next_file = file_names[self.current_file_index]

        elif direction == -1 and self.current_file_index - 1 >= 0:
            self.current_file_index -= 1
            next_file = file_names[self.current_file_index]

        if next_file is not None:
            self.load_diff(next_file, self.base)


    def display_files_menu(self):
        file_names = sort_alpha(list(self.files_list.keys()))

        self.current_file_index = file_names.index(self.file_name)
        items = []
        index = 0

        for fname in file_names:
            fdata = self.files_list[fname]
            # comments = self.comments_count_text(fname)

            items.append({
                'caption': [
                    fname,
                    '%s %s%s' % (
                        fdata['status'],
                        fdata['lines_total'],
                        '' # ((', ' + comments) if comments else '')
                    )
                ],
                'index': index,
                'on_select': lambda selected: self.load_diff(file_names[selected['index']], self.base),
                'selected': index == self.current_file_index
            })
            index += 1

        quick_panel(items)


    def scroll_to(self, view, region):
        visible = view.visible_region()

        viewport_begin_row, _ = view.rowcol(visible.begin())
        viewport_end_row, _ = view.rowcol(visible.end())

        region_begin_row, _ = view.rowcol(region.begin())
        region_end_row, _ = view.rowcol(region.end())

        viewport_begin_row += 2
        viewport_end_row -= 2

        is_in_viewport = region_begin_row > viewport_begin_row and region_end_row < viewport_end_row

        if not is_in_viewport:
            viewport_height = viewport_end_row - viewport_begin_row
            region_height = region_end_row - region_begin_row

            point_begin = view.text_point(region_begin_row, 0)
            point_end = view.text_point(region_begin_row + int(round(viewport_height / 2)), 0)

            view.show_at_center(sublime.Region(point_begin, point_end))


    def display_changes_menu(self):
        items = []

        def select_change(selected):
            self.change_selected_index = selected['index']

            region_a = sublime.Region(selected['regions'][0], selected['regions'][0])
            region_b = sublime.Region(selected['regions'][1], selected['regions'][1])

            self.a.add_regions('change_pointer', [region_a], 'keyword', 'bookmark', sublime.HIDDEN)
            self.b.add_regions('change_pointer', [region_b], 'keyword', 'bookmark', sublime.HIDDEN)

            self.scroll_to(self.a, region_a)
            self.scroll_to(self.b, region_b)


        def deselect_change(selected):
            self.a.erase_regions('change_pointer')
            self.b.erase_regions('change_pointer')


        for i in range(len(self.regions_a)):
            items.append({
                'caption': ['Change %d' % (i + 1)],
                'regions': (self.regions_a[i][1][0].begin(), self.regions_b[i][1][0].begin()),
                'index': i,
                'on_over': select_change,
                'on_out': deselect_change
            })

        quick_panel(items, selected_index=self.change_selected_index)


    def show_next_change(self, direction):
        next_file = None

        if direction == 1 and self.change_selected_index + 1 < len(self.regions_a):
            self.change_selected_index += 1

        elif direction == -1 and self.change_selected_index - 1 >= 0:
            self.change_selected_index -= 1

        selected = (
            self.regions_a[self.change_selected_index][1][0].begin(),
            self.regions_b[self.change_selected_index][1][0].begin()
        )

        region_a = sublime.Region(selected[0], selected[0])
        region_b = sublime.Region(selected[1], selected[1])

        self.a.add_regions('change_pointer', [region_a], 'keyword', 'bookmark', sublime.HIDDEN)
        self.b.add_regions('change_pointer', [region_b], 'keyword', 'bookmark', sublime.HIDDEN)

        self.scroll_to(self.a, region_a)
        self.scroll_to(self.b, region_b)


    def focus(self):
        if not self.destroying:
            self.window.focus_view(self.b)


    def destroy(self, unloading=False, display_review_menu=True):
        if not self.created:
            return

        try:
            if self.destroying:
                return
        except:
            return

        self.opener.settings().erase('is_sublimegerrit_diff_view')

        self.destroying = True
        self.window.run_command('hide_panel', {'cancel': True})
        if self.sync:
            self.sync.destroy()
            self.sync = None

        if self.a is not None and self.a.window() is not None:
            self.window.focus_view(self.a)
            self.window.run_command('close')

        if self.b is not None and self.b.window() is not None:
            self.window.focus_view(self.b)
            self.window.run_command('close')

        self.restore_layout()

        if not unloading:
            instance = BaseView.find_instance_by_view(self.opener)

            if instance is not None and display_review_menu:
                instance.refresh()
                sublime.set_timeout(instance.display_review_menu, 200)

        BaseView.destroy(self)

    def display_comments_menu(self):
        CommentsBrowser(self.comments, self.window.active_view()).show(comments=True, drafts=False)

    def display_drafts_menu(self):
        CommentsBrowser(self.comments, self.window.active_view()).show(comments=False, drafts=True)

    def display_comments_browser_at_lines(self, view, view_lines):
        sublime.set_timeout(lambda: CommentsBrowser(self.comments, view, view_lines).show(), 100) # fix blinking menu

    def show_next_comment(self, direction):
        CommentsBrowser(self.comments, self.window.active_view()).activate_next_comment(direction)

    def toggle_intralines(self):
        self.intralines_visible = not self.intralines_visible

        if not self.intralines_visible:
            flags = sublime.HIDDEN
        elif Settings.get('diff.block_intraline_draw_outlined'):
            flags = sublime.DRAW_NO_FILL | sublime.HIDE_ON_MINIMAP
        else:
            flags = sublime.DRAW_NO_OUTLINE | sublime.HIDE_ON_MINIMAP

        def toggle(view):
            intralines = view.get_regions('intralines')

            view.add_regions(
                'intralines',
                intralines,
                Settings.get('diff.block_intraline'),
                '',
                flags
            )

        toggle(self.a)
        toggle(self.b)




    def show_base_change_menu_cmd(self):
        return self.display_base_change_menu if len(self.revisions) > 1 else False

    def show_file_change_menu_cmd(self):
        return self.display_files_menu if len(self.files_list.keys()) > 1 else False

    def show_changes_menu_cmd(self):
        return self.display_changes_menu if len(self.regions_a) > 0 else False

    def toggle_intralines_cmd(self):
        return self.toggle_intralines if len(self.regions_a) > 0 else False

    def view_drafts_cmd(self):
        return self.display_drafts_menu if self.comments.has_drafts(self.window.active_view()) else False

    def view_comments_cmd(self):
        return self.display_comments_menu if self.comments.has_comments(self.window.active_view()) else False

    def load_next_file_cmd(self, direction):
        file_names = sort_alpha(list(self.files_list.keys()))

        if (
            (direction == 1 and self.current_file_index + 1 < len(file_names)) or
            (direction == -1 and self.current_file_index - 1 >= 0)
        ):
            return self.load_next_file

        return False

    def show_next_change_cmd(self, direction):
        if (
            (direction == 1 and self.change_selected_index + 1 < len(self.regions_a)) or
            (direction == -1 and self.change_selected_index - 1 >= 0)
        ):
            return self.show_next_change

        return False

    def show_next_comment_cmd(self, direction):
        return self.show_next_comment if CommentsBrowser(self.comments, self.window.active_view()).has_next_comment(direction) else False



    def on_selection_modified(self, view):
        if self.handling_selection or self.loading or any([sel.size() > 1 for sel in view.sel()]):
            return

        if self.view_to_focus is None:
            self.view_to_focus = view

        sel = view.sel()
        self.handling_selection = True
        to_select = []
        size = view.size()
        total_rows, _ = view.rowcol(size)

        if view in [self.a, self.b]:
            for selection in sel:
                row, col = view.rowcol(selection.begin())
                if row == total_rows: # disallow selecting 'extra' line
                    row -= 1
                    sel.subtract(selection)
                    begin = view.text_point(row, 0)
                    selection = sublime.Region(begin, begin)
                    sel.add(selection)

                if selection.empty():
                    if row not in self.view_to_real['a' if view in [self.a] else 'b']:
                        sel.subtract(selection)
                        continue

                    if col > 0:
                        point = view.text_point(row, 0)
                        sel.subtract(selection)
                        selection = sublime.Region(point, point)
                        sel.add(selection)

                    to_select.append(row)

            if view in [self.a]:
                self.select_rows_in(self.b, to_select)
                self.window.focus_view(self.b)
            elif view in [self.b]:
                self.select_rows_in(self.a, to_select)
                self.window.focus_view(self.a)

            self.window.focus_view(self.view_to_focus)

            if len(to_select) > 1:
                collection = self.comments.get_collection_by_view(self.view_to_focus)

                if collection is not None:
                    to_delete = []

                    for line in to_select:
                        if collection.get_drafts(line) is not None:
                            to_delete.append(line)
                            point = self.view_to_focus.text_point(line, 0)
                            self.view_to_focus.sel().subtract(sublime.Region(point, point))

                    for line in to_delete:
                        to_select.remove(line)


            self.display_comments_browser_at_lines(self.view_to_focus, to_select)

        self.handling_selection = False
        self.view_to_focus = None

    def on_activated(self, view):
        pass

    def on_modified(self, view):
        pass

    def on_deactivated(self, view):
        pass

    def on_close(self, view):
        self.destroy()
