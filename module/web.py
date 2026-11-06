# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026-09-10 12:00:00
# File:web.py
import os
import re
import sys
import json
import time
import copy
import base64
import shutil
import socket
import asyncio
import datetime
import mimetypes
import threading

from typing import Union
from asyncio import AbstractEventLoop
from urllib.parse import (
    unquote,
    urlparse,
    parse_qs
)
from http.server import (
    ThreadingHTTPServer,
    BaseHTTPRequestHandler
)

from pyrogram import __version__ as pyrogram_version  # noqa.

from module import (
    log,
    console,
    VERSION_WITH_COMMIT
)
from module.remote import rc
from module.language import _t
from module.notice import NoticeHub
from module.parser import PARSE_ARGS
from module.path_tool import split_path
from module.storage import TRMDStorage
from module.stdio import (
    MetaData,
    PanelTable,
    ConnectionStatus
)
from module.task import (
    UploadTask,
    DownloadTask
)
from module.util import (
    ChatInfo,
    is_frozen,
    is_docker,
    get_local_ip,
    parse_chat_id,
    get_web_session,
    reset_web_session,
    get_message_dtype,
    get_work_directory,
    gen_random_credential
)
from module.enums import (
    Issues,
    WebMeta,
    KeyWord,
    UploadStatus,
    DownloadStatus,
    SaveDirectoryPrefix
)


