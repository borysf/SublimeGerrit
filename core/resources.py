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
import threading
import re

from .client import GerritClient
from .reader import DataReader
from .settings import Settings
from .thread_progress import ThreadProgress
from .utils import log, version_compare, error_message
from urllib.parse import quote, quote_plus

MIN_API_VERSION = '2.8'

def urlencode(d):
    s = []
    for name in d:
        s.append('%s=%s' % (name, quote_plus(str(d[name]).encode('utf-8'), ':')))

    return '&'.join(s)

class HttpThread(threading.Thread):
    API_VERSION = None
    SELF_DATA = None

    def __init__(self, kind, *request_args):
        self.request_args = request_args
        self.client = GerritClient({
            'username': Settings.get('connection.username'),
            'password': Settings.get('connection.password'),
            'url': Settings.get('connection.url'),
            'timeout': Settings.get('connection.timeout')
        })
        self.reader = DataReader(kind)
        self.callback = lambda data: None

        threading.Thread.__init__(self)

    def run(self):
        ThreadProgress(self, 'Contacting Gerrit...')

        if self.check_version():
            self.get_self_data()
            print(self.request_args)
            self.callback(self.reader.read(self.client.request(*self.request_args)))

    def set_connection_settings(self, connection_settings):
        self.client.connection = connection_settings

    def then(self, callback):
        self.callback = callback
        self.start()

    def check_version(self):
        if HttpThread.API_VERSION is None:
            version = self.client.request('GET', '/config/server/version', None, True)
            HttpThread.API_VERSION = version


        if HttpThread.API_VERSION and version_compare(HttpThread.API_VERSION, MIN_API_VERSION) < 0:
            error_message(
                'Gerrit version %s detected, but at least %s is required. This version is not supported due to missing API features.' % (HttpThread.API_VERSION, MIN_API_VERSION)
            )
            return False

        return True

    def get_self_data(self):
        if HttpThread.SELF_DATA is None:
            HttpThread.SELF_DATA = DataReader(None).read(self.client.request('GET', '/accounts/self', None, True))


class SilentHttpThread(HttpThread):
    def run(self):
        self.get_self_data()
        self.callback(self.reader.read(self.client.request(*self.request_args)))


