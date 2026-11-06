# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2025-2-25 01:32:00
# File:config.py
import os
import logging
import datetime
import threading

from typing import Union

from module import (
    log,
    console,
    yaml,
    CustomDumper,
    PLATFORM,
    FILE_LOG_LEVEL,
    CONSOLE_LOG_LEVEL,
    GLOBAL_CONFIG_NAME,
    GLOBAL_CONFIG_PATH
)
from module.language import _t
from module.parser import PARSE_ARGS
from module.path_tool import (
    gen_backup_config,
    safe_scan_directory_file
)
from module.enums import (
    KeyWord,
    ProcessConfig,
    GetStdioParams
)
from module.util import (
    ctrl_c,
    get_work_directory
)


class BaseConfig:
    FILE_NAME: str = 'base_config.yaml'
    PATH: str = os.path.join(get_work_directory(), FILE_NAME)
    TEMPLATE: dict = {}

    def __init__(self):
        self.config: dict = self.TEMPLATE.copy()
        self.config_path: str = self.PATH

    @staticmethod
    def add_missing_keys(target, template, log_message) -> None:
        """Add missing configuration keys."""
        for key, value in template.items():
            if key not in target:
                target[key] = value
                console.log(log_message.format(key))

    @staticmethod
    def remove_extra_keys(target, template, log_message) -> None:
        """Remove extra configuration keys."""
        keys_to_remove: list = [key for key in target.keys() if key not in template]
        for key in keys_to_remove:
            target.pop(key)
            console.log(log_message.format(key))

    def process_nesting(self, param_name: Union[str, dict], config):
        param_template = self.TEMPLATE.get(param_name)
        param_length = len(param_template)
        if param_name in config:
            param_template = self.TEMPLATE.get(param_name)
            param_config = config.get(param_name)
            if not isinstance(param_config, dict) or (
                    isinstance(param_config, dict) and len(param_config) != param_length):
                param_config: dict = {}
                config[param_name] = param_config
            self.add_missing_keys(
                target=param_config,
                template=param_template,
                log_message='"{}"'
                            f' is missing from the {param_name} configuration; added.'
            )
            self.remove_extra_keys(
                target=param_config,
                template=param_template,
                log_message='"{}"'
                            f' is not present in the {param_name} configuration; removed.'
            )

    def __check_params(self, config: dict) -> None:
        """Check that the configuration contains all required parameters."""
        # Initialize config as an empty dictionary if it is None.
        if config is None:
            config = {}

        # Process top-level parameters.
        self.add_missing_keys(target=config, template=self.TEMPLATE, log_message='"{}" is missing from the global configuration; added.')
        # Remove fields that are not in the top-level template.
        self.remove_extra_keys(config, self.TEMPLATE, '"{}" is not present in the template; removed.')

        if config != self.config:
            self.config = config
            self.save_config(self.config)

    def load_config(self) -> None:
        """Load the global configuration file."""
        try:
            if not os.path.exists(self.PATH):
                with open(file=self.PATH, mode='w', encoding='UTF-8') as f:
                    yaml.dump(self.TEMPLATE, f, Dumper=CustomDumper)
                return
            with open(file=self.PATH, mode='r', encoding='UTF-8') as f:
                config = yaml.safe_load(f)
                if config:
                    self.config = config
                else:
                    raise ValueError('The file is empty or has invalid format.')
        except Exception as e:
            log.error(f'Invalid or corrupted global configuration detected. A new template file has been generated. {_t(KeyWord.REASON)}:"{e}"')
            self.config: dict = self.TEMPLATE.copy()
            self.save_config(self.config)

    def save_config(self, config: dict) -> None:
        """Save the configuration file."""
        try:
            with open(file=self.config_path, mode='w', encoding='UTF-8') as f:
                yaml.dump(config, f)
            log.info('Global configuration file saved.')
        except Exception as e:
            log.error(f'Failed to save the global configuration file. {_t(KeyWord.REASON)}:"{e}"')
        finally:
            self.config = config

    def get_config(self, param, error_param=None) -> Union[str, None]:
        """Get the current configuration."""
        self.load_config()
        return self.config.get(param, error_param)


