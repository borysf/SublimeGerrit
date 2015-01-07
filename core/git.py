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

import shlex
import sublime, sublime_plugin
import os, sys, re
import threading
import subprocess
import functools
import time
from urllib.parse import urlparse, urlsplit

from .utils import error_message, info_message, quick_panel, git_root
from .settings import Settings
from .thread_progress import ThreadProgress


def find_git_roots(repo_window):
    roots = []
    for path in repo_window.folders():
        root = git_root(path)

        if root is not None and root not in roots:
            roots.append(root)

    return roots


def select_repository_menu(repo_window, on_done):
    roots = find_git_roots(repo_window)

    if len(roots) == 0:
        error_message('Git repository could not be found in any of open directories (or any of the parent directories)')
        return

    if len(roots) == 1:
        on_done(roots[0])

    else:
        quick_panel(
            items=[{'caption': [path], 'path': path} for path in roots],
            on_select=lambda selected: on_done(selected['path'])
        )


class ProcessListener(object):
    def on_stdout(self, proc, data):
        pass

    def on_stderr(self, proc, data):
        pass

    def on_finished(self, proc):
        pass


class Command(ProcessListener):
    output = {}

    @classmethod
    def clear_output(self):
        window_id = sublime.active_window().id()

        if window_id in Command.output:
            Command.output[window_id].run_command('sublime_gerrit_clear')

    def __init__(self, command, on_done, on_failure=None, on_stdout=None, on_stderr=None, silent=False):
        window = sublime.active_window()

        self.on_done_cb = on_done
        self.on_stdout_cb = on_stdout
        self.on_stderr_cb = on_stderr
        self.on_failure_cb = on_failure
        self.silent = silent

        self.stdout = []
        self.stderr = []

        command = shlex.split(command)
        defaults = Settings.get('git.default_args')

        if command[0] == 'git' and defaults:
            command = ['git'] + [defaults] + command[1:]

        command = ' '.join(command)

        self.output_write('runcmd: ' + command)

        self.proc = AsyncProcess(
            cmd=None,
            shell_cmd=command,
            env={},
            listener=self,
            path='$PATH;%s' % Settings.get('git.executable_path')
        )

    def on_stdout(self, proc, data):
        self.stdout.append(data)

        self.output_write('stdout: ' + data)

        if self.on_stdout_cb is not None:
            self.on_stdout_cb(data)

    def on_stderr(self, proc, data):
        self.stderr.append(data)

        self.output_write('stderr: ' + data)

        if self.on_stderr_cb is not None:
            self.on_stderr_cb(data)

    def on_finished(self, proc):
        if proc.exit_code() is None:
            sublime.set_timeout(lambda: self.on_finished(proc), 10)
            return

        ec = proc.exit_code()

        self.output_write('status: %d' % ec)

        if ec != 0:
            if self.on_failure_cb is None:
                error_message('%s\n\nExit Code: %d' % ('\n'.join(self.stdout + self.stderr), ec))
            else:
                self.on_failure_cb(ec, self.stdout, self.stderr)
        else:
            self.on_done_cb(ec, self.stdout, self.stderr)

    def output_write(self, data):
        if self.silent:
            return

        window_id = sublime.active_window().id()

        if window_id not in Command.output:
            output = sublime.active_window().create_output_panel('sublimegerrit')
            Command.output.update({window_id: output})

            output.set_syntax_file('/'.join(['Packages', 'SublimeGerrit', 'syntax', 'SublimeGerritConsole.tmLanguage']))
            output.settings().set('gutter', False)
            output.settings().set('line_numbers', False)
            output.settings().set('scroll_past_end', False)
        else:
            output = Command.output[window_id]

        sublime.active_window().run_command('show_panel', {'panel': 'output.sublimegerrit'})

        size = output.size()

        if size > 0 and data[0:6] == 'runcmd':
            data = '\n' + data

        output.run_command('sublime_gerrit_insert', {
            'content': data + '\n',
            'pos': size
        })

        size = output.size()
        output.show(sublime.Region(size, size))