class GerritResources():
    self_data = None

    def test(self, connection_settings):
        connection_settings['timeout'] = 10
        thread = self.changes(1, {'q': 'status:open'})
        thread.set_connection_settings(connection_settings)

        return thread

    def changes(self, limit, query):
        return HttpThread(
            'gerritcodereview#change',
            'GET',
            '/changes/?O=1&n=%d&%s' % (limit, urlencode(query))
        )

    def get_self(self):
        return HttpThread.SELF_DATA

    def check_changes(self, limit, query):
        return SilentHttpThread(
            None,
            'GET',
            '/changes/?O=1&n=%d&%s' % (limit, urlencode(query)),
            None,
            True
        )

    def change(self, change_id):
        opts = [
            'DOWNLOAD_COMMANDS',
            'ALL_REVISIONS',
            'DETAILED_LABELS',
            'CURRENT_ACTIONS',
            'MESSAGES',
            'DETAILED_ACCOUNTS',
            'ALL_COMMITS',
            'ALL_FILES',
            'DRAFT_COMMENTS'
        ]

        return HttpThread(
            'gerritcodereview#change',
            'GET',
            '/changes/%s/detail?o=%s' % (change_id, '&o='.join(opts))
        )

    def submit_type(self, change_id, revision_id):
        return HttpThread(
            None,
            'GET',
            '/changes/%s/revisions/%s/submit_type' % (change_id, revision_id)
        )

    def review(self, change_id, revision_id, review_data):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/revisions/%s/review' % (change_id, revision_id),
            review_data
        )

    def submit(self, change_id, revision_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/revisions/%s/submit' % (change_id, revision_id),
            {'wait_for_merge': True}
        )

    def rebase(self, change_id, revision_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/revisions/%s/rebase' % (change_id, revision_id)
        )

    def publish(self, change_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/publish' % (change_id)
        )

    def restore(self, change_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/restore' % (change_id)
        )

    def delete(self, change_id):
        return HttpThread(
            None,
            'DELETE',
            '/changes/%s' % (change_id)
        )

    def abandon(self, change_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/abandon' % (change_id)
        )

    def remove_reviewer(self, change_id, account_id):
        return HttpThread(
            None,
            'DELETE',
            '/changes/%s/reviewers/%s' % (change_id, account_id)
        )

    def suggest_reviewers(self, change_id, query='', limit=10):
        return HttpThread(
            'gerritcodereview#suggestedreviewer',
            'GET',
            '/changes/%s/suggest_reviewers?%s' % (change_id, urlencode({'q': query, 'n': limit}))
        )

    def add_reviewer(self, change_id, account_id):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/reviewers' % change_id,
            {'reviewer': account_id}
        )

    def diff(self, change_id, revision_id, filename, base=None):
        return HttpThread(
            None,
            'GET',
            '/changes/%s/revisions/%s/files/%s/diff?intraline&context=ALL%s' % (
                change_id,
                revision_id,
                quote(filename, ''),
                ('&base=%d' % base) if base is not None else ''
            )
        )

    def get_content(self, change_id, revision_id, filename):
        return HttpThread(
            None,
            'GET',
            '/changes/%s/revisions/%s/files/%s/content' % (change_id, revision_id, quote(filename, '')),
            None,
            True
        )

    def set_reviewed(self, change_id, revision_id, filename):
        return HttpThread(
            None,
            'PUT',
            '/changes/%s/revisions/%s/files/%s/reviewed' % (change_id, revision_id, quote(filename, '')),
            None,
            True
        )

    def set_topic(self, change_id, topic):
        return HttpThread(
            None,
            'PUT',
            '/changes/%s/topic' % (change_id),
            {'topic': topic}
        )

    def delete_topic(self, change_id):
        return HttpThread(
            None,
            'DELETE',
            '/changes/%s/topic' % (change_id)
        )

    def create_draft_comment(self, change_id, revision_id, side, path, line, message, in_reply_to=None):
        data = {
            'path': path,
            'line': line,
            'message': message,
            'side': side
        }

        if in_reply_to is not None:
            data.update({'in_reply_to': in_reply_to})

        return HttpThread(
            'gerritcodereview#comment',
            'PUT',
            '/changes/%s/revisions/%s/drafts' % (change_id, revision_id),
            data
        )

    def update_draft_comment(self, change_id, revision_id, side, draft_id, path, line, message, in_reply_to=None):
        data = {
            'path': path,
            'line': line,
            'message': message,
            'side': side
        }

        if in_reply_to is not None:
            data.update({'in_reply_to': in_reply_to})

        return HttpThread(
            'gerritcodereview#comment',
            'PUT',
            '/changes/%s/revisions/%s/drafts/%s' % (change_id, revision_id, draft_id),
            data
        )

    def get_draft_comments(self, change_id, revision_id):
        return HttpThread(
            None,
            'GET',
            '/changes/%s/revisions/%s/drafts' % (change_id, revision_id),
            None,
            True
        )

    def delete_draft_comment(self, change_id, revision_id, draft_id):
        return HttpThread(
            None,
            'DELETE',
            '/changes/%s/revisions/%s/drafts/%s' % (change_id, revision_id, draft_id)
        )

    def get_comments(self, change_id, revision_id):
        return HttpThread(
            None,
            'GET',
            '/changes/%s/revisions/%s/comments' % (change_id, revision_id),
            None,
            True
        )

    def edit_commit_message(self, change_id, revision_id, message):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/revisions/%s/message' % (change_id, revision_id),
            {'message': message}
        )

    def project_branches(self, project):
        return HttpThread(
            None,
            'GET',
            '/projects/%s/branches' % (quote(project, ''))
        )

    def cherry_pick_to(self, change_id, revision_id, destination, message):
        return HttpThread(
            None,
            'POST',
            '/changes/%s/revisions/%s/cherrypick' % (change_id, revision_id),
            {'message': message, 'destination': destination}
        )
