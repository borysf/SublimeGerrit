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
import urllib.request
import urllib.error
import base64

#import zlib

# from http.client import HTTPConnection
# from urllib.request import HTTPHandler

from .utils import error_message, log, version_compare
from .version import VERSION
from .settings import ConnectionSettings

def create_https_handler():
    if sublime.platform() == 'linux':
        import ssl
        import socket
        import http

        # must be called as a function because ssl module is available after Reloader loads it
        _strict_sentinel = object()

        "Class HTTPSConnection taken from Python 3.3"

        class HTTPSConnection(http.client.HTTPConnection):
            "This class allows communication via SSL."

            default_port = 443

            # XXX Should key_file and cert_file be deprecated in favour of context?

            def __init__(self, host, port=None, key_file=None, cert_file=None,
                         strict=_strict_sentinel, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                         source_address=None, *, context=None, check_hostname=None):
                super(HTTPSConnection, self).__init__(host, port, strict, timeout,
                                                      source_address)
                self.key_file = key_file
                self.cert_file = cert_file
                if context is None:
                    # Some reasonable defaults
                    context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
                    context.options |= ssl.OP_NO_SSLv2
                will_verify = context.verify_mode != ssl.CERT_NONE
                if check_hostname is None:
                    check_hostname = will_verify
                elif check_hostname and not will_verify:
                    raise ValueError("check_hostname needs a SSL context with "
                                     "either CERT_OPTIONAL or CERT_REQUIRED")
                if key_file or cert_file:
                    context.load_cert_chain(cert_file, key_file)
                self._context = context
                self._check_hostname = check_hostname

            def connect(self):
                "Connect to a host on a given (SSL) port."

                sock = socket.create_connection((self.host, self.port),
                                                self.timeout, self.source_address)

                if self._tunnel_host:
                    self.sock = sock
                    self._tunnel()

                server_hostname = self.host if ssl.HAS_SNI else None
                self.sock = self._context.wrap_socket(sock,
                                                      server_hostname=server_hostname)
                try:
                    if self._check_hostname:
                        ssl.match_hostname(self.sock.getpeercert(), self.host)
                except Exception:
                    self.sock.shutdown(socket.SHUT_RDWR)
                    self.sock.close()
                    raise

        class HTTPSHandler(urllib.request.UnknownHandler):
            def __init__(self, debuglevel=0, context=None, check_hostname=None):
                self._context = context

            def unknown_open(self, req):
                return urllib.request.HTTPHandler().do_open(HTTPSConnection, req, context=self._context)
    else:
        from urllib.request import HTTPSHandler
        import ssl

    return HTTPSHandler(context=ssl.SSLContext(ssl.PROTOCOL_SSLv3))

# class HTTP10Connection(HTTPConnection):
#     _http_vsn = 10
#     _http_vsn_str = "HTTP/1.0"


# class HTTP10Handler(HTTPHandler):
#     def http_open(self, req):
#         return self.do_open(HTTP10Connection, req)

# urllib fixes.
class Fixed_HTTPPasswordMgrWithDefaultRealm(urllib.request.HTTPPasswordMgrWithDefaultRealm):
    def add_password(self, username, password):
        self._authinfo = (username, password)

    def find_user_password(self, realm, authuri):
        return self._authinfo

    def is_suburi(self, base, test):
        return True


class Spied_HTTPBasicAuthHandler(urllib.request.HTTPBasicAuthHandler):
    def retry_http_basic_auth(*args):
        log('Using Basic Auth')

        return urllib.request.HTTPBasicAuthHandler.retry_http_basic_auth(*args)


class Spied_HTTPDigestAuthHandler(urllib.request.HTTPDigestAuthHandler):
    def retry_http_digest_auth(*args):
        log('Using Digest Auth')
        return urllib.request.HTTPDigestAuthHandler.retry_http_digest_auth(*args)


class GerritClient():
    def __init__(self, connection):
        self.connection = connection
        self.silent = False
        self.ssl_checked = False

    def request(self, method, path, body=None, silent=False):
        url = self.connection['url'] if 'url' in self.connection else ConnectionSettings.get_url()

        auth = 'username' in self.connection and self.connection['username'] and 'password' in self.connection and self.connection['password']
        self.silent = silent

        if auth:
            url += '/a' + path
        else:
            url += path

        if auth:
            password_mgr = Fixed_HTTPPasswordMgrWithDefaultRealm()
            password_mgr.add_password(self.connection['username'], self.connection['password'])
        else:
            password_mgr = None

        handlers = [
            create_https_handler(),
            Spied_HTTPDigestAuthHandler(password_mgr),
            Spied_HTTPBasicAuthHandler(password_mgr),
            urllib.request.ProxyDigestAuthHandler(password_mgr),
            urllib.request.ProxyBasicAuthHandler(password_mgr)
        ]

        opener = urllib.request.build_opener(*handlers)
        s = '%s:%s' % (self.connection['username'], self.connection['password'])

        headers = {
            'User-Agent': 'SublimeGerrit/' + VERSION
        }

        if isinstance(body, dict):
            headers.update({'Content-Type': 'application/json;charset=UTF-8'})
            body = sublime.encode_value(body, False).encode('utf-8')

        request = urllib.request.Request(url, data=body, headers=headers)
        request.get_method = lambda: method

        log('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>')
        log('REQUEST', method, url)
        for header in request.header_items():
            log('%s:%s' % header)
        log('')
        log(body)

        try:
            f = opener.open(request, timeout=int(self.connection['timeout']))
            data = f.read()
            # data = zlib.decompress(f.read(), 16+zlib.MAX_WBITS)

            f.close()

            log('<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<')
            log('RESPONSE', f.getcode())
            for header in f.getheaders():
                log('%s: %s' % header)
            log('')
            log(data)
            log('=====================================')

            for header in f.getheaders():
                name, value = header

                if name == 'Content-Type' and value.startswith('text/plain'):
                    return data.decode('utf-8')

            return sublime.decode_value(data[5:].decode('utf-8'))
        except urllib.error.HTTPError as e:
            log('urllib.error.HTTPError', e)

            if not silent:
                if e.code in [400, 409]:
                    error_message(e.read().decode('utf-8').strip())
                else:
                    error_message(str(e))

        except urllib.error.URLError as e:
            log('urllib.error.URLError', e)

            if not silent:
                reason = str(e.reason)

                if reason.startswith('[SSL:'):
                    error_message(str(e) + '\n\nProblem with SSL certificate?')
                else:
                    error_message(str(e))

        except Exception as e:
            log('urllib.error.*', e)

            if not silent:
                error_message(str(e))

        return None
