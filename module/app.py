# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2024-7-25 12:32:00
# File:app.py
import os
import time
import datetime
import subprocess

from typing import Union
from functools import wraps

import pyrogram

from module import (
    console,
    log,
    SOFTWARE_FULL_NAME,
    SOFTWARE_SHORT_NAME,
    VERSION_WITH_COMMIT
)
from module.language import _t
from module.config import UserConfig
from module.stdio import StatisticalTable
from module.client import TelegramRestrictedMediaDownloaderClient

from module.util import (
    get_message_dtype,
    AdjustableSemaphore
)
from module.enums import (
    KeyWord,
    DownloadType,
    DownloadStatus
)
from module.path_tool import (
    get_extension,
    validate_title,
    truncate_filename,
    is_compressed_file,
    extract_full_extension
)


class Application(UserConfig, StatisticalTable):
    APP_VERSION: str = f'TRMD {VERSION_WITH_COMMIT}@Pyrogram {pyrogram.__version__}'
    DEVICE_MODEL: str = SOFTWARE_SHORT_NAME

    def __init__(self):
        UserConfig.__init__(self)
        StatisticalTable.__init__(self)
        self.client = self.build_client()
        self.check_download_type()
        self.current_task_num: int = 0
        self.is_paused: bool = False  # Global pause flag: when true, the scheduler stops dispatching downloads/uploads and forwarding waits until resumed.

    def build_client(self) -> pyrogram.Client:
        """Build the Pyrogram client from the configured settings."""
        os.makedirs(self.work_directory, exist_ok=True)
        client = TelegramRestrictedMediaDownloaderClient(
            name=SOFTWARE_FULL_NAME.replace(' ', ''),
            api_id=self.api_id,
            api_hash=self.api_hash,
            proxy=self.proxy if self.enable_proxy else None,
            workdir=self.work_directory,
            app_version=Application.APP_VERSION,
            device_model=Application.DEVICE_MODEL
        )
        # Adjustable semaphores let the web panel change concurrency without discarding slots held by active transfers.
        client.get_file_semaphore = AdjustableSemaphore(self.max_download_task)
        client.save_file_semaphore = AdjustableSemaphore(self.max_upload_task)
        return client

    def process_shutdown(self, second: int) -> None:
        """Handle shutdown behavior."""
        self.shutdown_task(second=second) if self.config.get('is_shutdown') else None

    def get_temp_file_path(
            self,
            message: pyrogram.types.Message,
            dtype: str
    ) -> str:
        """Get the temporary save path for a file being downloaded."""

        def splice_chat_id(_file_name) -> str:
            try:
                chat_id: str = str(getattr(message.chat, 'id', 0))
                if chat_id:
                    temp_directory_with_chat_id: str = os.path.join(self.temp_directory, chat_id)
                    os.makedirs(temp_directory_with_chat_id, exist_ok=True)
                    _file: str = os.path.join(temp_directory_with_chat_id, validate_title(_file_name))
                else:
                    raise ValueError('chat id is empty.')
            except Exception as e:
                _file: str = os.path.join(self.temp_directory, validate_title(_file_name))
                log.warning(f'Unable to get channel ID while building temporary path, {_t(KeyWord.REASON)}:"{e}"')
            return _file

        os.makedirs(self.temp_directory, exist_ok=True)
        dt = DownloadFileName(message=message, download_type=dtype)
        if dtype in (DownloadType.VIDEO, DownloadType.VIDEO_NOTE):
            file_name: str = dt.get_video_filename()
        elif dtype in (DownloadType.PHOTO, DownloadType.LIVE_PHOTO):
            file_name: str = dt.get_photo_filename()
        elif dtype == DownloadType.DOCUMENT:
            file_name: str = dt.get_document_filename()
        elif dtype in (DownloadType.AUDIO, DownloadType.VOICE, DownloadType.ANIMATION):
            file_name: str = dt.get_filename()
        else:
            file_id = getattr(message, 'id', '0')
            time_format = '%Y-%m-%d_%H-%M-%S'
            file_name: str = f'{file_id} - {datetime.datetime.now().strftime(time_format)}.unknown'
        return truncate_filename(splice_chat_id(file_name))

    def on_record(func):  # noqa.

        @wraps(func)  # noqa.
        def wrapper(self, *args):
            res = func(self, *args)  # noqa.
            download_type = res
            _, file_name, download_status = args
            self.update_download_status(download_type, download_status, file_name)
            return res

        return wrapper

    def increase_task_num(self) -> None:
        """Increment the current download task count."""
        self.current_task_num += 1

    def decrease_task_num(self) -> None:
        """Decrement the current download task count."""
        self.current_task_num -= 1

    def update_download_status(
            self,
            download_type: str,
            download_status: str,
            file_name: str
    ):
        type_to_success = {
            DownloadType.PHOTO: self.success_photo,
            DownloadType.VIDEO: self.success_video,
            DownloadType.DOCUMENT: self.success_document,
            DownloadType.AUDIO: self.success_audio,
            DownloadType.VOICE: self.success_voice,
            DownloadType.ANIMATION: self.success_animation,
            DownloadType.VIDEO_NOTE: self.success_video_note,
            DownloadType.LIVE_PHOTO: self.success_live_photo
        }

        type_to_failure = {
            DownloadType.PHOTO: self.failure_photo,
            DownloadType.VIDEO: self.failure_video,
            DownloadType.DOCUMENT: self.failure_document,
            DownloadType.AUDIO: self.failure_audio,
            DownloadType.VOICE: self.failure_voice,
            DownloadType.ANIMATION: self.failure_animation,
            DownloadType.VIDEO_NOTE: self.failure_video_note,
            DownloadType.LIVE_PHOTO: self.failure_live_photo
        }

        type_to_skip = {
            DownloadType.PHOTO: self.skip_photo,
            DownloadType.VIDEO: self.skip_video,
            DownloadType.DOCUMENT: self.skip_document,
            DownloadType.AUDIO: self.skip_audio,
            DownloadType.VOICE: self.skip_voice,
            DownloadType.ANIMATION: self.skip_animation,
            DownloadType.VIDEO_NOTE: self.skip_video_note,
            DownloadType.LIVE_PHOTO: self.skip_live_photo
        }

        if download_status == DownloadStatus.SUCCESS:
            target_set = type_to_success[download_type]
        elif download_status == DownloadStatus.FAILURE:
            target_set = type_to_failure[download_type]
        elif download_status == DownloadStatus.SKIP:
            target_set = type_to_skip[download_type]
        else:
            return
        # Count a file in only one status: remove it from the other status sets of the same type before adding it to the target set.
        # Successful records use temporary paths (with a .temp suffix), while failures use final paths, so compare normalized names without .temp.
        # This supports a retry succeeding while avoiding accidental removal of different files that share a basename.
        base_name: str = os.path.basename(str(file_name))
        norm_name: str = base_name[:-len('.temp')] if base_name.lower().endswith('.temp') else base_name
        for other_set in (type_to_success[download_type], type_to_failure[download_type], type_to_skip[download_type]):
            if other_set is target_set:
                continue
            other_set.discard(file_name)
            other_set.discard(norm_name)
            other_set.difference_update({
                i for i in other_set
                if (os.path.basename(str(i))[:-len('.temp')]
                    if os.path.basename(str(i)).lower().endswith('.temp')
                    else os.path.basename(str(i))) == norm_name
            })
        target_set.add(file_name)

    def get_download_type(self, message: pyrogram.types.Message, default_type: str) -> str:
        """Get the message's download type for display only; do not record statistics."""
        return get_message_dtype(message, self.download_type) or default_type or 'unknown_type'

    @on_record  # noqa.
    def get_file_type(self, *args) -> str:
        message, file_name, download_type = args
        return self.get_download_type(message=message, default_type=download_type)

    def check_download_type(self) -> None:
        for dtype in self.download_type:
            if dtype not in DownloadType():
                self.download_type.remove(dtype)
                p = f'"{dtype}" is not a supported download type and has been removed.'
                console.log(p, style='#FF4689')
                log.info(p)
        if self.download_type:
            return None
        self.download_type = [_ for _ in DownloadType()]
        self.config['download_type'] = self.download_type
        self.save_config(config=self.config)
        console.log('No supported download types were selected. All supported types have been enabled by [#f08a5d]default[/#f08a5d].')

    def shutdown_task(self, second: int) -> None:
        """Shut down automatically after downloads finish."""
        try:
            if self.platform == 'Windows':
                # Start the shutdown command; currently only Windows shutdown is supported here.
                shutdown_command: str = f'shutdown -s -t {second}'
                subprocess.Popen(shutdown_command, shell=True)  # Run shutdown asynchronously.
            else:
                shutdown_command: str = f'shutdown -h +{second // 60}'
                subprocess.Popen(shutdown_command, shell=True)  # Run shutdown asynchronously.
            # Display the countdown in real time.
            for remaining in range(second, 0, -1):
                console.print(f'Shutting down in {remaining} seconds. Press CTRL+C to cancel.', end='\r', style='#ff4805')
                time.sleep(1)
            console.print('\nShutdown is about to begin!', style='#f6ad00')
        except KeyboardInterrupt:
            cancel_flag: bool = False
            # Cancel shutdown if the user presses CTRL+C.
            if self.platform == 'Windows':
                subprocess.Popen('shutdown -a', shell=True)  # Cancel shutdown.
                cancel_flag: bool = True
            else:
                try:
                    # Linux/macOS shutdown cancellation command.
                    subprocess.Popen('shutdown -c', shell=True)
                    cancel_flag: bool = True
                except Exception as e:
                    log.warning(f'Failed to cancel shutdown; this system may not support it, {_t(KeyWord.REASON)}:"{e}"')
            console.print('\nShutdown cancelled by user!', style='#4bd898') if cancel_flag else 0
        except Exception as e:
            log.error(f'Failed to schedule shutdown; this system may not support automatic shutdown, {_t(KeyWord.REASON)}:"{e}"')


