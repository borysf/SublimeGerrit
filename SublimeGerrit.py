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

from .core.commands import *
from .core.listener import *
from .core.reloader import Reloader
from .core.diff_view import DiffView
from .core.change_view import ChangeView

def plugin_loaded():
    Reloader.reload()

def plugin_unloaded():
    ChangeView.destroy_all()
    DiffView.destroy_all()
