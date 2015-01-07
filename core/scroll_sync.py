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
from math import ceil

class Scroller():
    def __init__(self, view, proportionally_x=False, proportionally_y=False):
        self.view = view
        self.last_position = None
        self.proportionally_x = proportionally_x
        self.proportionally_y = proportionally_y

        self.reset()

    def sync_to(self, scroller_active):
        pos = scroller_active.view.viewport_position()
        ve = scroller_active.view.viewport_extent()
        le = scroller_active.view.layout_extent()


        ve = self.view.viewport_extent()
        le = self.view.layout_extent()

        if self.proportionally_x:
            percentage_x = min(1, pos[0] / (1 if le[0] <= ve[0] else le[0] - ve[0]))
            pos_x = max(0, min(ceil(percentage_x * (le[0] - ve[0])), le[0] - ve[0]))
        else:
            pos_x = max(0, min(pos[0], le[0] - ve[0]))

        if self.proportionally_y:
            percentage_y = min(1, pos[1] / (1 if le[1] <= ve[1] else le[1] - ve[1]))
            pos_y = max(0, min(ceil(percentage_y * (le[1] - ve[1])), le[1] - ve[1]))
        else:
            pos_y = max(0, min(pos[1], le[1] - ve[1]))

        self.target_pos = (
            pos_x,
            pos_y
        )

        self.view.set_viewport_position(self.target_pos, False)

    def is_stopped(self):
        pos = self.view.viewport_position()

        if pos == self.last_position:
            return True

        self.last_position = pos
        return False

    def is_synced(self):
        p = self.view.viewport_position()
        ve = self.view.viewport_extent()
        le = self.view.layout_extent()

        pos = (max(0, min(p[0], le[0] - ve[0])), max(0, min(p[1], le[1] - ve[1])))

        return pos == self.target_pos

    def reset(self):
        p = self.view.viewport_position()
        ve = self.view.viewport_extent()
        le = self.view.layout_extent()

        self.target_pos = (max(0, min(p[0], le[0] - ve[0])), max(0, min(p[1], le[1] - ve[1])))


class ScrollSync():
    def __init__(self, a, b):
        self.interval = 1

        self.scrollers = [Scroller(a), Scroller(b)]
        self.scrollers_to_sync = []
        self.scroller_active = None
        self.enabled = True
        self.stored = None

        self.sync()

    def store(self):
        self.stored = [scroller.view.viewport_position() for scroller in self.scrollers]


    def restore(self):
        def inner():
            if self.stored is not None:

                for i in range(0, len(self.scrollers)):
                    self.scrollers[i].view.set_viewport_position(self.stored[i], False)

                self.stored = None

            for scroller in self.scrollers:
                scroller.reset()

        sublime.set_timeout(inner, 100)

    def destroy(self):
        self.enabled = False

    def sync(self):
        if not self.scroller_active:
            for scroller in self.scrollers:
                if not scroller.is_synced():
                    self.scroller_active = scroller
                    self.scrollers_to_sync = [s for s in self.scrollers if s is not scroller]

                    for s in self.scrollers_to_sync:
                        s.sync_to(self.scroller_active)
                    break

        elif all(s.is_synced() for s in self.scrollers_to_sync) or self.scroller_active.is_stopped():
            self.scroller_active.reset()

            for s in self.scrollers_to_sync:
                s.sync_to(self.scroller_active)

            self.scrollers_to_sync = []
            self.scroller_active = None

        if self.enabled:
            sublime.set_timeout(self.sync, self.interval)