class DownloadFileName:
    def __init__(
            self,
            message: pyrogram.types.Message,
            download_type: Union[str, 'DownloadType']
    ):
        self.message = message
        self.download_type = download_type

    def get_video_filename(self):
        """Handle video filenames."""
        default_mtype: str = 'video/mp4'  # v1.2.8: improve filename retrieval.
        media_object = getattr(self.message, self.download_type)
        title: Union[str, None] = getattr(media_object, 'file_name', None)  # v1.2.8: fix download errors when the filename is missing.
        try:
            if isinstance(title, str):
                if title.lower().startswith('video_'):  # v1.5.6: attempt to prevent duplicate downloads of date-named titles.
                    title = None
            if title is None:
                title: str = 'None'
            else:
                title: str = os.path.splitext(title)[0]
        except Exception as e:
            title: str = 'None'
            log.warning(f'Error while getting filename; renamed to "{title}", {_t(KeyWord.REASON)}:"{e}"')
        return '{} - {}.{}'.format(
            getattr(self.message, 'id', '0'),
            title,
            get_extension(
                file_id=media_object.file_id,
                mime_type=getattr(media_object, 'mime_type', default_mtype),
                dot=False
            )
        )

    def get_photo_filename(self):
        """Handle image filenames."""
        default_mtype: str = 'image/jpg'  # v1.2.8: improve filename retrieval.
        media_object = getattr(self.message, self.download_type)
        extension: str = 'unknown'
        if self.download_type == DownloadType.LIVE_PHOTO:
            media_object = getattr(self.message, DownloadType.LIVE_PHOTO)
            extension = 'mov'
        elif self.download_type == DownloadType.PHOTO:
            extension: str = get_extension(
                file_id=media_object.file_id,
                mime_type=default_mtype,
                dot=False
            )
        elif self.download_type == DownloadType.DOCUMENT:
            extension: str = get_extension(
                file_id=media_object.file_id,
                mime_type=getattr(media_object, 'mime_type', default_mtype),
                dot=False
            )
        return '{} - {}.{}'.format(
            getattr(self.message, 'id', '0'),
            getattr(media_object, 'file_unique_id', 'None'),
            extension
        )

    def get_document_filename(self):
        """Handle document filenames."""
        try:
            document_obj = getattr(self.message, self.download_type)
            _mime_type = getattr(document_obj, 'mime_type')
            if 'video' in _mime_type:
                return self.get_video_filename()
            elif 'image' in _mime_type:
                return self.get_photo_filename()
            elif _mime_type:
                origin_filename = getattr(document_obj, 'file_name', None)
                if origin_filename and is_compressed_file(origin_filename):
                    log.warning(
                        f'Archive file "{origin_filename}" detected. Its original name was kept to preserve integrity '
                        f'(for example, for split archives); resolve any filename conflicts manually.')
                    return origin_filename
                return self.get_filename()

        except (AttributeError, Exception) as e:
            log.info(f'Unable to determine the document file extension, {_t(KeyWord.REASON)}:"{e}"')
            file_id = getattr(self.message, 'id', '0')
            time_format = '%Y-%m-%d_%H-%M-%S'
            return f'{file_id} - {datetime.datetime.now().strftime(time_format)}.unknown'

    def get_filename(self):
        try:
            origin_extension = None
            media_obj = getattr(self.message, self.download_type)
            _mime_type = getattr(media_obj, 'mime_type')
            _origin_file_name = getattr(media_obj, 'file_name', None)

            if _origin_file_name:
                origin_extension = extract_full_extension(_origin_file_name)

            if not origin_extension:
                origin_extension = get_extension(
                    file_id=media_obj.file_id,
                    mime_type=_mime_type,
                    dot=False
                )

            return '{} - {}.{}'.format(
                getattr(self.message, 'id', '0'),
                getattr(media_obj, 'file_unique_id', 'None'),
                origin_extension
            )
        except Exception as e:
            log.info(f'Unable to determine the {_t(self.download_type)} file extension, {_t(KeyWord.REASON)}:"{e}"')
            file_id = getattr(self.message, 'id', '0')
            time_format = '%Y-%m-%d_%H-%M-%S'
            return f'{file_id} - {datetime.datetime.now().strftime(time_format)}.unknown'