class UserConfig(BaseConfig):
    CONFIG_LOCK: threading.Lock = threading.Lock()  # Serialize writes to the same configuration file across threads and async callbacks.
    DIRECTORY_NAME: str = get_work_directory()  # Absolute application working directory.
    FILE_NAME: str = 'config.yaml'  # Configuration filename.
    PATH: str = os.path.join(DIRECTORY_NAME, FILE_NAME)
    TEMPLATE: dict = {
        'api_id': None,
        'api_hash': None,
        'bot_token': None,
        'session_directory': None,
        'proxy': {
            'enable_proxy': None,
            'scheme': None,
            'hostname': None,
            'port': None,
            'username': None,
            'password': None
        },
        'links': None,
        'save_directory': None,  # v1.3.0: rename the configuration key save_path to save_directory.
        'temp_directory': None,
        'max_tasks': {
            'download': None,
            'upload': None
        },
        'is_shutdown': None,
        'download_type': None,
        'max_retries': {
            'download': None,
            'upload': None
        }
    }
    TEMP_DIRECTORY: str = os.path.join(os.getcwd(), 'temp')
    BACKUP_DIRECTORY: str = 'ConfigBackup'
    ABSOLUTE_BACKUP_DIRECTORY: str = os.path.join(DIRECTORY_NAME, BACKUP_DIRECTORY)
    WORK_DIRECTORY: str = os.path.join(os.getcwd(), 'sessions')

    def __init__(self):
        super().__init__()
        self.config_path: str = PARSE_ARGS.config if PARSE_ARGS.config.endswith('.yaml') else UserConfig.PATH
        self.platform: str = PLATFORM
        self.history_timestamp: dict = {}
        self.input_link: list = []
        self.last_record: dict = {}
        self.difference_timestamp: dict = {}
        self.download_type: list = []
        self.record_dtype: set = set()
        self.record_flag: bool = False
        self.modified: bool = False
        self.get_last_history_record()
        self.is_change_account: bool = True
        self.re_config: bool = False
        self.config_guide()
        self.config: dict = self.load_config()  # v1.3.0: fix repeated prompts to reconfigure the file.
        self.api_hash = self.config.get('api_hash')
        self.api_id = self.config.get('api_id')
        self.bot_token = self.config.get('bot_token')
        self.download_type: list = self.config.get('download_type')
        self.is_shutdown: bool = self.config.get('is_shutdown')
        self.links: str = self.config.get('links')
        self.max_download_task: int = self.config.get('max_tasks', {'download': 3}).get('download')
        self.max_download_retries: int = self.config.get('max_retries', {'download': 5}).get('download')
        self.max_upload_task: int = (self.config.get('max_tasks') or {}).get('upload', 3) or 3
        self.max_upload_retries: int = (self.config.get('max_retries') or {}).get('upload', 3) or 3
        self.proxy: dict = self.config.get('proxy', {})
        self.enable_proxy: bool = self.proxy.get('enable_proxy', False)
        self.save_directory: str = self.config.get('save_directory')
        self.work_directory: str = PARSE_ARGS.session or (
                self.config.get('session_directory') or UserConfig.WORK_DIRECTORY)
        self.temp_directory: str = PARSE_ARGS.temp or (self.config.get('temp_directory') or UserConfig.TEMP_DIRECTORY)

    def get_last_history_record(self) -> None:
        """Get the most recently saved configuration history file."""
        # First check whether the history directory exists.
        try:
            res: list = safe_scan_directory_file(UserConfig.ABSOLUTE_BACKUP_DIRECTORY)
        except FileNotFoundError:
            return
        except Exception as e:
            log.error(f'Failed to read the history file. {_t(KeyWord.REASON)}: "{e}"')
            return
        file_start: str = 'history_'
        file_end: str = '_config.yaml'

        now_timestamp: float = datetime.datetime.now().timestamp()  # Get the current timestamp.
        if res:
            for i in res:  # Find the configuration file closest to the current time.
                try:
                    if i.startswith(file_start) and i.endswith(file_end):
                        format_date_str = i.replace(file_start, '').replace(file_end, '').replace('_', ' ')
                        to_datetime_obj = datetime.datetime.strptime(format_date_str, '%Y-%m-%d %H-%M-%S')
                        timestamp = to_datetime_obj.timestamp()
                        self.history_timestamp[timestamp] = i
                except ValueError:
                    pass
                except Exception:  # noqa.
                    pass
            for i in self.history_timestamp.keys():
                self.difference_timestamp[now_timestamp - i] = i
            if self.history_timestamp:  # If a matching history file was found.
                self.last_record: dict = self.__find_history_config()

        else:
            return

    def __find_history_config(self) -> dict:
        """Find a configuration file in the history directory."""
        if not self.history_timestamp:
            return {}
        if not self.difference_timestamp:
            return {}
        try:
            min_key: int = min(self.difference_timestamp.keys())
            min_diff_timestamp: str = self.difference_timestamp.get(min_key)
            min_config_file: str = self.history_timestamp.get(min_diff_timestamp)
            if not min_config_file:
                return {}
            last_config_file: str = os.path.join(UserConfig.ABSOLUTE_BACKUP_DIRECTORY, min_config_file)  # Build the file path.
            with open(file=last_config_file, mode='r', encoding='UTF-8') as f:
                config: dict = yaml.safe_load(f)
            last_record: dict = self.__check_params(config, history=True)  # v1.1.6: fix the flag being set when a history file has missing fields.

            if last_record == UserConfig.TEMPLATE:
                # Remove the current file from the dictionary.
                self.history_timestamp.pop(min_diff_timestamp, None)
                self.difference_timestamp.pop(min_key, None)
                # Recurse to check the next history file.
                return self.__find_history_config()
            else:
                return last_record
        except Exception:  # noqa.
            return {}

    def add_missing_keys(self, target, template, log_message, history=False) -> None:
        """Add missing configuration keys."""
        for key, value in template.items():
            if key not in target:
                target[key] = value
                if not history:
                    console.log(log_message.format(key))
                    self.modified = True
                    self.record_flag = True

    def remove_extra_keys(self, target, template, log_message, history=False) -> None:
        """Remove extra configuration keys."""
        keys_to_remove: list = [key for key in target.keys() if key not in template]
        for key in keys_to_remove:
            target.pop(key)
            if not history:
                console.log(log_message.format(key))
                self.record_flag = True

    def __check_params(self, config: dict, history=False) -> dict:
        """Check that the configuration contains all required parameters."""
        # Initialize config as an empty dictionary if it is None.
        if config is None:
            config = {}

        # Process top-level parameters.
        self.add_missing_keys(
            target=config,
            template=UserConfig.TEMPLATE,
            log_message='"{}" is missing from the configuration; added.',
            history=history
        )

        self.process_nesting(param_name='proxy', config=config)
        self.process_nesting(param_name='max_tasks', config=config)
        self.process_nesting(param_name='max_retries', config=config)

        # Remove fields that are not in the top-level template.
        self.remove_extra_keys(
            target=config,
            template=UserConfig.TEMPLATE,
            log_message='"{}" is not present in the template; removed.',
            history=history
        )

        return config

    def load_config(self) -> dict:
        """Load the current configuration once, validating it, checking for missing parameters, and handling errors."""
        config: dict = UserConfig.TEMPLATE.copy()
        try:
            if not os.path.exists(self.config_path):
                with open(file=self.config_path, mode='w', encoding='UTF-8') as f:
                    yaml.dump(UserConfig.TEMPLATE, f, Dumper=CustomDumper)
                console.log('Configuration file not found. A new template has been created...')
                self.re_config = True  # v1.3.4: fix failing to regenerate a missing configuration file.
            with open(self.config_path, 'r', encoding='UTF-8') as f:
                config: dict = yaml.safe_load(f)  # v1.1.4: add completeness checks for every field.
            compare_config: dict = config.copy() if config else {}
            config: dict = self.__check_params(config) if compare_config else None
            if config != compare_config or config == UserConfig.TEMPLATE:  # v1.3.4: fix errors when every configuration value is empty.
                self.re_config = True
        except UnicodeDecodeError as e:  # v1.1.3: add an error message for configuration paths containing Chinese or special characters; this is a Nuitka packaging limitation.
            # Packaged binaries may not recognize paths containing Chinese characters, so use English names for link-file and media-save paths.
            self.re_config = True
            log.error(
                f'An encoding error occurred while reading the configuration file. A save path may contain a folder with unsupported characters. A new template has been created... {_t(KeyWord.REASON)}:"{e}"')
            self.backup_config(config, error_config=self.re_config)
        except Exception as e:
            self.re_config = True
            console.print('Note: link and save paths must not contain quotation marks.', style='#B1DB74')
            log.error(f'Invalid or corrupted configuration file detected. A new template has been created... {_t(KeyWord.REASON)}:"{e}"')
            self.backup_config(config, error_config=self.re_config)
        finally:
            if config is None:
                self.re_config = True
                log.warning('Empty configuration file detected. A new template has been created...')
                config: dict = UserConfig.TEMPLATE.copy()
        return config

    def backup_config(
            self,
            backup_config: dict,
            error_config: bool = False,
            force: bool = False
    ) -> None:  # v1.2.9: correct the backup_config parameter type.
        """Back up the current configuration file."""
        if backup_config != UserConfig.TEMPLATE or force:  # v1.2.9: fix the incorrect variable comparison.
            backup_path: str = gen_backup_config(
                old_path=self.config_path,
                absolute_backup_dir=UserConfig.ABSOLUTE_BACKUP_DIRECTORY,
                error_config=error_config
            )
            console.log(f'The previous configuration file was backed up to "{backup_path}"', style='#B1DB74')
        else:
            console.log('The configuration file matches the template; no backup is needed.')

    def config_guide(self) -> None:
        """Guide the user through editing and saving the configuration interactively."""
        exit_flag: bool = False
        pre_load_config: dict = self.load_config()
        gsp = GetStdioParams()
        # v1.1.0: reorder api_id and api_hash to match Telegram's application form and avoid input mistakes.
        try:
            if not self.modified and pre_load_config != UserConfig.TEMPLATE:
                re_config: bool = False if PARSE_ARGS.quiet else gsp.get_is_re_config().get('is_re_config')
                if re_config:
                    self.re_config = re_config
                    # Cache the existing session_directory so it is not lost during reconfiguration.
                    origin_session_directory = pre_load_config.get('session_directory')
                    pre_load_config: dict = UserConfig.TEMPLATE.copy()
                    self.backup_config(backup_config=pre_load_config, error_config=False, force=True)
                    self.get_last_history_record()  # Restore the most recently entered values.
                    if not PARSE_ARGS.session:
                        self.is_change_account = gsp.get_is_change_account(valid_format='y|n').get(
                            'is_change_account')
                        if self.is_change_account:
                            pre_load_config['session_directory'] = gsp.get_session_directory().get('session_directory')
                        else:
                            pre_load_config['session_directory'] = origin_session_directory
            _api_id: Union[str, None] = pre_load_config.get('api_id')
            _api_hash: Union[str, None] = pre_load_config.get('api_hash')
            _bot_token: Union[str, None] = pre_load_config.get('bot_token')
            _links: Union[str, None] = pre_load_config.get('links')
            _save_directory: Union[str, None] = pre_load_config.get('save_directory')
            _max_download_task: Union[int, None] = pre_load_config.get('max_tasks', {'download': 3}).get('download')
            _max_download_retries: Union[int, None] = pre_load_config.get('max_retries', {'download': 5}).get(
                'download')
            _download_type: Union[list, None] = pre_load_config.get('download_type')
            _is_shutdown: Union[bool, None] = pre_load_config.get('is_shutdown')
            _proxy_config: dict = pre_load_config.get('proxy', {})
            _enable_proxy: Union[str, bool] = _proxy_config.get('enable_proxy', False)
            _proxy_scheme: Union[str, bool] = _proxy_config.get('scheme', False)
            _proxy_hostname: Union[str, bool] = _proxy_config.get('hostname', False)
            _proxy_port: Union[str, bool] = _proxy_config.get('port', False)
            _proxy_username: Union[str, bool] = _proxy_config.get('username', False)
            _proxy_password: Union[str, bool] = _proxy_config.get('password', False)
            proxy_record: dict = self.last_record.get('proxy', {})  # Previous proxy settings.
            enable_bot: bool = False  # Whether to enable the bot.
            if any([not _api_id, not _api_hash, not _save_directory, not _max_download_task, not _download_type]):
                console.print('Note: press Enter to use the previous value.',
                              style='#B1DB74')
            if self.is_change_account or _api_id is None or _api_hash is None or self.re_config:
                if not _api_id:
                    api_id, record_flag = gsp.get_api_id(
                        last_record=self.last_record.get('api_id')).values()
                    if record_flag:
                        self.record_flag = record_flag
                        pre_load_config['api_id'] = api_id
                if not _api_hash:
                    api_hash, record_flag = gsp.get_api_hash(
                        last_record=self.last_record.get('api_hash'),
                        valid_length=32).values()
                    if record_flag:
                        self.record_flag = record_flag
                        pre_load_config['api_hash'] = api_hash
            if not _bot_token and self.re_config:
                enable_bot: bool = gsp.get_enable_bot(valid_format='y|n').get('enable_bot')
                if enable_bot:
                    bot_token, record_flag = gsp.get_bot_token(
                        last_record=self.last_record.get('bot_token'),
                        valid_format=':').values()
                    if record_flag:
                        self.record_flag = record_flag
                        pre_load_config['bot_token'] = bot_token
            if not _links or not _bot_token and self.re_config:
                links, record_flag = gsp.get_links(
                    last_record=self.last_record.get('links'),
                    valid_format='.txt',
                    enable_bot=True if enable_bot else False).values()
                if record_flag:
                    self.record_flag = record_flag
                    pre_load_config['links'] = links
            if not _save_directory or self.re_config:
                save_directory, record_flag = gsp.get_save_directory(
                    last_record=self.last_record.get('save_directory')).values()
                if record_flag:
                    self.record_flag = record_flag
                    pre_load_config['save_directory'] = save_directory
            if not _max_download_task or self.re_config:
                max_download_task, record_flag = gsp.get_max_download_task(
                    last_record=self.last_record.get('max_tasks', {'download': 3}).get('download')).values()
                if record_flag:
                    self.record_flag = record_flag
                    pre_load_config.get('max_tasks')['download'] = max_download_task
            if not _max_download_retries or self.re_config:
                max_retry_count, record_flag = gsp.get_max_retry_count(
                    last_record=self.last_record.get('max_retries', {'download': 5}).get('download')).values()
                if record_flag:
                    self.record_flag = record_flag
                    pre_load_config.get('max_retries')['download'] = max_retry_count
            if not _download_type or self.re_config:
                download_type, record_flag = gsp.get_download_type(
                    last_record=self.last_record.get('download_type')).values()
                if record_flag:
                    self.record_flag = record_flag
                    pre_load_config['download_type'] = download_type
            if _is_shutdown is None or self.re_config:
                is_shutdown, _is_shutdown_record_flag = gsp.get_is_shutdown(
                    last_record=self.last_record.get('is_shutdown'),
                    valid_format='y|n').values()
                if _is_shutdown_record_flag:
                    self.record_flag = True
                    pre_load_config['is_shutdown'] = is_shutdown
            # Ask whether to enable the proxy.
            if not _enable_proxy and self.re_config:
                valid_format: str = 'y|n'
                is_enable_proxy, is_ep_record_flag = gsp.get_enable_proxy(
                    last_record=proxy_record.get('enable_proxy', False),
                    valid_format=valid_format).values()
                if is_ep_record_flag:
                    self.record_flag = True
                    _proxy_config['enable_proxy'] = is_enable_proxy
            # Configure proxy details if needed.
            # Continue if enable_proxy was selected above or was already true in the configuration.
            if _proxy_config.get('enable_proxy') is True or _enable_proxy is True:
                if ProcessConfig.is_proxy_input(proxy_config=_proxy_config):
                    if not _proxy_scheme:
                        scheme, record_flag = gsp.get_scheme(
                            last_record=proxy_record.get('scheme'),
                            valid_format=['http', 'socks4',
                                          'socks5']
                        ).values()
                        if record_flag:
                            self.record_flag = True
                            _proxy_config['scheme'] = scheme
                    if not _proxy_hostname:
                        hostname, record_flag = gsp.get_hostname(
                            proxy_config=_proxy_config,
                            last_record=proxy_record.get('hostname'),
                            valid_format='x.x.x.x').values()
                        if record_flag:
                            self.record_flag = True
                            _proxy_config['hostname'] = hostname
                    if not _proxy_port:
                        port, record_flag = gsp.get_port(
                            proxy_config=_proxy_config,
                            last_record=proxy_record.get('port'),
                            valid_format='0~65535').values()
                        if record_flag:
                            self.record_flag = True
                            _proxy_config['port'] = port
                    if not all([_proxy_username, _proxy_password]):
                        username, password, record_flag = gsp.get_proxy_authentication().values()
                        if record_flag:
                            self.record_flag = True
                            _proxy_config['username'] = username
                            _proxy_config['password'] = password
        except KeyboardInterrupt:
            n: bool = True
            try:
                if self.record_flag:
                    print('\n')
                    if gsp.get_is_ki_save_config().get('is_ki_save_config'):
                        self.save_config(pre_load_config)
                        console.log('Configuration saved!')
                    else:
                        console.log('Current entries were not saved.')
                else:
                    raise SystemExit(0)
            except KeyboardInterrupt:
                n: bool = False
                print('\n')
                console.log('Current entries were not saved (configuration was cancelled by the user).')
            finally:
                if n:
                    print('\n')
                    console.log('Configuration was cancelled by the user.')
                ctrl_c()
                exit_flag: bool = True
        if exit_flag:
            raise SystemExit(0)
        pre_load_config.get(
            'max_tasks',
            {
                'download': _max_download_task,
                'upload': 3
            }
        )['upload'] = (pre_load_config.get('max_tasks') or {}).get('upload', 3) or 3
        pre_load_config.get(
            'max_retries',
            {
                'download': _max_download_retries,
                'upload': 3}
        )['upload'] = (pre_load_config.get('max_retries') or {}).get('upload', 3) or 3
        if not PARSE_ARGS.session:
            _session_directory = pre_load_config.get(
                'session_directory',
                UserConfig.WORK_DIRECTORY) or UserConfig.WORK_DIRECTORY
            pre_load_config['session_directory'] = _session_directory
        else:
            pre_load_config['session_directory'] = PARSE_ARGS.session

        if not PARSE_ARGS.temp:
            _temp_directory = pre_load_config.get(
                'temp_directory',
                UserConfig.TEMP_DIRECTORY) or UserConfig.TEMP_DIRECTORY
            pre_load_config['temp_directory'] = _temp_directory
        else:
            pre_load_config['temp_directory'] = PARSE_ARGS.temp
        self.save_config(pre_load_config)  # v1.3.0: fix saving the configuration even when the user chose not to save it.

    def save_config(self, config: dict) -> bool:
        temp_path: str = f'{self.config_path}.temp'
        with UserConfig.CONFIG_LOCK:  # Only synchronous file I/O occurs inside the lock (no await or nested lock calls), so this cannot deadlock.
            try:
                with open(file=temp_path, mode='w', encoding='UTF-8') as f:
                    yaml.dump(config, f)
                os.replace(temp_path, self.config_path)  # Replacing a file within the same directory is atomic.
            except Exception as e:
                log.error(f'Failed to save configuration file, {_t(KeyWord.REASON)}:"{e}"')
                return False
            finally:
                try:
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                except Exception:  # noqa.
                    pass
        log.info('Configuration file saved.')
        return True


