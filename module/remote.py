# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026-09-07 00:00:00
# File:remote.py
import os
import json
import time
import asyncio

from functools import partial
from urllib.request import (
    Request,
    urlopen
)

from module import (
    log,
    AUTHOR,
    __version__,
    APPDATA_PATH,
    SOFTWARE_SHORT_NAME
)
from module.parser import PARSE_ARGS


class RemoteConfig(object):
    """Fetch, validate, cache, and parse remote configuration."""

    BRANCH: str = 'main'
    URLS: tuple = (
        f'https://cdn.jsdelivr.net/gh/{AUTHOR}/{SOFTWARE_SHORT_NAME}_CONFIG@{BRANCH}/config.json',
        f'https://fastly.jsdelivr.net/gh/{AUTHOR}/{SOFTWARE_SHORT_NAME}_CONFIG@{BRANCH}/config.json',
    )
    HEADERS: dict = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/124.0.0.0 Safari/537.36'
    }
    TIMEOUT: int = 8  # Request timeout for each remote URL, in seconds.
    TTL: int = 24 * 3600  # Local cache lifetime and retry interval after a failed remote fetch, in seconds.
    PATH: str = os.path.join(APPDATA_PATH, '.REMOTE_CONFIG')
    DEFAULT_VERSION: str = __version__
    DEFAULT_REFERRAL: str = 'https://t.me/jisou2?start=a_1604151130'
    DEFAULT_VIDEO_TUTORIAL: str = 'https://www.youtube.com/watch?v=ucwKJu-MrBw'
    DEFAULT_SUBSCRIBE_CHANNEL: str = 'https://t.me/RestrictedMediaDownloader'
    DEFAULT_PROXY_SELLER: str = 'https://proxy-seller.com/zh/?partner=CCFF5F78CF9C46A7'
    DEFAULT_GITHUB: str = 'https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader'
    CONFIG: dict = {
        'version': (DEFAULT_VERSION, str),
        'referral': (DEFAULT_REFERRAL, str),
        'video_tutorial': (DEFAULT_VIDEO_TUTORIAL, str),
        'subscribe_channel': (DEFAULT_SUBSCRIBE_CHANNEL, str),
        'proxy_seller': (DEFAULT_PROXY_SELLER, str),
        'github': (DEFAULT_GITHUB, str)
    }

    def default_config(self) -> dict:
        """Build the built-in default configuration from the field table, used for missing or mismatched fields."""
        return {name: field[0] for name, field in self.CONFIG.items()}

    def verify(self, remote: dict) -> dict:
        """Validate configuration against the field table and fill missing fields, ignoring unknown fields for compatibility across versions."""
        config: dict = {}
        for name, field in self.CONFIG.items():
            default, expected_type = field
            value = remote.get(name, default)
            # Fall back to the default for missing fields or type mismatches so one malformed field cannot invalidate the entire configuration.
            if not isinstance(value, expected_type):
                log.info(f'Unexpected field value: "{name}={value}", using default: "{default}"')
                value = default
            config[name] = value
        return config

    async def read(self) -> dict:
        """Load the configuration from a valid cache or fetch it remotely, falling back to the cache or built-in defaults on failure."""
        default: dict = self.default_config()
        if getattr(PARSE_ARGS, 'test', False):
            log.info('test mode, using default config')
            return default
        # Fall back to the local cache when remote configuration is unavailable so the last usable settings remain available offline.
        cached: dict = self.cached_config()
        if cached:
            try:
                # If the cache file disappears after it is read, treat it as expired and fetch the remote configuration.
                remaining: float = self.TTL - (time.time() - os.path.getmtime(self.PATH))
            except OSError:
                remaining: float = 0
            if remaining > 0:
                log.info(f'Using cached remote config from "{self.PATH}", '
                         f'remaining valid time: {remaining / 3600:.1f} hours')
                return cached
        config: dict = await self.fetch()
        self.save(config or cached or default)  # Always write once to refresh the cache timestamp and avoid retrying too often while the remote source is unavailable.
        return config or cached or default

    def save(self, config: dict) -> None:
        """Write the configuration to the cache file; its modification time marks when the cache takes effect."""
        try:
            with open(file=self.PATH, mode='w', encoding='UTF-8') as f:
                json.dump(config, f)
            log.info(f'Remote config cached successfully: {config}')
        except OSError as e:
            log.info(f'Failed to write to the remote config cache due to {e}')

    async def fetch(self) -> dict:
        """Try each remote URL in turn and return an empty dictionary if all requests fail."""
        loop = asyncio.get_running_loop()
        for url in self.URLS:
            try:
                log.info(f'Getting remote config from "{url}"')
                request = Request(url=url, headers=self.HEADERS)
                response = await asyncio.wait_for(
                    loop.run_in_executor(None, partial(urlopen, request, timeout=self.TIMEOUT)),
                    timeout=self.TIMEOUT
                )
                with response:
                    remote: dict = json.loads(response.read().decode('UTF-8'))
                config: dict = self.verify(remote)
                log.info(f'Successfully obtained remote config from "{url}": {config}')
                return config
            except Exception as e:
                # Continue to the next URL after a failure; use local configuration only if all URLs fail.
                log.info(f'Failed to obtain remote config from "{url}" due to {e}')
        log.info(f'All remote addresses are unavailable, using local default config: {self.default_config()}')
        return {}

    def cached_config(self) -> dict:
        """Read the local configuration cache, returning an empty dictionary if it is missing or invalid without making a remote request."""
        try:
            if os.path.exists(self.PATH):
                with open(file=self.PATH, mode='r', encoding='UTF-8') as f:
                    return self.verify(json.load(f))
        except Exception as e:
            log.info(f'Failed to read the remote config cache due to {e}')
        return {}


rc = RemoteConfig()
