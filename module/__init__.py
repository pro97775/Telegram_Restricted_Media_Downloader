# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2023-11-18 12:28:18
# File:__init__.py
import os
import sys
import atexit
import logging
import platform

from logging.handlers import RotatingFileHandler

import yaml

from rich.console import Console
from rich.logging import RichHandler


def read_input_history(history_path: str, max_record_len: int, **kwargs) -> None:
    if kwargs.get('platform') == 'Windows':
        # 尝试读取历史记录文件。
        import readline
        readline.backend = 'readline'
        try:
            readline.read_history_file(history_path)
        except FileNotFoundError:
            pass
        # 设置历史记录的最大长度。
        readline.set_history_length(max_record_len)
        # 注册退出时保存历史记录。
        atexit.register(readline.write_history_file, history_path)


def via_log_level(log_level: str, param_name: str, default_level: int = logging.INFO) -> bool:
    if log_level not in ['CRITICAL', 'FATAL', 'ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'NOTSET']:
        with open(file=GLOBAL_CONFIG_PATH, mode='w', encoding='UTF-8') as file:
            global_config[param_name] = logging.getLevelName(default_level)
            yaml.dump(global_config, file)
        return False
    return True


class CustomDumper(yaml.Dumper):

    def represent_none(self, data):
        """自定义将yaml文件中None表示为~。"""
        return self.represent_scalar('tag:yaml.org,2002:null', '~')


class CallerFilter(logging.Filter):
    PROJECT_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    """Add the calling module and function name to log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rel_path: str = os.path.relpath(record.pathname, CallerFilter.PROJECT_PATH)
            module_path: str = os.path.splitext(rel_path)[0].replace(os.sep, '.')
        except Exception:  # noqa.
            module_path: str = record.module
        # 先写入默认值,保证后续任何分支返回时格式化字段都完整。
        # 若缺失字段,格式化日志时会抛出"Formatting field not found in record"(如在函数外直接调用日志)。
        record.name_part = '' if record.name == 'rich' else f'{record.name}:'
        record.caller_name = ''  # 没有上层调用者时留空,连分隔符一起省略。
        record.file_func = f'{module_path}.{record.funcName}'
        frame = sys._getframe(1)
        # 回溯到实际调用日志的帧(record的pathname与lineno即为其位置)。
        while frame is not None:
            if frame.f_code.co_filename == record.pathname and frame.f_lineno == record.lineno:
                break
            frame = frame.f_back
        caller_frame = frame.f_back if frame is not None else None
        if caller_frame is None:  # 在模块顶层等没有上层调用者的位置记录日志。
            return True
        func_name: str = caller_frame.f_code.co_name
        # 项目内的调用者显示完整模块名,第三方与标准库仅显示函数名,避免名称过长导致换行。
        if caller_frame.f_code.co_filename.startswith(CallerFilter.PROJECT_PATH):
            record.caller_name = f'{caller_frame.f_globals.get("__name__", "")}.{func_name}:'
        else:
            record.caller_name = f'{func_name}:'
        return True


LOG_TIME_FORMAT = '[%Y-%m-%d %H:%M:%S]'
console = Console(log_path=False, log_time_format=LOG_TIME_FORMAT)
DOWNLOAD_TIMEOUT = 120
FORWARD_LIMIT = 33  # 每分钟允许的最大转发次数。
AUTHOR = 'Gentlesprite'
__version__ = '2.1.5'
__license__ = 'GPL-3.0-or-later'
__update_date__ = '2026-10-31 14:48:18'
__copyright__ = f'Copyright (C) 2024-{__update_date__[:4]} {AUTHOR} <https://github.com/{AUTHOR}>'
SOFTWARE_FULL_NAME = 'Telegram Restricted Media Downloader'
SOFTWARE_SHORT_NAME = 'TRMD'
APPDATA_PATH = os.path.join(
    os.environ.get('APPDATA') or os.environ.get('XDG_CONFIG_HOME', os.path.expanduser('~/.config')),
    SOFTWARE_SHORT_NAME)
GLOBAL_CONFIG_NAME = '.CONFIG.yaml'
GLOBAL_CONFIG_PATH = os.path.join(APPDATA_PATH, GLOBAL_CONFIG_NAME)
PLATFORM = platform.system()
os.makedirs(APPDATA_PATH, exist_ok=True)  # v1.2.6修复初次运行打开报错问题。
INPUT_HISTORY_PATH = os.path.join(APPDATA_PATH, f'.{SOFTWARE_SHORT_NAME}_HISTORY')
MAX_RECORD_LENGTH = 1000
read_input_history(history_path=INPUT_HISTORY_PATH, max_record_len=MAX_RECORD_LENGTH, platform=PLATFORM)
LOG_PATH = os.path.join(APPDATA_PATH, f'{SOFTWARE_SHORT_NAME}_LOG.log')
MAX_LOG_SIZE = 200 * 1024 * 1024  # 200MB
BACKUP_COUNT = 0  # 不保留日志文件。
LOG_FORMAT = '%(name_part)s%(caller_name)s%(file_func)s:%(lineno)d - %(message)s'
FILE_LOG_LEVEL: int = logging.INFO
CONSOLE_LOG_LEVEL: int = logging.WARNING
REFERRAL_RECORD_PATH: str = os.path.join(APPDATA_PATH, f'.{SOFTWARE_SHORT_NAME}_REFERRAL')
TRMD_WEB_SESSION: str = os.path.join(APPDATA_PATH, f'.{SOFTWARE_SHORT_NAME}_WEB_SESSION')
# 配置日志文件处理器(文件记录)
file_handler = RotatingFileHandler(
    filename=LOG_PATH,
    maxBytes=MAX_LOG_SIZE,
    backupCount=BACKUP_COUNT,
    encoding='UTF-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s' + ' ' + LOG_FORMAT, datefmt=LOG_TIME_FORMAT))

if os.path.exists(GLOBAL_CONFIG_PATH):
    try:
        with open(file=GLOBAL_CONFIG_PATH, mode='r', encoding='UTF-8') as f:
            global_config = yaml.safe_load(f)
        file_log_level: str = global_config.get('file_log_level')
        console_log_level: str = global_config.get('console_log_level')
        if via_log_level(log_level=file_log_level, param_name='file_log_level', default_level=logging.INFO):
            FILE_LOG_LEVEL: int = logging.getLevelName(file_log_level)
        if via_log_level(log_level=console_log_level, param_name='console_log_level', default_level=logging.WARNING):
            CONSOLE_LOG_LEVEL: int = logging.getLevelName(console_log_level)
    except Exception:  # noqa.
        pass

file_handler.setLevel(logging.getLevelName(FILE_LOG_LEVEL))
file_handler.addFilter(CallerFilter())
# 配置日志终端记录器(控制台输出)
console_handler = RichHandler(
    level=CONSOLE_LOG_LEVEL,  # 控制台只显示WARNING及以上级别。
    console=console,
    rich_tracebacks=True,
    show_path=False,
    omit_repeated_times=True,
    log_time_format=LOG_TIME_FORMAT
)
console_handler.addFilter(CallerFilter())
# 配置日志记录器(根记录器设置为最低级别 DEBUG)
logging.basicConfig(
    level=logging.DEBUG,  # 根记录器设置为DEBUG,允许所有日志通过。
    format=LOG_FORMAT,
    datefmt=LOG_TIME_FORMAT,
    handlers=[
        console_handler,  # 控制台:WARNING+
        file_handler  # 文件:INFO+
    ]
)


class PyrogramQuietFilter(logging.Filter):
    """按记录名与调用者命名空间屏蔽pyrogram的INFO/DEBUG日志。"""
    PYROGRAM_LOGGERS = (
        'pyrogram.client',
        'pyrogram.crypto',
        'pyrogram.session',
        'pyrogram.connection',
        'pyrogram.dispatcher',
        'pyrogram.methods.advanced.invoke',
        'module.client.invoke'
    )

    def filter(self, record: logging.LogRecord) -> bool:
        caller_name: str = getattr(record, 'caller_name', '')
        file_func: str = getattr(record, 'file_func', '')
        for name in PyrogramQuietFilter.PYROGRAM_LOGGERS:
            if (record.name == name
                    or record.name.startswith(name + '.')
                    or caller_name == name + ':'
                    or caller_name.startswith(name + '.')
                    or file_func == name
                    or file_func.startswith(name + '.')):
                if record.levelno < logging.WARNING:
                    return False
                break
        return True


if CONSOLE_LOG_LEVEL > logging.DEBUG:
    console_handler.addFilter(PyrogramQuietFilter())
if FILE_LOG_LEVEL > logging.DEBUG:
    file_handler.addFilter(PyrogramQuietFilter())
log = logging.getLogger('rich')


def get_commit_hash():
    env_commit = os.environ.get('TRMD_COMMIT_HASH')
    if env_commit:
        log.debug(f'Got commit hash from the TRMD_COMMIT_HASH environment variable: {env_commit}.')
        return env_commit
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isdir(os.path.join(repo_root, '.git')):
        try:
            import subprocess
            completed = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=repo_root,
                capture_output=True,
                text=True
            )
            if completed.returncode == 0 and completed.stdout.strip():
                commit_hash: str = completed.stdout.strip()
                log.debug(f'Got commit hash from Git: {commit_hash}.')
                return commit_hash
        except Exception as e:
            log.debug(f'Could not get commit hash. Reason: "{e}"')
    return None


def get_build_time():
    env_build_time = os.environ.get('TRMD_BUILD_TIME')
    if env_build_time:
        log.debug(f'Got build time from the TRMD_BUILD_TIME environment variable: {env_build_time}.')
        return env_build_time
    return None


COMMIT = get_commit_hash()
BUILD_TIME = get_build_time()
BUILD_META: str = '.'.join(part for part in (COMMIT, BUILD_TIME) if part)
VERSION_SEMVER = f'{__version__}+{BUILD_META}' if BUILD_META else __version__
VERSION_WITH_COMMIT = f'{__version__}+{COMMIT}' if COMMIT else __version__
CustomDumper.add_representer(type(None), CustomDumper.represent_none)  # noqa.
README = r'''
```yaml
api_hash: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx # Your Telegram API hash.
api_id: 'xxxxxxxx' # Your Telegram API ID.
# bot_token (optional): bot features are unavailable if omitted. Get one free from https://t.me/BotFather.
bot_token: 123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
download_type: # Media types to download. Supported values: video, photo, document, audio, voice, animation, video_note, live_photo.
- video # Video.
- photo # Photo.
- document # Document.
- audio # Audio.
- voice # Voice message.
- animation # GIF.
- video_note # Video note.
- live_photo # Live photo (treated as a photo if unspecified and photo is enabled).
is_shutdown: true # Shut down the computer after downloads finish. Supported values: true, false.
links: D:\path\where\your\link\files\save\content.txt # Path to the text file containing media links.
# Create a .txt file with one link per line and enter its path without quotation marks. Create it before starting TRMD.
# Example: D:\path\where\your\link\txt\save\content.txt (one link per line).
max_retries:
  download: 5 # Maximum download retry attempts.
  upload: 3 # Maximum upload retry attempts.
max_tasks:
  download: 5 # Maximum concurrent download tasks.
  upload: 3 # Maximum concurrent upload tasks.
proxy: # For no proxy, set all values to null. Keep a space after each colon.
  enable_proxy: true # Enable proxy usage. Supported values: true, false.
  hostname: 127.0.0.1 # Proxy IP address or hostname.
  scheme: socks5 # Proxy type. Supported values: http, socks4, socks5.
  port: 10808 # Proxy port. Valid range: 0-65535.
  username: null # Proxy username, or null if not required.
  password: null # Proxy password, or null if not required.
save_directory: F:\directory\media\where\you\save # Directory for downloaded media (wildcards supported).
session_directory: F:\directory\session\where\you\save # Directory for session files (wildcards supported).
temp_directory: F:\directory\temp\where\you\save # Directory for temporary files (wildcards supported).
```
'''  # noqa.