class GlobalConfig(BaseConfig):
    FILE_NAME: str = GLOBAL_CONFIG_NAME
    PATH: str = GLOBAL_CONFIG_PATH
    TEMPLATE: dict = {
        'notice': True,
        'file_log_level': logging.getLevelName(FILE_LOG_LEVEL),
        'console_log_level': logging.getLevelName(CONSOLE_LOG_LEVEL),
        'export_table': {
            'link': False,
            'count': False,
            'upload': False
        },
        'upload':
            {
                'download_upload': True,
                'delete': False
            },
        'forward_type':
            {
                'video': True,
                'photo': True,
                'audio': True,
                'document': True,
                'voice': True,
                'text': True,
                'animation': True,
                'video_note': True,
                'live_photo': True
            },
        'authorized_users': []
    }

    def __init__(self):
        super().__init__()
        self.default_upload_nesting = self.TEMPLATE.get('upload')
        self.default_forward_type_nesting = self.TEMPLATE.get('forward_type')
        self.load_config()
        self.__check_params(self.config.copy())
        self.download_upload: bool = self.get_nesting_config(
            default_nesting=self.default_upload_nesting,
            param='upload',
            nesting_param='download_upload'
        )
        self.upload_delete: bool = self.get_nesting_config(
            default_nesting=self.default_upload_nesting,
            param='upload',
            nesting_param='delete'
        )
        self.forward_type: dict = self.config.get('forward_type')
        self.authorized_users: list = self.config.get('authorized_users', [])

    def get_nesting_config(self, default_nesting, param, nesting_param):
        return self.config.get(param, default_nesting).get(nesting_param)

    def save_config(self, config: dict) -> None:
        super().save_config(config)
        self.download_upload = self.get_nesting_config(
            default_nesting=self.default_upload_nesting,
            param='upload',
            nesting_param='download_upload'
        )
        self.upload_delete = self.get_nesting_config(
            default_nesting=self.default_upload_nesting,
            param='upload',
            nesting_param='delete'
        )
        self.forward_type: dict = self.config.get('forward_type')
        self.authorized_users: list = self.config.get('authorized_users', [])
        p = 'Global configuration reloaded.'
        console.log(p, style='#FF4689')
        log.info(f'{p.replace("。", ":")}{self.config}')

    def __check_params(self, config: dict) -> None:
        if config is None:
            config = {}

        # Process top-level parameters.
        self.add_missing_keys(
            target=config,
            template=self.TEMPLATE,
            log_message='"{}" is missing from the global configuration; added.'
        )
        # Process nested parameters.
        self.process_nesting(param_name='export_table', config=config)
        self.process_nesting(param_name='upload', config=config)
        self.process_nesting(param_name='forward_type', config=config)
        # Validate the authorized-user list and retain only integer user IDs.
        authorized_users: Union[list, object] = config.get('authorized_users')
        if not isinstance(authorized_users, list):
            config['authorized_users'] = []
        else:
            config['authorized_users'] = [
                uid for uid in authorized_users
                if isinstance(uid, int)
            ]
        # Remove fields that are not in the top-level template.
        self.remove_extra_keys(
            target=config,
            template=self.TEMPLATE,
            log_message='"{}" is not present in the template; removed.'
        )

        if config != self.config:
            self.config = config
            self.save_config(self.config)