class Git():
    def __init__(self, project_name, branch_name, change_id, repo_window, change_window):
        self.commands = []
        self.project_name = project_name
        self.branch_name = branch_name
        self.applied = False
        self.change_id = change_id
        self.stash_id = 'review-%s' % change_id[0:10]
        self.review_branch = 'review-%s' % change_id[0:10]
        self.working_dir = None
        self.repo_window = repo_window
        self.change_window = change_window

    def checkout(self, command):
        select_repository_menu(self.repo_window, lambda directory: self.do_checkout(command, directory))

    def do_checkout(self, command, working_dir):
        Command.clear_output()

        self.working_dir = working_dir
        self.commands = self.parse_command(command)
        os.chdir(working_dir)

        def done(exit_code, stdout, stderr):
            info_message('Switched to branch `%s`.' % self.review_branch)
            self.applied = True

        def done_branch(exit_code, stdout, stderr):
            if exit_code == 0 and len(stdout) == 1:

                if stdout[0] == 'HEAD' or re.match('^\(.*\)$', stdout[0]):
                    error_message('You are in detached state. Please checkout to a regular branch and try again.')
                    return

                self.branch_name = stdout[0]

            if self.is_review_branch(self.branch_name):
                error_message('You are already on a review branch (`%s`).\nPlease drop that branch or complete your review and try again.' % self.branch_name)
                return

            self.commands.insert(0, 'git stash save %s' % self.stash_id)
            self.commands.append('git checkout -B %s' % self.review_branch)

            self.run_commands_queue(
                self.commands,
                done
            )

        self.ensure_correct_project(lambda: self.get_current_branch(done_branch))


    def is_review_branch(self, name):
        return True if re.match('^review-[a-zA-Z0-9]{10}$', name) else False


    def get_current_branch(self, on_done, silent=False):
        Command(
            command='git rev-parse --abbrev-ref HEAD',
            on_done=on_done,
            silent=silent
        )


    def check_branch_exists(self, name, on_done, on_failure):
        Command(
            command='git show-ref --verify --quiet refs/heads/%s' % name,
            on_done=on_done,
            on_failure=on_failure
        )


    def revert(self):
        from .gutter_comments import GutterComments

        GutterComments.set_suspended(True)
        Command.clear_output()
        os.chdir(self.working_dir)

        def on_done(exit_code, stdout, stderr):
            info_message('Branch `%s` reverted to the state before checkout.' % self.branch_name)
            self.applied = False
            GutterComments.set_suspended(False)

        def find_stash_and_revert(exit_code, stdout, stderr):
            if exit_code == 0:
                queue = [
                    'git reset --hard',
                    'git checkout %s' % self.branch_name
                ]

                matches = False

                for line in stdout:
                    matches = re.match('^([^:]+):.*\s+%s$' % self.stash_id, line)

                if matches:
                    queue.append('git stash pop %s' % matches.group(1))

                queue.append('git branch -D %s' % self.review_branch)

                self.run_commands_queue(
                    queue,
                    on_done
                )

        def checkout_to_review(current_branch):
            if sublime.ok_cancel_dialog('SublimeGerrit - Revert Checkout\n\nCurrent branch is `%s`, but `%s` is required to proceed.\n\nCheckout to `%s`?' % (current_branch, self.review_branch, self.review_branch)):
                Command(
                    command='git checkout %s' % self.review_branch,
                    on_done=lambda exit_code, stdout, stderr: self.revert()
                )


        def display_error(current_branch):
            error_message('SublimeGerrit - Revert Checkout\n\nCan\'t proceed because review branch `%s` does not exist.\nPlease checkout to `%s` and pop stash `%s` (if any).' % (self.review_branch, self.branch_name, self.stash_id))


        def on_branch(exit_code, stdout, stderr):
            if exit_code == 0 and len(stdout) == 1:
                required_branch = stdout[0]
                if self.is_review_branch(required_branch):
                    Command(
                        command='git stash list --grep "%s$"' % self.stash_id,
                        on_done=find_stash_and_revert
                    )
                else:
                    self.check_branch_exists(
                        self.review_branch,
                        lambda exit_code, stdout, stderr: checkout_to_review(required_branch),
                        lambda exit_code, stdout, stderr: display_error(required_branch)
                    )

        self.get_current_branch(on_branch)


    def is_applied(self):
        return self.applied


    def parse_command(self, command):
        parts = shlex.split(command)

        commands = []
        command = []

        commands.append(command)

        for part in parts:
            if part != '&&':
                command.append(part)
            else:
                command = []
                commands.append(command)


        return [' '.join(command) for command in commands]


    def run_commands_queue(self, queue, on_done):
        def run_next(exit_code=0, stdout='', stderr='', first_run=False):
            if exit_code == 0:
                if len(queue) > 0:
                    command = queue.pop(0)
                    execute_command(command)
                else:
                    on_done(exit_code, stdout, stderr)

        def execute_command(command):
            Command(
                command=command,
                on_done=run_next
            )

        run_next(first_run=True)


    def ensure_correct_project(self, on_ok):
        def done(exit_code, stdout, stderr):
            repo_name = None
            project_name = os.path.basename(self.project_name)

            if exit_code == 0:
                for line in stdout:
                    matches = re.match('^[^\t]+\t(.*)\s+\(fetch\)$', line)

                    if matches:
                        repo_name = matches.group(1)
                        repo_name = repo_name[:-1] if repo_name[-1:] == '/' else repo_name
                        repo_name = os.path.basename(repo_name)
                        repo_name = repo_name[0:-4] if repo_name[-4:] == '.git' else repo_name
                        break

                if repo_name is None:
                    if sublime.ok_cancel_dialog(
                        'SublimeGerrit\n\nCould not determine project repository name to match your Gerrit project name.\n\nProceed with `%s`?' % self.commands[0]
                    ):
                        on_ok()

                elif repo_name != project_name:
                    if sublime.ok_cancel_dialog(
                        'SublimeGerrit\n\nLocal project name `%s` does not match Gerrit project name `%s`. Is it the same project?\n\nProceed with\n\n%s\n\nin\n\n%s\n\n?' % (repo_name, project_name, self.commands[0], self.working_dir)
                    ):
                        on_ok()

                else:
                    on_ok()

        Command('git remote -v', on_done=done)


