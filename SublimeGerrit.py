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