class WebHandler(BaseHTTPRequestHandler):
    """Handle web-dashboard requests."""
    server_version: str = 'TRMDWeb'
    remember_session: bool = False  # Whether this response should set a cookie.
    expire_session: bool = False  # Whether this response should clear the cookie (logout).
    first_login: bool = False  # Whether this is the first request without a valid cookie.
    # Match the opening <body> tag so replacement still works if attributes are added to the template.
    BODY_TAG_PATTERN: bytes = rb'<body\b[^>]*>'
    # data-auth indicates that password authentication is enabled; the frontend uses it to show the logout option.
    FIRST_LOGIN_BODY: bytes = b'<body data-auth="1" data-first-login="1" data-bot="__HAS_BOT__" data-storage="__HAS_STORAGE__">'  # Mark the homepage on first login so it can automatically display the card.
    # Inject when a username and password are set: hide page content initially to prevent a flash of the logged-in view on refresh.
    LOGIN_BODY: bytes = b'<body data-auth="1" class="logged-out" data-bot="__HAS_BOT__" data-storage="__HAS_STORAGE__">'
    VERSION_PLACEHOLDER: bytes = b'__VERSION__'  # TRMD version placeholder in the homepage template, replaced with the actual version before responding.
    # Pyrogram version placeholder in the homepage template, replaced with the actual version before responding.
    PYROGRAM_PLACEHOLDER: bytes = b'__PYROGRAM_VERSION__'
    HAS_BOT_PLACEHOLDER: bytes = b'__HAS_BOT__'  # Whether a bot_token is configured; the frontend uses this to hide the upload and listener sidebars.
    HAS_STORAGE_PLACEHOLDER: bytes = b'__HAS_STORAGE__'  # Whether the history database is available; the frontend uses this to show the history sidebar.

    def do_GET(self) -> None:  # noqa.
        if self.path.startswith('/api/'):
            # Require authentication for API endpoints; allow pages and static assets so the login card can load.
            if self.__check_auth() is False:  # noqa.
                return
            if self.path.startswith('/api/progress'):
                self.__response_progress()
            elif self.path.startswith('/api/storage/disk'):
                self.__response_disk_usage()
            elif self.path.startswith('/api/storage'):
                self.__response_storages()
            else:
                self.send_error(404)
            return
        self.__response_static()

    def do_POST(self) -> None:  # noqa.
        if self.path.startswith('/api/login'):
            self.__response_login()  # The login endpoint itself must not be blocked by authentication.
            return
        if self.path.startswith('/api/logout'):
            self.__response_logout()  # The logout endpoint must not be blocked by authentication either.
            return
        if self.__check_auth() is False:  # noqa.
            return
        if self.path.startswith('/api/listener/remove'):
            self.__response_remove_listener()
        elif (self.path.startswith('/api/config/save_directory')
              or self.path.startswith('/api/config/max_tasks')
              or self.path.startswith('/api/config/max_retries')):
            self.__response_set_config()
        elif self.path.startswith('/api/pause'):
            self.__response_set_pause()  # The three legacy paths are equivalent; use one handler and persist changes only once.
        else:
            self.send_error(404)

    @staticmethod
    def replace_body_tag(body: bytes, tag: bytes) -> bytes:
        """Replace the homepage's opening <body> tag to inject authentication and bot markers.

        The template's <body> may have attributes, so a fixed-string replacement could miss it;
        use a regular expression to match the opening tag itself.
        """
        return re.sub(WebHandler.BODY_TAG_PATTERN, tag, body, count=1)

    def log_message(self, fmt, *args) -> None:
        """Suppress default request logs to avoid cluttering terminal output."""

    def __check_auth(self) -> bool:
        """Check authentication: prefer cookie-based access, then a temporary frontend token, and finally Basic authentication."""
        self.remember_session = False
        self.first_login = False
        web: Union[Web, None] = getattr(self.server, 'web', None)
        if web is None or not web.username:
            return True
        if web.check_session(self.__get_cookie()):
            return True  # This browser is remembered; no password is needed again.
        authorization: str = self.headers.get('Authorization', '')
        if authorization.startswith('Bearer '):
            # Without "Stay logged in for 30 days", do not set a cookie; the frontend stores the token in
            # sessionStorage and sends it with requests, so it expires when the tab is closed.
            if web.check_session(authorization.split(' ', 1)[1].strip()):
                return True
        if not authorization.startswith('Basic '):
            self.__response_unauthorized()
            return False
        try:
            credential: str = base64.b64decode(authorization.split(' ', 1)[1]).decode('UTF-8')
        except Exception:  # noqa.
            self.__response_unauthorized()
            return False
        if credential != f'{web.username}:{web.password}':
            self.__response_unauthorized()
            return False
        self.remember_session = True  # First authentication succeeded; set a cookie in the response.
        self.first_login = True  # No valid cookie was included, so this is the first login.
        return True

    def __get_cookie(self) -> str:
        """Read the cookie with the configured name from the request headers."""
        for item in self.headers.get('Cookie', '').split(';'):
            name, _, value = item.strip().partition('=')
            if name == WebMeta.COOKIE_NAME:
                return value
        return ''

    def __response_unauthorized(self) -> None:
        """Return an authentication-required response.

        Do not send WWW-Authenticate, which would open the browser's native credential dialog and
        bypass the page styling; let the frontend show its frosted-glass login card instead.
        """
        self.send_response(401)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def __response_login(self) -> None:
        """Validate the username and password submitted by the login card.

        Set a long-lived cookie only when "Stay logged in for 30 days" is selected. Otherwise,
        return the token for the frontend to store in sessionStorage; closing the tab then requires
        logging in again.
        """
        web: Union[Web, None] = getattr(self.server, 'web', None)
        payload: dict = self.__read_json()
        ok: bool = False
        if web is not None:
            if not web.username:  # Allow access directly when no username and password are configured.
                ok = True
            else:
                username: str = str(payload.get('username') or '')
                password: str = str(payload.get('password') or '')
                ok = username == web.username and password == web.password
        if ok:
            # When the option is unchecked, leave remember_session false and do not set a cookie.
            self.remember_session = bool(payload.get('remember'))
            self.first_login = bool(web and web.username)
        self.__response_body(
            body=json.dumps(
                {
                    'status': ok,
                    'first_login': bool(ok and web and web.username),
                    'token': web.token if (ok and web is not None) else ''
                },
                ensure_ascii=False
            ).encode('UTF-8'),
            content_type='application/json; charset=utf-8',
            status=200 if ok else 401
        )

    def __response_session_cookie(self) -> None:
        """Set or clear the cookie.

        Set a long-lived cookie when "Stay logged in for 30 days" is selected; on logout, set an
        immediately expired cookie to clear it.
        """
        web: Union[Web, None] = getattr(self.server, 'web', None)
        if web is None:
            return
        if self.remember_session:
            cookie: str = (
                f'{WebMeta.COOKIE_NAME}={web.token}; '
                f'Max-Age={Web.REMEMBER_COOKIE_MAX_AGE}; Path=/; HttpOnly; SameSite=Lax'
            )
        elif self.expire_session:
            # Max-Age=0 makes the browser discard the cookie immediately (HttpOnly cookies cannot be deleted by frontend JavaScript).
            cookie = f'{WebMeta.COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax'
        else:
            return
        self.send_header('Set-Cookie', cookie)

    def __response_logout(self) -> None:
        """Log out: rotate the token to invalidate all issued cookies and clear this browser's cookie."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        if web is not None:
            web.logout()
        self.expire_session = True
        self.__response_body(
            body=json.dumps({'status': True}, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_body(self, body: bytes, content_type: str, status: int = 200) -> None:
        """Return a response with the given content; status is used to return 401 for failed logins."""
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')  # Disable caching so the browser does not reuse an old page.
        self.__response_session_cookie()
        try:
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as e:
            log.info(f'Client interrupted response writing, {_t(KeyWord.REASON)}:"{e}"')

    def __response_progress(self) -> None:
        """Return progress data as JSON."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        query: dict = parse_qs(urlparse(self.path).query)
        section: str = (query.get('section') or [''])[0]
        data: dict = web.snapshot(section=section) if web else {}
        self.__response_body(
            body=json.dumps(data, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_storages(self) -> None:
        """Return download/upload history as JSON, checking whether files exist during each read and discarding missing entries.

        Return all records of the requested type; pagination and grouping by channel are handled by the frontend.
        """
        web: Union[Web, None] = getattr(self.server, 'web', None)
        query: dict = parse_qs(urlparse(self.path).query)
        storage_type: str = (query.get('type') or [''])[0]
        storages: list = web.get_storage(storage_type=storage_type) if web else []
        self.__response_body(
            body=json.dumps({'storage': storages}, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_disk_usage(self) -> None:
        """Return disk-space information for the download directory as JSON."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        data: dict = web.disk_usage() if web else {}
        self.__response_body(
            body=json.dumps(data, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __read_json(self) -> dict:
        """Read JSON data from the request body, returning an empty dict if parsing fails."""
        try:
            length: int = int(self.headers.get('Content-Length') or 0)
        except (TypeError, ValueError):
            return {}
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode('UTF-8'))
        except Exception as e:
            log.debug(f'Failed to parse request data, {_t(KeyWord.REASON)}:"{e}"')
            return {}

    def __response_remove_listener(self) -> None:
        """Handle requests to remove download and forwarding listeners."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        payload: dict = self.__read_json()
        if web is None:
            body: dict = {'status': False, 'e_code': 'Web dashboard is not ready.'}
        else:
            body: dict = web.remove_listener(
                kind=str(payload.get('kind') or ''),
                link=str(payload.get('link') or '')
            )
        self.__response_body(
            body=json.dumps(body, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_set_config(self) -> None:
        """Handle configuration changes from the web panel.

        The legacy save_directory, max_tasks, and max_retries paths are equivalent here: read all
        fields from the request body at once and pass them to Web.set_config, so multiple changes
        are persisted with a single configuration-file write.
        """
        web: Union[Web, None] = getattr(self.server, 'web', None)
        payload: dict = self.__read_json()
        if web is None:
            body: dict = {'status': False, 'e_code': 'Web dashboard is not ready'}  # The frontend adds the final period.
        else:
            body: dict = web.set_config(
                directory=payload.get('save_directory'),
                max_tasks=payload.get('max_tasks'),
                max_retries=payload.get('max_retries'),
                confirm_directory=bool(payload.get('confirm_directory'))
            )
        self.__response_body(
            body=json.dumps(body, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_set_pause(self) -> None:
        """Handle requests to pause or resume globally."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        payload: dict = self.__read_json()
        if web is None:
            body: dict = {'status': False, 'e_code': 'Web dashboard is not ready.'}
        else:
            body: dict = web.set_pause(bool(payload.get('paused')))
        self.__response_body(
            body=json.dumps(body, ensure_ascii=False).encode('UTF-8'),
            content_type='application/json; charset=utf-8'
        )

    def __response_static(self) -> None:
        """Return a file from the web templates or static directory."""
        web: Union[Web, None] = getattr(self.server, 'web', None)
        if web is None:
            self.send_error(404)
            return
        name: str = unquote(self.path.split('?')[0].lstrip('/'))
        if not name or name in Web.TEMPLATE_FILES:  # The root path serves the homepage; registered template names are served from the template directory.
            root: str = os.path.abspath(web.template_directory)
            file_path: str = os.path.join(root, name or Web.INDEX_FILE)
        else:
            root = os.path.abspath(web.static_directory)
            file_path = os.path.abspath(os.path.join(root, name))
        if os.path.commonpath([root, file_path]) != root:  # Prevent access to files outside the web directory.
            self.send_error(403)
            return
        if not os.path.isfile(file_path):
            self.send_error(404)
            return
        body: bytes = b''
        try:
            with open(file=file_path, mode='rb') as f:
                body = f.read()
        except OSError as e:
            log.warning(f'Failed to read web file "{file_path}", {_t(KeyWord.REASON)}:"{e}"')
            self.send_error(404)
            return
        if os.path.basename(file_path) == Web.INDEX_FILE:  # Replace markers and version numbers on the homepage.
            # body is assigned by this point (read from the file on the normal path; errors returned above).
            # Copy it to page and base all later replacements on that value, rather than referring to
            # body assigned inside the try block in separate branches.
            page: bytes = body  # type: ignore[reportPossiblyUnboundVariable]
            if self.first_login:
                page = WebHandler.replace_body_tag(page, WebHandler.FIRST_LOGIN_BODY)
            elif web and web.username:
                page = WebHandler.replace_body_tag(
                    page,
                    WebHandler.LOGIN_BODY
                )  # For authenticated pages, hide content immediately and let the frontend remove this class after login to prevent a flash on refresh.
            page = page.replace(
                WebHandler.VERSION_PLACEHOLDER,
                f'{VERSION_WITH_COMMIT}'.encode('UTF-8')
            )
            page = page.replace(
                WebHandler.PYROGRAM_PLACEHOLDER,
                f'{pyrogram_version}'.encode('UTF-8')
            )
            page = page.replace(  # Inject whether a bot is configured; the frontend uses this to hide the upload and listener sidebars.
                WebHandler.HAS_BOT_PLACEHOLDER,
                b'1' if (web and web.has_bot) else b'0'
            )
            page = page.replace(  # Inject whether the history database is available; the frontend uses this to show the history sidebar.
                WebHandler.HAS_STORAGE_PLACEHOLDER,
                b'1' if (web and web.has_storage) else b'0'
            )
            body = page
        content_type: str = mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        if content_type.startswith('text/'):
            content_type: str = f'{content_type}; charset=utf-8'
        self.__response_body(body=body, content_type=content_type)


class Web:
    # Directory conventions for web-panel assets.
    # templates stores HTML pages; register new page names here for routing.
    # static stores assets in type-specific subdirectories (css, js, img, fonts, vendor).
    # Pages reference them using paths relative to the site root, such as "css/style.css".
    TEMPLATE_DIRECTORY: str = os.path.join('module', 'templates')
    STATIC_DIRECTORY: str = os.path.join('module', 'static')
    INDEX_FILE: str = 'index.html'
    TEMPLATE_FILES: tuple = ('index.html',)  # Pages served from the template directory; all other requests are treated as static assets.
    UNGROUPED: str = 'Ungrouped'
    REMOVE_LISTEN_TIMEOUT: int = 10  # Timeout in seconds when waiting for the event loop to remove a listener.
    REMEMBER_COOKIE_MAX_AGE: int = 30 * 24 * 3600  # Cookie lifetime in seconds (30 days).
    STORAGE_TIMEOUT: int = 3  # Timeout in seconds when waiting for the event loop to return web history.
    CACHE_SIZE_INTERVAL: int = 30  # Minimum interval in seconds between cache-size recalculations; a full traversal is expensive and should not run on each 3-second poll.
    UNFINISHED_STATE: tuple = (
        DownloadStatus.PENDING,
        DownloadStatus.DOWNLOADING
    )  # Message states that have not yet reached a result.
    LOCAL_IP: str = get_local_ip()

    def __init__(self, progress, app=None, downloader=None):
        self.progress = progress
        self.app = app
        self.downloader = downloader  # Downloader instance, used to read registered listener information.
        self.cache_size_stamp: float = 0.0  # Time of the last cache-size calculation, used for throttling.
        self.cache_size_value: int = 0  # Cache-directory size in bytes from the last calculation.
        self.filled_chat_ids: set = set()  # Channel IDs whose titles were backfilled, to avoid repeated scans and writes.
        self.has_bot = bool(app and getattr(app, 'bot_token', None))  # Whether a bot is configured; controls the upload/listener sidebars (only downloads are available without a bot).
        self.credential: dict = gen_random_credential()
        self.protocol: str = 'http'
        self.ip: str = '0.0.0.0'
        self.port: int = self.get_free_port(PARSE_ARGS.port)
        self.username: str = self.credential.get(WebMeta.USERNAME)
        self.password: str = self.credential.get(WebMeta.PASSWORD)
        self.token: str = get_web_session()  # Token that keeps the browser logged in after a software restart.
        self.template_directory, self.static_directory = self.get_web_directory()
        self.server: Union[ThreadingHTTPServer, None] = None
        self.thread: Union[threading.Thread, None] = None

    @property
    def has_storage(self) -> bool:
        """Whether the history database is available, determining whether the frontend shows the history entry.

        The database opens only after a successful login, so unlike has_bot this cannot be determined
        during initialization and must be checked at runtime.
        """
        return bool(getattr(self.downloader, 'storage_database', None))

    @staticmethod
    def __bind_port(port: int) -> int:
        """Bind the specified port and return the port actually used."""
        # Do not set SO_REUSEADDR: on Windows this can bind to an occupied port and let another process take over connections.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', port))
            return s.getsockname()[1]

    @staticmethod
    def get_free_port(port: int) -> int:
        """Get an available port, automatically assigning one if the specified port is occupied."""
        try:
            return Web.__bind_port(port)
        except OSError as e:
            log.warning(f'Port {port} is unavailable; assigned a new port, {_t(KeyWord.REASON)}:"{e}"')
            return Web.__bind_port(0)

    @staticmethod
    def get_web_directory() -> tuple:
        """Get the web-template and static-asset directories, using the extracted resource directory in a packaged environment."""
        base_directory: str = get_work_directory()
        if is_frozen():
            base_directory = getattr(sys, '_MEIPASS', sys.prefix)  # noqa.
        template_directory: str = os.path.join(base_directory, Web.TEMPLATE_DIRECTORY)
        static_directory: str = os.path.join(base_directory, Web.STATIC_DIRECTORY)
        log.info(f'Web template directory: "{template_directory}"; static assets directory: "{static_directory}".')
        return template_directory, static_directory

    @staticmethod
    def format_seconds(seconds: Union[int, float, None]) -> str:
        """Format seconds as a readable remaining-time string."""
        if seconds is None:
            return ''
        seconds: int = int(seconds)
        if seconds < 60:
            return f'{seconds} sec'
        if seconds < 3600:
            return f'{seconds // 60} min {seconds % 60} sec'
        return f'{seconds // 3600} hr {seconds % 3600 // 60} min {seconds % 60} sec'

    def start(self) -> bool:
        """Start the web panel in a background thread."""
        for directory in (self.template_directory, self.static_directory):
            if not os.path.isdir(directory):
                log.error(f'Failed to start web dashboard: web directory not found: "{directory}".')
                return False
        try:
            self.server = ThreadingHTTPServer((self.ip, self.port), WebHandler)  # type: ignore[arg-type]
        except OSError as e:
            log.error(f'Failed to start web dashboard, {_t(KeyWord.REASON)}:"{e}"')
            return False
        self.server.web = self
        # Make request-handler threads daemons so persistent connections or in-flight requests do not block shutdown.
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, name='TRMDWeb', daemon=True)
        self.thread.start()
        log.info(f'Web dashboard started at "{self.protocol}://{self.LOCAL_IP}:{self.port}".')
        self.print_meta()
        console.log(Issues.DOCKER_HOST_IP_TIP, style='#5AC8FA') if is_docker() else None
        return True

    def stop(self) -> None:
        """Stop the web panel."""
        srv = self.server
        if srv is None:
            return
        self.server = None
        # Run serve_forever shutdown in a daemon thread: with persistent connections or in-flight requests,
        # shutdown() may block forever in __is_shut_down.wait(), leaving the program hung after Ctrl+C
        # and requiring repeated interrupts to exit.
        shutdown_thread = threading.Thread(target=srv.shutdown, daemon=True)
        shutdown_thread.start()
        shutdown_thread.join(timeout=3)
        try:
            srv.server_close()
        except Exception as e:  # noqa: BLE001.
            log.debug(f'Failed to close web dashboard listening socket, {_t(KeyWord.REASON)}:"{e}"')
        log.info('Web dashboard stopped.')

    def print_meta(self) -> None:
        """Print the web panel's access information."""
        PanelTable(
            title='Web Dashboard',
            header=('Property', 'Value'),
            data=[
                [_t(WebMeta.PORT), self.port],
                [_t(WebMeta.USERNAME), self.username],
                [_t(WebMeta.PASSWORD), self.password],
                ['URL', f'{self.protocol}://{Web.LOCAL_IP}:{self.port}']
            ],
            show_lines=True
        ).print_meta()

    def check_session(self, token: str) -> bool:
        """Validate a token submitted by the browser for password-free login."""
        return bool(token) and token == self.token

    def logout(self) -> None:
        """Log out by generating and saving a new token, invalidating all issued cookies."""
        self.token = reset_web_session()

    @staticmethod
    def get_outer_links() -> dict:
        """Get external links for the header and menu, falling back to built-in defaults when remote configuration is missing."""
        config: dict = rc.cached_config()
        return {
            'github': config.get('github', rc.DEFAULT_GITHUB) + '/releases',
            'subscribe_channel': config.get('subscribe_channel', rc.DEFAULT_SUBSCRIBE_CHANNEL),
            'video_tutorial': config.get('video_tutorial', rc.DEFAULT_VIDEO_TUTORIAL),
            'proxy_seller': config.get('proxy_seller', rc.DEFAULT_PROXY_SELLER)
        }

    def get_count(self) -> dict:
        """Aggregate the number of successful, failed, and skipped download tasks."""
        count: dict = {'success': 0, 'failure': 0, 'skip': 0}
        if self.app is None:
            return count
        for name, value in list(vars(self.app).items()):
            if not isinstance(value, set):
                continue
            if name.startswith('success_'):
                count['success'] += len(value)
            elif name.startswith('failure_'):
                count['failure'] += len(value)
            elif name.startswith('skip_'):
                count['skip'] += len(value)
        # Link-level parse failures (such as a missing channel) are recorded only as a -1 sentinel in
        # task.fail_id, not in the app-level failure_* sets.
        # Count them separately so the web panel's failure-card total matches the visible failed links
        # without affecting app-level statistics.
        for _task in list(DownloadTask.TASKS.values()):
            if -1 in _task.fail_id:
                count['failure'] += 1
        return count

    def get_link_progress(self) -> list:
        """Get progress for each download link and all its message members, including completed, skipped, and failed members."""
        result: list = []
        try:
            for link, task in list(DownloadTask.TASKS.items()):
                member_num: int = int(task.member_num or 0)
                complete_num: int = int(task.complete_num or 0)
                fail_num: int = int(task.fail_num or 0)
                members: list = self.get_members(task=task)
                unfinished: int = len(
                    [i for i in members if i.get('state') in Web.UNFINISHED_STATE]
                )
                base_num: int = max(member_num - fail_num, 0)  # Exclude permanently failed members from the progress base so progress can reach 100%.
                result.append({
                    'link': str(link),
                    'channel': str(task.chat_id or ''),
                    'channel_name': Web.format_channel(str(task.chat_id or ''), parse_chat_id(task.link)),
                    'complete': complete_num,
                    'member': member_num,
                    'failed': fail_num,
                    'remaining': max(member_num - complete_num - fail_num, 0),
                    'queue': members,
                    'queue_total': unfinished,
                    'total': len(members),
                    'percent': round(complete_num / base_num * 100, 1) if base_num else 0.0
                })
        except Exception as e:
            log.debug(f'Error getting link progress, {_t(KeyWord.REASON)}: "{e}"')
        return result

    def get_members(self, task: DownloadTask) -> list:
        """Get display information for all message members under a link.

        Original messages are available for queued items, so their file names and sizes can be
        completed. Completed or failed messages have been removed from the queue, so use the
        information saved when they were registered.
        """
        result: list = []
        for message_id, member in list(task.member_info.items()):
            item: dict = task.items.get(message_id) or {}
            meta: dict = self.format_queue_message(item, member.get('state')) if item else {}
            result.append({
                'name': member.get('name') or meta.get('name') or f'Message {message_id}',
                'size': member.get('size') or meta.get('size') or '',
                'size_byte': int(member.get('size_byte') or 0),
                'date': member.get('date') or meta.get('date') or '',
                'state': member.get('state') or DownloadStatus.PENDING,
                'task_id': member.get('task_id'),
                'note': member.get('note') or ''
            })
        return result

    def format_queue_message(self, item: dict, state: Union[str, None] = None) -> dict:
        """Parse and cache display information for a queued message to avoid repeating the work on each poll."""
        meta: Union[dict, None] = item.get('meta')
        if meta is None:
            meta = self.parse_queue_message(item)
            item['meta'] = meta
        meta['state'] = str(state or '')  # Queue state changes, so do not cache it.
        return meta

    def parse_queue_message(self, item: dict) -> dict:
        """Parse the name, size, and date of a queued message."""
        message = item.get('message')
        result: dict = {'name': 'Message ' + str(getattr(message, 'id', '')), 'size': '', 'date': ''}
        try:
            result['date'] = str(getattr(message, 'date', '') or '')[:10]
            if self.app is None:
                return result
            dtype: Union[str, None] = get_message_dtype(message, self.app.download_type)
            if dtype:
                result['name'] = str(split_path(self.app.get_temp_file_path(message, dtype)).get('file_name'))
                result['size'] = MetaData.suitable_units_display(getattr(getattr(message, dtype), 'file_size', 0))
        except Exception as e:
            log.debug(f'Error parsing queued message, {_t(KeyWord.REASON)}: "{e}"')
        return result

    def get_listeners(self) -> dict:
        """Get registered download and forwarding listener information.

        Returns:
            dict: download contains download-listener channel links; forward contains source and target channels for forwarding.
        """
        result: dict = {'download': [], 'forward': []}
        if self.downloader is None:
            return result
        try:
            result['download'] = [str(link) for link in list(self.downloader.listen_download_chat)]
            for rule in list(self.downloader.listen_forward_chat):
                args: list = str(rule).split()
                if len(args) != 2:
                    continue  # Forwarding rules must have exactly two parts, "source channel target channel"; skip malformed rules.
                result['forward'].append({'source': args[0], 'target': args[1]})
        except Exception as e:
            log.debug(f'Error getting listener information, {_t(KeyWord.REASON)}: "{e}"')
        return result

    @staticmethod
    def get_notices() -> dict:
        """Get notifications registered with the notice center, grouped by type for the Notices section."""
        return NoticeHub.snapshot()

    def get_storage(self, storage_type: str = '') -> list:
        """Read web download/upload history.

        The read must run on the downloader's event loop (the loop thread owns the database
        connection). As with listener removal, submit it with run_coroutine_threadsafe and wait
        for the result. The database first uses directory mtimes as a shortcut to check whether
        files exist, discarding missing entries. Return all records of the requested type;
        pagination and grouping by channel are handled by the frontend.

        Args:
            storage_type: Record type: download or upload; empty returns all records.

        Returns:
            list: Display information for the records.
        """
        if self.downloader is None:
            return []
        storage_db = getattr(self.downloader, 'storage_database', None)
        if storage_db is None:
            return []
        loop: Union[AbstractEventLoop, None] = getattr(self.downloader, 'loop', None)
        if loop is None or not loop.is_running():
            return []
        try:
            future = asyncio.run_coroutine_threadsafe(
                storage_db.get_storages(storage_type=storage_type or None),
                loop
            )
            storages: list = future.result(timeout=Web.STORAGE_TIMEOUT)
        except Exception as e:
            log.debug(f'Failed to get web history, {_t(KeyWord.REASON)}: "{e}"')
            return []
        self.__fill_storage_chat_names(storages)  # Add any cached titles to the records so they display as "title (ID)".
        return [Web.format_storage(storage) for storage in storages]

    def disk_usage(self) -> dict:
        """Return disk-space information for the save-directory volume and cache usage for the Storage page.

        On Windows, query the drive root: the drive defines the filesystem boundary, regardless of
        wildcards or intermediate path components. Unix-like systems have a single "/" root that
        may span multiple mount points (especially with Docker bind mounts), so query the nearest
        existing directory under the save path to find the correct filesystem. shutil.disk_usage
        handles Windows, Linux, and macOS uniformly (using GetDiskFreeSpaceEx or statvfs internally),
        so the query itself needs no platform-specific branch.

        Returns:
            dict: directory, total, used, free, percent, and display text for the disk,
                plus cache_directory, cache_size, and cache_text for the cache directory.
        """
        directory: str = self.app.save_directory if self.app else ''
        root: str = ''
        if directory:
            if sys.platform == 'win32':
                # On Windows, the drive root is the target filesystem; no need to resolve placeholders such as %CHAT_NAME%.
                drive, _ = os.path.splitdrive(os.path.abspath(directory))
                root = drive + os.sep if drive else os.sep
            else:
                # On Unix-like systems the root may span mount points, so query the nearest existing directory instead.
                root = os.path.abspath(directory)
                drive, _ = os.path.splitdrive(root)
                volume: str = drive + os.sep if drive else os.sep
                while root and not os.path.isdir(root):
                    parent = os.path.dirname(root.rstrip(os.sep))
                    if not parent or parent == root:
                        root = ''
                        break
                    root = parent
                if root == volume:
                    root = ''  # The entire path is missing; do not use the root directory as a substitute.
        data: dict = {'directory': directory}
        try:
            usage = shutil.disk_usage(root or os.getcwd())
        except Exception as e:
            log.debug(f'Failed to read disk space, {_t(KeyWord.REASON)}: "{e}"')
            data.update({'total': 0, 'used': 0, 'free': 0, 'percent': 0.0})
        else:
            total: int = int(usage.total)
            used: int = int(usage.used)
            free: int = int(usage.free)
            data.update({
                'total': total,
                'used': used,
                'free': free,
                'percent': round(used * 100 / total, 1) if total else 0.0,
                'used_text': 'Used: {0}'.format(MetaData.suitable_units_display(used)),
                'free_text': 'Free: {0}'.format(MetaData.suitable_units_display(free)),
                'total_text': 'Total: {0}'.format(MetaData.suitable_units_display(total))
            })
        data.update(self.cache_size())
        return data

    def cache_size(self) -> dict:
        """Measure the cache directory's disk usage, throttling recalculations to avoid a full traversal on every poll.

        The cache directory also supports wildcards, so walk up to the nearest existing directory
        before traversing it; placeholder paths are simply deeper subdirectories of the same cache.

        Returns:
            dict: cache_directory, cache_size (bytes), and cache_text (display text).
        """
        directory: str = self.app.temp_directory if self.app else ''
        result: dict = {
            'cache_directory': directory,
            'cache_size': 0,
            'cache_text': '0.00B'
        }
        if not directory:
            return result
        now: float = time.monotonic()
        if now - self.cache_size_stamp >= Web.CACHE_SIZE_INTERVAL:
            # Set the timestamp before traversing; requests arriving during the walk reuse the previous result instead of starting concurrent walks.
            self.cache_size_stamp = now
            total: int = 0
            real: str = os.path.abspath(directory)
            drive, _ = os.path.splitdrive(real)
            volume: str = drive + os.sep if drive else os.sep
            while real and not os.path.isdir(real):
                parent: str = os.path.dirname(real.rstrip(os.sep))
                if not parent or parent == real:
                    real = ''
                    break
                real = parent
            if real == volume:
                # The cache path does not exist; do not count the whole volume as cache, which would be meaningless and very slow to traverse.
                real = ''
            if real:
                for walk_root, _, files in os.walk(real):
                    for name in files:
                        try:
                            total += os.path.getsize(os.path.join(walk_root, name))
                        except OSError:
                            continue  # The file is in use by a download or has been deleted; skip it.
            self.cache_size_value = total
        result['cache_size'] = self.cache_size_value
        result['cache_text'] = MetaData.suitable_units_display(self.cache_size_value)
        return result

    @staticmethod
    def format_storage(storage: TRMDStorage) -> dict:
        """Format a web-history record for display, preferring its saved channel title as in the download section's "title (ID)" style."""
        chat_id: str = str(storage.chat_id) if storage.chat_id is not None else ''
        display_id: str = parse_chat_id(storage.link, chat_id)
        chat_name: str = storage.chat_name or ChatInfo.get(display_id)
        return {
            'storage_id': storage.storage_id,
            'storage_type': storage.storage_type,
            'channel': chat_id,
            'chat': f'{chat_name}({display_id})' if chat_name and display_id else (display_id or Web.UNGROUPED),
            'message_id': storage.message_id if storage.message_id is not None else '',
            'file': storage.file_name,
            'path': storage.file_path,
            'size': MetaData.suitable_units_display(storage.file_size),
            'size_byte': storage.file_size,
            'type': storage.file_type,
            'status': _t(storage.status),
            'state': storage.status,
            'error': storage.error_msg,
            'link': storage.link,
            'time': datetime.datetime.fromtimestamp(storage.finish_time).strftime(
                '%Y-%m-%d %H:%M:%S') if storage.finish_time else ''
        }

    def __fill_storage_chat_names(self, storages: list) -> None:
        """Fill in record titles from the ChatInfo cache and asynchronously write them back to the database.

        If a title was not cached when the record was written, chat_name is empty. A later download
        or upload may cache the title; fill it in when reading so history shows "title (ID)" instead
        of a bare ID. Submit the write-back without waiting, so failures do not affect this display;
        update each channel only once.
        """
        storage_db = getattr(self.downloader, 'storage_database', None)
        loop: Union[AbstractEventLoop, None] = getattr(self.downloader, 'loop', None)
        if storage_db is None or loop is None or not loop.is_running():
            return
        pending: dict = {}
        for storage in storages:
            chat_id: str = str(storage.chat_id or '')
            if not chat_id or storage.chat_name or chat_id in self.filled_chat_ids:
                continue
            title: str = ChatInfo.get(chat_id)
            if title:
                storage.chat_name = title
                pending[chat_id] = title
        if not pending:
            return
        self.filled_chat_ids.update(pending.keys())
        try:
            asyncio.run_coroutine_threadsafe(storage_db.update_chat_names(pending), loop)
        except Exception as e:
            log.debug(f'Failed to backfill the channel title in the web history, {_t(KeyWord.REASON)}: "{e}"')

    def remove_listener(self, kind: str, link: str) -> dict:
        """Remove a registered download or forwarding listener at the web panel's request.

        Removal must run on the downloader's event loop so the user client can safely send a
        command to the bot. The web panel runs on a separate HTTP thread, so submit the coroutine
        to the event loop and wait for its result.

        Args:
            kind: Listener type: download or forward.
            link: A channel link for a download listener; "source channel target channel" for forwarding.

        Returns:
            dict: status indicates whether removal succeeded; e_code contains the reason for failure.
        """
        if self.downloader is None:
            return {'status': False, 'e_code': 'The web dashboard is not connected to the downloader.'}
        loop: Union[AbstractEventLoop, None] = self.downloader.loop
        if loop is None or not loop.is_running():
            return {'status': False, 'e_code': 'The downloader is not running, so listeners cannot be removed.'}
        future = asyncio.run_coroutine_threadsafe(
            self.downloader.cancel_listen_from_web(kind=kind, link=link),
            loop
        )
        try:
            return future.result(timeout=Web.REMOVE_LISTEN_TIMEOUT)
        except Exception as e:
            log.debug(f'Failed to remove listener, {_t(KeyWord.REASON)}:"{e}"')
            return {'status': False, 'e_code': 'Removing the listener timed out. Please try again later.'}

    def set_pause(self, paused: bool) -> dict:
        """Toggle the global pause state at the web panel's request.

        The flag and pause event must be changed on the downloader's event-loop thread. Since the
        web panel runs on a separate HTTP thread, use call_soon_threadsafe to schedule the change
        on the event loop.

        Args:
            paused: True to pause, False to resume.

        Returns:
            dict: status indicates whether the change succeeded; e_code contains the reason for failure.
        """
        if self.app is None:
            return {'status': False, 'e_code': 'Configuration is not loaded, so the task cannot be paused.'}
        if self.downloader is None:
            return {'status': False, 'e_code': 'The web dashboard is not connected to the downloader.'}
        loop: Union[AbstractEventLoop, None] = self.downloader.loop
        if loop is None or not loop.is_running():
            return {'status': False, 'e_code': 'The downloader is not running, so tasks cannot be paused.'}

        def apply(_paused: bool) -> None:
            # Change the flag and event in order within one closure so the HTTP thread cannot read an inconsistent intermediate state.
            self.app.is_paused = _paused
            if _paused:
                self.downloader.pause_event.clear()
            else:
                self.downloader.pause_event.set()

        loop.call_soon_threadsafe(apply, paused)  # Schedule the change on the event-loop thread; no need to wait to confirm it was queued.
        return {'status': True}

    @staticmethod
    def __check_number_pair(
            values: Union[dict, None],
            lower: int,
            upper: Union[int, None],
            name: str,
            range_text: str,
            error_parts: list
    ) -> Union[dict, None]:
        """Validate a set of download/upload values, appending errors to error_parts when invalid.

        Args:
            values: Values in the form {'download': int, 'upload': int}; None means no change this time.
            lower: Inclusive minimum value.
            upper: Inclusive maximum value; None means there is no upper limit.
            name: Setting name, used to build the failure message.
            range_text: Message to use when a value is out of range.
            error_parts: List that collects failure reasons.

        Returns:
            dict | None: Normalized values if valid; None if unchanged or validation fails.
        """
        if values is None:
            return None
        try:
            result: dict = {'download': int(values.get('download')), 'upload': int(values.get('upload'))}
        except (AttributeError, TypeError, ValueError):
            error_parts.append(f'{name} must be an integer')
            return None
        if result['download'] < lower or result['upload'] < lower:
            error_parts.append(f'{name}{range_text}')
            return None
        if upper is not None and (result['download'] > upper or result['upload'] > upper):
            error_parts.append(f'{name}{range_text}')
            return None
        return result

    @staticmethod
    def __check_save_directory(path: str, allow_create: bool = True) -> dict:
        """Validate the save directory without prompting.

        Remove wildcard placeholders before checking the directory; if it does not exist, allow_create determines whether to create it immediately.

        Args:
            path: New save directory; wildcard placeholders are allowed.
            allow_create: Whether to create a missing directory immediately. If False, do not create
                it and set need_confirm in the result so the web panel can ask the user to confirm,
                avoiding silent creation of a mistyped directory.

        Returns:
            dict: status indicates whether validation passed; e_code contains the failure reason.
                need_confirm is True if the directory does not exist and has not been created.
        """
        if not path:
            return {'status': False, 'e_code': 'The save directory cannot be empty.'}
        clean_path: str = path
        for placeholder in SaveDirectoryPrefix():
            if placeholder in clean_path:
                clean_path = clean_path.replace(placeholder, '')
        clean_path = os.path.normpath(clean_path)
        drive, tail = os.path.splitdrive(clean_path)
        invalid: list = [c for c in '<>:"|?*' if c in tail]
        if invalid:
            return {'status': False, 'e_code': f'Path contains invalid characters: {", ".join(sorted(set(invalid)))}'}
        if os.path.isdir(clean_path):
            return {'status': True}
        if not allow_create:
            return {'status': False, 'need_confirm': True}  # The directory is missing; let the web panel confirm before creating it.
        try:
            os.makedirs(clean_path, exist_ok=True)
        except Exception as e:
            return {'status': False, 'e_code': f'Invalid directory or unable to create it, {_t(KeyWord.REASON)}:"{e}"'}
        if not os.path.isdir(clean_path):
            return {'status': False, 'e_code': 'The save directory is not a valid directory.'}
        return {'status': True}

    def __adjust_client_semaphores(self, download: int, upload: int) -> None:
        """Adjust client transfer semaphore capacities to the new concurrency settings.

        Adjust capacity rather than creating new semaphores: a replacement would discard the slots
        held by active transfers, causing the old active count to be added to the new capacity and
        potentially exceed the limit. With an adjusted semaphore, active transfers remain under the
        same gate, and new transfers wait in the queue when concurrency is reduced.

        Args:
            download: Maximum download concurrency.
            upload: Maximum upload concurrency.
        """
        client = getattr(self.app, 'client', None)
        if client is None:
            return
        try:
            loop = getattr(client, 'loop', None)

            def adjust() -> None:
                client.get_file_semaphore.set_limit(download)
                client.save_file_semaphore.set_limit(upload)

            if loop is not None and hasattr(loop, 'call_soon_threadsafe'):
                loop.call_soon_threadsafe(adjust)
            else:
                adjust()
        except Exception as e:
            log.warning(f'Failed to update concurrency semaphores at runtime, {_t(KeyWord.REASON)}: "{e}"')

    def __wake_upload_waiters(self) -> None:
        """Wake tasks waiting for upload slots so they can recheck the new concurrency limit.

        Upload tasks block on uploader.event.wait() while waiting for a slot. This event is set only
        when an upload finishes, successfully or not. Changing max_upload_task alone will not wake
        them, so queued tasks remain asleep until another upload finishes or a new command arrives,
        making it appear that the concurrency changed but the current upload count did not.
        """
        uploader = getattr(self.downloader, 'uploader', None)
        if uploader is None:
            return
        loop = getattr(self.downloader, 'loop', None)
        if loop is None or not loop.is_running():
            return  # Without a running event loop, no tasks can be waiting; accessing asyncio objects across threads is unsafe.
        try:
            loop.call_soon_threadsafe(lambda: uploader.notify_waiters())
        except Exception as e:
            log.warning(f'Failed to wake queued upload tasks, {_t(KeyWord.REASON)}: "{e}"')

    def set_config(self, directory=None, max_tasks=None, max_retries=None, confirm_directory: bool = False) -> dict:
        """Apply multiple configuration changes at once, as requested by the web panel.

        Args:
            directory: New save directory; None means no change this time.
            max_tasks: Concurrency values in the form {'download': int, 'upload': int}; None means no change this time.
            max_retries: Retry counts in the form {'download': int, 'upload': int}; None means no change this time.
            confirm_directory: Whether creation of a missing directory has been confirmed (if False,
                return need_confirm first so the frontend can ask for confirmation).

        Returns:
            dict: status indicates success; e_code contains the failure reason (multiple errors are
                separated by semicolons). If directory creation needs confirmation, also return
                need_confirm as True.
        """
        if self.app is None:
            return {'status': False, 'e_code': 'Configuration is not loaded, so it cannot be changed'}  # The frontend adds the final period.
        error_parts: list = []
        need_confirm: bool = False  # The directory is missing; request frontend confirmation only after other errors are ruled out.
        tasks = self.__check_number_pair(max_tasks, 1, 10, 'Concurrent task count', 'must be an integer from 1 to 10', error_parts)
        retries = self.__check_number_pair(max_retries, 1, None, 'Retry count', 'must be greater than 0', error_parts)
        if directory is not None:
            checked: dict = self.__check_save_directory(directory, allow_create=confirm_directory)
            if checked.get('need_confirm'):
                need_confirm = True  # A missing directory is not an error; do not return it with other errors yet.
            elif not checked.get('status'):
                error_parts.append(checked.get('e_code') or 'The save directory is invalid.')
        if error_parts:
            # If any item is invalid, let the user fix it first; do not offer to create the directory or apply any changes.
            return {'status': False, 'e_code': '; '.join(error_parts)}
        if need_confirm:
            # All other items are valid and only the directory is missing; do not save or create it yet.
            # Return to the frontend for confirmation before applying the change.
            return {'status': False, 'need_confirm': True, 'e_code': f'The directory "{directory}" does not exist. Create it?'}
        save_config: dict = copy.deepcopy(self.app.config)  # Edit a copy first so a failed save does not affect the original configuration.
        if directory is not None:
            save_config['save_directory'] = directory
        if tasks is not None:
            save_config['max_tasks'] = tasks
        if retries is not None:
            save_config['max_retries'] = retries
        if not self.app.save_config(save_config):  # Combine all changes and write the configuration file only once for this request.
            return {'status': False, 'e_code': 'Failed to save the configuration file. Please try again later.'}  # The frontend adds the final period.
        self.app.config = save_config
        if directory is not None:
            self.app.save_directory = directory
        if tasks is not None:
            self.app.max_download_task = tasks['download']
            self.app.max_upload_task = tasks['upload']
            self.__adjust_client_semaphores(tasks['download'], tasks['upload'])
            self.__wake_upload_waiters()  # Wake queued tasks so they can recheck capacity and start after upload concurrency increases.
        if retries is not None:
            self.app.max_download_retries = retries['download']
            self.app.max_upload_retries = retries['upload']
        log.info(
            f'Configuration updated at runtime; '
            f'save directory: "{self.app.save_directory}", '
            f'download concurrency: "{self.app.max_download_task}", upload concurrency: "{self.app.max_upload_task}", '
            f'download retries: "{self.app.max_download_retries}", upload retries: "{self.app.max_upload_retries}".')
        return {'status': True}

    def get_upload_tasks(self, tasks: Union[list, None] = None) -> list:
        """Get upload-task summaries and fill in progress using progress-bar task IDs."""
        result: list = []
        live: dict = {}
        for item in tasks if tasks is not None else self.get_tasks():
            live[item.get('id')] = item
        try:
            for task in list(UploadTask.TASKS):
                status = getattr(task.status, 'value', task.status)
                done: bool = status in (UploadStatus.SUCCESS, UploadStatus.SENT)
                progress: dict = live.get(getattr(task, 'task_id', None)) or {}
                size: str = MetaData.suitable_units_display(task.file_size)
                info: str = progress.get('info', '')
                if not info and done:
                    info = f'{size}/{size}'  # The progress-bar task has been removed on completion; use the file's size as a fallback.
                result.append({
                    'file': task.file_name,
                    'path': task.file_path,
                    'chat': Web.format_channel(str(task.chat_id)) if task.chat_id else Web.UNGROUPED,
                    'channel': str(task.chat_id) if task.chat_id else Web.UNGROUPED,
                    'size': size,
                    'size_byte': int(task.file_size),
                    'status': _t(str(status)),
                    'state': str(status),  # Raw status, used by the web panel to distinguish uploading, completed, and failed.
                    'task_id': getattr(task, 'task_id', None),
                    'completed': progress.get('completed', task.file_size if done else 0),
                    'percent': progress.get('percent', 100.0 if done else 0.0),
                    'info': info,
                    'speed': progress.get('speed', ''),
                    'speed_value': progress.get('speed_value', 0),
                    'remaining': progress.get('remaining', ''),
                    'error': task.error_msg if task.error_msg else ''
                })
        except Exception as e:
            log.debug(f'Error getting upload tasks, {_t(KeyWord.REASON)}: "{e}"')
        return result

    @staticmethod
    def get_summary(links: list, tasks: list) -> dict:
        """Summarize overall progress across all tasks.

        The total is the combined size of all non-failed members (queued, completed, and skipped),
        rather than only currently downloading tasks, so the total does not keep increasing as
        tasks start. Permanently failed members (retries exhausted) are excluded to prevent them
        from permanently lowering progress.

        Args:
            links: Link progress returned by get_link_progress.
            tasks: Tasks currently shown in the progress bar.

        Returns:
            dict: Overall progress.
        """
        live: dict = {task.get('id'): task for task in tasks}
        completed: int = 0
        total: int = 0
        speed: float = 0.0
        for link in links:
            for member in link.get('queue') or []:
                state: str = str(member.get('state') or '')
                note: str = str(member.get('note') or '')
                if state == DownloadStatus.FAILURE:
                    continue  # Exclude permanently failed members from totals and speed so they do not lower progress or prevent it from reaching zero.
                if state == DownloadStatus.SKIP and note:
                    continue  # Exclude unsupported or ignored (cancelled) items because they will not be downloaded; skipped files that already exist have no note and remain in the total.
                size: int = int(member.get('size_byte') or 0)
                total += size
                if state in (DownloadStatus.SUCCESS, DownloadStatus.SKIP):
                    completed += size
                    continue
                if state == DownloadStatus.DOWNLOADING:
                    completed += int(live.get(member.get('task_id'), {}).get('completed') or 0)
        for task in tasks:
            speed += task.get('speed_value', 0)
        remaining: Union[float, None] = None
        if speed and total > completed:
            remaining: Union[float, None] = (total - completed) / speed
        return {
            'completed': completed,
            'total': total,
            'percent': round(completed / total * 100, 1) if total else 0.0,
            'info': f'{MetaData.suitable_units_display(completed)}/{MetaData.suitable_units_display(total)}',
            'speed': f'{MetaData.suitable_units_display(speed)}/s' if speed else '',
            'remaining': Web.format_seconds(remaining)
        }

    @staticmethod
    def format_channel(channel: str, display: str = '') -> str:
        """Format a channel's display name, showing "title (display value)" when a title is available.

        channel is the title-cache key (the download flow stores it in lowercase); display is the
        value in parentheses and defaults to channel. Pass it to preserve the original casing from
        the link, matching web-panel history records.
        """
        if not channel or channel == Web.UNGROUPED:
            return Web.UNGROUPED
        title: str = ChatInfo.get(channel)
        _display: str = display or channel
        return f'{title}({_display})' if title else _display

    def get_tasks(self) -> list:
        """Read tasks currently in progress in the progress bar."""
        tasks: list = []
        for task in self.progress.tasks:
            item: dict = {
                'id': task.id,
                'type': str(task.description),
                'channel': str(task.fields.get('channel', '')) or Web.UNGROUPED,
                'channel_name': Web.format_channel(str(task.fields.get('channel', ''))),
                'filename': str(task.fields.get('fullname') or task.fields.get('filename', '')),
                'info': str(task.fields.get('info', '')),
                'completed': int(task.completed),
                'total': int(task.total) if task.total else 0,
                'percent': round(task.percentage, 1),
                'speed': f'{MetaData.suitable_units_display(task.speed)}/s' if task.speed else '',
                'speed_value': task.speed if task.speed else 0,
                'remaining': self.format_seconds(task.time_remaining)
            }
            tasks.append(item)
        return tasks

    def snapshot(self, section: str = '') -> dict:
        """Generate progress data for display in the web panel.

        section is the frontend's current section: only the Downloads section needs links (the
        member arrays), and only the Notices section needs notices. Send these large payloads only
        to their respective sections instead of transferring them every second while another
        section is open. Small, persistent header data (counts, progress bars, uploads, listeners,
        and pause state) is always sent. When section is omitted, return everything for compatibility
        with older pages.
        """
        need_links: bool = section in ('', 'download')  # Member arrays are the largest part of the snapshot and are only needed on the Downloads page.
        need_notices: bool = section in ('', 'notice')  # Notices are also a large payload and are only needed on the Notices page.
        try:
            all_tasks: list = self.get_tasks()
            uploads: list = self.get_upload_tasks(tasks=all_tasks)
            upload_ids: set = {item.get('task_id') for item in uploads if item.get('task_id') is not None}
            tasks: list = [item for item in all_tasks if item.get('id') not in upload_ids]  # Exclude upload progress-bar tasks from download statistics.
            result: dict = {
                'count': self.get_count(),
                'is_paused': bool(self.app.is_paused) if self.app else False,  # Global pause state, displayed and toggled by the frontend.
                'outer_links': self.get_outer_links(),  # External links used by the header menu.
                'save_directory': self.app.save_directory if self.app else '',
                'max_tasks': {
                    'download': self.app.max_download_task if self.app else 3,
                    'upload': self.app.max_upload_task if self.app else 3
                },
                'max_retries': {
                    'download': self.app.max_download_retries if self.app else 5,
                    'upload': self.app.max_upload_retries if self.app else 3
                },
                'tasks': tasks,
                'uploads': uploads,
                'listeners': self.get_listeners(),
                'connection_status': ConnectionStatus.get_status()
            }
            if need_links:
                links: list = self.get_link_progress()
                result['summary'] = self.get_summary(links=links, tasks=tasks)
                result['queue'] = sum(link.get('remaining', 0) for link in links)  # Total number of messages remaining to download across all links.
                result['links'] = links
            if need_notices:
                result['notices'] = self.get_notices()
            return result
        except Exception as e:
            log.debug(f'Failed to generate progress data, {_t(KeyWord.REASON)}:"{e}"')
            result: dict = {
                'count': {'success': 0, 'failure': 0, 'skip': 0},
                'is_paused': bool(self.app.is_paused) if self.app else False,  # Global pause state, displayed and toggled by the frontend.
                'outer_links': self.get_outer_links(),
                'save_directory': self.app.save_directory if self.app else '',
                'max_tasks': {
                    'download': self.app.max_download_task if self.app else 3,
                    'upload': self.app.max_upload_task if self.app else 3
                },
                'max_retries': {
                    'download': self.app.max_download_retries if self.app else 5,
                    'upload': self.app.max_upload_retries if self.app else 3
                },
                'tasks': [],
                'uploads': [],
                'listeners': {'download': [], 'forward': []},
                'connection_status': ConnectionStatus.get_status()
            }
            if need_links:
                result['summary'] = self.get_summary(links=[], tasks=[])
                result['queue'] = 0
                result['links'] = []
            if need_notices:
                result['notices'] = self.get_notices()
            return result