class GitPush():

    def push(self, drafts=False):
        select_repository_menu(sublime.active_window(), lambda directory: self.do_push(directory, drafts))


    def do_push(self, directory, drafts):
        os.chdir(directory)

        Command.clear_output()

        def get_origin(exit_code, stdout, stderr):
            remotes = []

            if exit_code == 0:
                expected = '%s@%s' % (Settings.get('connection.username'), urlsplit(Settings.get('connection.url')).netloc.split(':')[0])

                for line in stdout:
                    matches = re.match('^([^\t]+)\t(.*)\s+\(push\)$', line)

                    if matches:
                        parsed = urlparse(matches.group(2))

                        if re.sub(':\d+$', '', parsed.netloc) == expected:
                            remotes.append({
                                'caption': [matches.group(1), matches.group(2)],
                                'name': matches.group(1)
                            })

            if len(remotes) == 0:
                error_message('Could not determine remote. Please push your changes manually.')
                return

            quick_panel(
                items=remotes,
                on_select=lambda selected: get_branch(selected['name'])
            )


        def get_branch(remote):
            Command(
                command='git rev-parse --abbrev-ref HEAD',
                on_done=lambda exit_code, stdout, stderr: exit_code == 0 and prompt(remote, stdout[0]),
                silent=True
            )


        def prompt(remote, branch):
            if branch == 'HEAD':
                branch = ''

            command = 'git push %s HEAD:refs/%s/' % (remote, 'drafts' if drafts else 'for')
            sublime.active_window().show_input_panel(command, branch, lambda text: submit(command + text), None, None)


        def submit(command):
            Command(
                command=command,
                on_done=lambda exit_code, stdout, stderr: None,
                on_failure=lambda exit_code, stdout, stderr: None
            )

        Command('git remote -v', on_done=get_origin, silent=True)


class AsyncProcess(object):
    done_stdout = True
    done_stderr = True
    on_finished_run = False

    def __init__(self, cmd, shell_cmd, env, listener, path="", shell=False):
        self.listener = listener

        startupinfo = None
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        if path:
            old_path = os.environ["PATH"]
            os.environ["PATH"] = os.path.expandvars(path)

        proc_env = os.environ.copy()
        proc_env.update(env)
        for k, v in proc_env.items():
            proc_env[k] = os.path.expandvars(v)

        if shell_cmd and sys.platform == "win32":
            self.proc = subprocess.Popen(shell_cmd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=True)
        elif shell_cmd and sys.platform == "darwin":
            self.proc = subprocess.Popen(["/bin/bash", "-l", "-c", shell_cmd], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=False)
        elif shell_cmd and sys.platform == "linux":
            self.proc = subprocess.Popen(["/bin/bash", "-c", shell_cmd], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=False)
        else:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, startupinfo=startupinfo, env=proc_env, shell=shell)

        if path:
            os.environ["PATH"] = old_path

        th1 = th2 = False
        if self.proc.stdout:
            th1 = threading.Thread(target=self.read_stdout)
            th1.start()

        if self.proc.stderr:
            th2 = threading.Thread(target=self.read_stderr)
            th2.start()

        ThreadProgress(th1 or th2, 'Running `%s`  ' % (cmd or shell_cmd))

    def exit_code(self):
        return self.proc.poll()

    def read_stdout(self):
        while True:
            data = os.read(self.proc.stdout.fileno(), 2**15)

            if len(data) > 0:
                self.done_stdout = False
                if self.listener:
                    for line in data.splitlines():
                        self.listener.on_stdout(self, self.decode(line))
            else:
                self.done_stdout = True
                self.proc.stdout.close()

                if self.listener and self.done_stderr and not self.on_finished_run:
                    self.on_finished_run = True
                    self.listener.on_finished(self)
                break

    def read_stderr(self):
        while True:
            data = os.read(self.proc.stderr.fileno(), 2**15)

            if len(data) > 0:
                self.done_stderr = False
                if self.listener:
                    for line in data.splitlines():
                        self.listener.on_stderr(self, self.decode(line))
            else:
                self.done_stderr = True
                self.proc.stderr.close()

                if self.listener and self.done_stdout and not self.on_finished_run:
                    self.on_finished_run = True
                    self.listener.on_finished(self)
                break

    def decode(self, line):
        try:
            return line.decode(sys.getfilesystemencoding())
        except:
            try:
                return line.decode('UTF-8')
            except:
                return line
