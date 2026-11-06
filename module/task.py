# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2025-02-27 17:38:00
# File:task.py
import os
import json
import math
import time
import asyncio

from functools import wraps
from typing import (
    Union,
    Optional,
    Callable
)

import pyrogram

from module import (
    log,
    console
)
from module.language import _t
from module.stdio import MetaData
from module.parser import PARSE_ARGS
from module.util import get_work_directory
from module.path_tool import (
    safe_delete,
    calc_sha256,
)
from module.enums import (
    KeyWord,
    UploadStatus,
    DownloadStatus,
    NoticeType
)


class DownloadTask:
    """Track pending messages and download progress for each link."""

    TASKS: dict = {}  # Link -> DownloadTask.
    ORDER: list = []  # Links in first-seen order; the scheduler dispatches them in this order.
    DOWNLOADING_KEYS: set = set()  # (chat_id, message_id) -> message currently downloading; prevents concurrent downloads of the same message through different links (e.g. a media group and one item), avoiding a race condition.
    PENDING_ENQUEUE: set = set()  # Links being parsed but not yet queued; no task object exists during parsing. Used by upload-side media-group polling to check whether any members are not yet queued.

    def __init__(self, link: Union[str, int]):
        self.link: str = str(link)
        self.link_type: Optional[str] = None
        self.chat_id: Union[str, int, None] = None
        self.member_num: int = 0
        self.complete_num: int = 0
        self.file_name: set = set()
        self.error_msg: dict = {}
        self.fail_id: set = set()  # Message IDs that permanently failed (retries exhausted).
        self.items: dict = {}  # Message ID -> pending message (dict; see add_item for fields).
        self.member_info: dict = {}  # Message ID -> display info and status for this link; retained after completion.
        self.max_retry: int = 0  # Retry limit locked for this task (set on first creation and reused for retries); 0 means not yet locked.
        self.owner: Union[int, None] = None  # ID of the user who created this task, used to notify that user.

    @property
    def fail_num(self) -> int:
        """Number of files that permanently failed (retries exhausted)."""
        return len(self.fail_id)

    @classmethod
    def get_or_create(cls, link: Union[str, int]) -> 'DownloadTask':
        """Get the download task for a link, creating it and recording its order if needed."""
        _link: str = str(link)
        task: Union[DownloadTask, None] = cls.TASKS.get(_link)
        if task is None:
            task = cls(_link)
            cls.TASKS[_link] = task
            cls.ORDER.append(_link)
        return task

    @classmethod
    def get(cls, link: Union[str, int, None]) -> Union['DownloadTask', None]:
        """Get the download task for a link."""
        return cls.TASKS.get(str(link))

    @classmethod
    def ordered_tasks(cls) -> list:
        """Return download tasks in the order their links first appeared."""
        return [cls.TASKS[link] for link in list(cls.ORDER) if link in cls.TASKS]

    @classmethod
    def add_item(
            cls,
            link: Union[str, int],
            chat_id: Union[str, int],
            message: Union[pyrogram.types.Message, list],
            link_type: Optional[str] = None,
            retry: Optional[dict] = None,
            with_upload: Optional[dict] = None,
            diy_download_type: Optional[list] = None
    ) -> None:
        """Add messages to a download task, resetting existing ones to the queued state."""
        task: DownloadTask = cls.get_or_create(link)
        messages: list = message if isinstance(message, list) else [message]
        retry_dict: dict = retry if retry else {'id': -1, 'count': 0}
        retry_id: int = int(retry_dict.get('id') or -1)
        retry_count: int = int(retry_dict.get('count') or 0)
        if retry_count == 0:
            task.clear_error()  # For a fresh fetch (not a retry), clear previous failures for this link.
            task.clear_fail()
            task.clear_file_name()  # Reset the completed count to avoid duplicate completion notices when reusing an old task.
        for _message in messages:
            key: int = int(getattr(_message, 'id', 0))
            if retry_count != 0 and key != retry_id:
                continue  # On retry, keep only the message being retried; do not queue the entire media group again.
            task.remove_fail(message_id=key)  # Clear the message's failure record when re-queuing it, including retries.
            existing: Union[dict, None] = task.items.get(key)
            current_status: Optional[str] = existing.get('status') if existing else None
            # Do not downgrade a downloading message to queued: this prevents the panel from showing it as queued
            # and prevents the scheduler from starting it again.
            # Exception: if no active download coroutine holds the message (its key is absent from DOWNLOADING_KEYS,
            # indicating a prior crash or forced termination before a terminal status was written),
            # treat it as orphaned and re-queue it so re-fetching the link does not leave it stuck in DOWNLOADING.
            dl_key = cls.download_key(_message, key)
            orphan_downloading: bool = (
                    current_status == DownloadStatus.DOWNLOADING
                    and dl_key is not None
                    and dl_key not in cls.DOWNLOADING_KEYS
            )
            if orphan_downloading:
                cls.DOWNLOADING_KEYS.discard(dl_key)  # Defensively clear a possibly stale reservation marker.
            re_enqueue: bool = current_status != DownloadStatus.DOWNLOADING or orphan_downloading
            task.update_member(  # Register the link member, including messages that remain visible after download.
                message_id=key,
                status=DownloadStatus.PENDING if re_enqueue else None,
                date=str(getattr(_message, 'date', '') or '')[:10]
            )
            item: Union[dict, None] = task.items.get(key)
            if item is None:
                task.items[key] = {
                    'link': task.link,
                    'chat_id': chat_id,
                    'message': _message,
                    'link_type': link_type,
                    'retry': retry_dict,
                    'with_upload': with_upload,
                    'diy_download_type': diy_download_type,
                    'status': DownloadStatus.PENDING,
                    'create_time': time.time(),
                    'meta': None  # Cached display metadata for the web panel.
                }
            elif re_enqueue:
                item['status'] = DownloadStatus.PENDING  # Reset the status for a retry.
            # Keep the existing status while downloading (when re_enqueue is False); do not downgrade it.

    def set_item_status(self, message_id: Union[int, str], status: str) -> None:
        """Set the queued status for a message and sync it to the link member."""
        item: Union[dict, None] = self.items.get(int(message_id))
        if item is not None:
            item['status'] = status
        self.update_member(message_id=message_id, status=status)

    def update_member(
            self,
            message_id: Union[int, str],
            status: Optional[str] = None,
            name: Optional[str] = None,
            size: Optional[str] = None,
            size_byte: Optional[int] = None,
            date: Optional[str] = None,
            task_id: Optional[int] = None,
            note: Optional[str] = None
    ) -> None:
        """Register or update the display information and status of a message under a link."""
        key: int = int(message_id)
        member: dict = self.member_info.get(key) or {
            'name': f'Message {key}',
            'size': '',
            'size_byte': 0,
            'date': '',
            'state': DownloadStatus.PENDING,
            'task_id': None,
            'note': ''
        }
        if status:
            member['state'] = status
        if name:
            member['name'] = name
        if size:
            member['size'] = size
        if size_byte is not None:
            member['size_byte'] = int(size_byte)
        if date is not None:
            member['date'] = date
        if task_id is not None:
            member['task_id'] = task_id
        if note:
            member['note'] = note
        self.member_info[key] = member

    def remove_item(self, message_id: Union[int, str]) -> None:
        """Remove the specified message from the download task."""
        self.items.pop(int(message_id), None)

    def get_pending_items(self, limit: int = 50) -> dict:
        """Get the PENDING messages queued in this download task."""
        items: list = [item for item in self.items.values() if item.get('status') == DownloadStatus.PENDING]
        return {'items': items[:limit], 'total': len(items)}

    @classmethod
    def queued_items(cls, limit: int = 50) -> list:
        """Get PENDING messages whose downloads have not started yet."""
        result: list = []
        for task in cls.ordered_tasks():
            for item in task.items.values():
                if item.get('status') == DownloadStatus.PENDING:
                    result.append(item)
        return result[:limit]

    @classmethod
    def download_key(cls, message: Union['pyrogram.types.Message', None], message_id: Union[int, str, None] = None) -> \
            Union[tuple, None]:
        """Build a download reservation key (chat_id, message_id); return None if message.chat is missing.

        Used for concurrent deduplication via DOWNLOADING_KEYS. Some messages (such as those
        reconstructed from serialized progress) may have message.chat set to None, in which case
        no valid deduplication key can be built; return None so the caller can skip deduplication.
        """
        if not isinstance(message, pyrogram.types.Message):
            return None
        chat = getattr(message, 'chat', None)
        inner_message_id = getattr(message, 'id', None)
        if chat is None:
            # These messages are usually saved under UNKNOWN_CHAT_ID, which can help trace the cause.
            log.warning(f'Message "{inner_message_id}" has no chat (it may have been deleted or be inaccessible); cannot build a download deduplication key, so concurrent deduplication was skipped.')
            return None
        return chat.id, message_id if message_id is not None else inner_message_id

    @classmethod
    def pick_pending(cls) -> Union[dict, None]:
        """Pick a queued (PENDING) message in the order its link first appeared.

        Skip messages reserved by another task (currently downloading) to avoid concurrent
        downloads of the same message through multiple links and the resulting race condition.
        """
        for task in cls.ordered_tasks():
            for item in task.items.values():
                if item.get('status') != DownloadStatus.PENDING:
                    continue
                message = item.get('message')
                if not isinstance(message, pyrogram.types.Message):
                    continue
                if cls.download_key(message) in cls.DOWNLOADING_KEYS:
                    continue
                return item
        return None

    @classmethod
    def has_task(cls) -> bool:
        """Check whether any tasks are unfinished or have not started yet."""
        for task in cls.ordered_tasks():
            for item in task.items.values():
                if item.get('status') in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING):
                    return True
        return False

    @classmethod
    def has_pending_message(cls, message_ids: set, chat_id: Optional[int] = None) -> bool:
        """Check whether any specified messages are queued or downloading (scoped to these messages).

        Args:
            message_ids: Set of message IDs to check (for example, all members of a media group).
            chat_id: Original channel ID. When provided, match the download reservation key
                (chat_id, message_id) exactly to detect a message downloading through another link.

        Returns:
            True if any member is queued or downloading; otherwise False.
        """
        if chat_id is not None:
            for message_id in message_ids:
                if (chat_id, message_id) in cls.DOWNLOADING_KEYS:
                    return True
        for task in cls.ordered_tasks():
            for key, item in task.items.items():
                if key not in message_ids:
                    continue
                if chat_id is not None:
                    message = item.get('message')
                    if not isinstance(message, pyrogram.types.Message):
                        continue
                    if getattr(message, 'chat', None) is not None and message.chat.id != chat_id:
                        continue
                if item.get('status') in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING):
                    return True
        return False

    @classmethod
    def has_pending_enqueue(cls) -> bool:
        """Check whether any links have started parsing but have not yet been queued in items.

        Range downloads (such as the restricted /forward fallback) split a range into individual
        links and parse them sequentially. Before parsing completes, a message is in neither
        DOWNLOADING_KEYS nor items, so upload-side media-group polling may mistake it for absent
        and send an incomplete album, with late members sent separately. Track links during parsing.
        """
        return bool(cls.PENDING_ENQUEUE)

    def add_file_name(self, file_name: str) -> None:
        """Record a completed file name and update the completion count."""
        self.file_name.add(file_name)
        self.complete_num = len(self.file_name)

    def set_error(self, value, key: Optional[str] = None) -> None:
        """Record download error information."""
        self.error_msg[key if key else 'all_member'] = value

    def clear_error(self, key: Optional[str] = None) -> None:
        """Clear download error information; if key is specified, clear only that file's failure record."""
        if key is None:
            self.error_msg.clear()
            return
        self.error_msg.pop(key, None)

    def add_fail(self, message_id: Union[int, str]) -> None:
        """Record a message that permanently failed (retries exhausted)."""
        self.fail_id.add(int(message_id))

    def remove_fail(self, message_id: Union[int, str]) -> None:
        """Remove a message's failure record when it is re-queued or downloaded successfully."""
        self.fail_id.discard(int(message_id))

    def clear_fail(self) -> None:
        """Clear all failure records."""
        self.fail_id.clear()

    def clear_file_name(self) -> None:
        """Clear completed file-name records and reset the completion count.

        Called when fetching the same link again (not a retry), to prevent a reused task's
        complete_num from causing done_notice to send duplicate completion notices.
        """
        self.file_name.clear()
        self.complete_num = 0

    def on_create_task(func):  # noqa.
        @wraps(func)  # noqa.
        async def wrapper(self, *args, **kwargs):
            message_ids = kwargs.get('message_ids')
            link = message_ids
            if isinstance(message_ids, pyrogram.types.Message):
                link = message_ids.link if message_ids.link else message_ids.id
            task: DownloadTask = DownloadTask.get_or_create(link)
            res: dict = await func(self, *args, **kwargs)  # noqa.
            status: Union[str, None] = res.get('status')
            e_code: Union[dict, None] = res.get('e_code')
            if status == DownloadStatus.FAILURE:
                task.error_msg = e_code
                # Link-level parse failures (such as a missing channel or message) bypass add_item,
                # leaving the web panel without a failed member to classify in the failure section.
                # Register a sentinel failed member with message_id=-1 (real message IDs start at 1),
                # allowing the existing web-panel logic to recognize it as a failure.
                fail_reason: str = (e_code or {}).get('error_msg') or (e_code or {}).get('all_member') or 'Download failed'
                task.update_member(message_id=-1, status=DownloadStatus.FAILURE, name=fail_reason)
                task.add_fail(-1)
                reason: str = e_code.get('error_msg')
                if reason:
                    log.error(
                        f'{_t(KeyWord.DOWNLOAD_TASK)}'
                        f'{_t(KeyWord.LINK)}:"{link}"{reason},'
                        f'{_t(KeyWord.REASON)}:"{e_code.get("all_member")}",'
                        f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.FAILURE)}。'
                    )
                else:
                    log.warning(
                        f'{_t(KeyWord.DOWNLOAD_TASK)}'
                        f'{_t(KeyWord.LINK)}:"{link}"{e_code.get("all_member")},'
                        f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.FAILURE)}。'
                    )
            elif status == DownloadStatus.DOWNLOADING:
                # If this link previously failed to parse (with a -1 sentinel, failure count, or error),
                # clear those records now that parsing succeeded, so no failure count remains.
                task.member_info.pop(-1, None)
                task.fail_id.discard(-1)
                task.error_msg = {}
            return res

        return wrapper

    def on_complete(func):  # noqa.
        @wraps(func)  # noqa.
        def wrapper(self, *args, **kwargs):
            res = func(self, *args, **kwargs)  # noqa.
            if all(i is None for i in res):
                return None
            link, file_name = res
            task: Union[DownloadTask, None] = DownloadTask.get(link)
            if task is None:
                return res
            task.add_file_name(file_name)
            if task.member_num == task.complete_num:
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.LINK)}:"{link}",'
                    f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.SUCCESS)}。'
                )
                task.error_msg = {}
                asyncio.create_task(self.done_notice(f'"{link}" download completed.', requester=task.owner, notice_type=NoticeType.DOWNLOAD))
                log.info(f'Link "{link}" download complete.')
            return res

        return wrapper


class UploadTask:
    DIRECTORY_NAME: str = PARSE_ARGS.temp or os.path.join(get_work_directory(), 'temp')
    PART_SIZE: int = 512 * 1024
    TASKS: set = set()
    TASK_COUNTER: int = 0
    NOTIFY: Optional[Callable] = None
    # Local file path being uploaded -> {'event': asyncio.Event, 'media': reference to uploaded media or None, 'success': bool}.
    # When the same file is uploaded concurrently, later tasks wait for the lead task and reuse its uploaded media reference.
    # Send directly to our own channel to avoid duplicate uploads and races over source-file deletion (only the lead task deletes it).
    UPLOADING_KEYS: dict = {}

    def __init__(
            self,
            chat_id: Union[str, int, None],
            file_path: str,
            file_id: int,
            file_size: int,
            file_part: Union[list],
            status: Union[UploadStatus, str],
            error_msg: Union[str, None] = None,
            with_delete: bool = False,
            media_group: Optional[asyncio.Task] = None,
            message_id: Optional[int] = None,
            send_as_media_group: bool = False,
            caption: Union[str, None] = None,
            caption_entities: Union[list, None] = None,
            owner: Union[int, None] = None
    ):
        UploadTask.TASKS.add(self)
        UploadTask.TASK_COUNTER += 1
        self.owner: Union[int, None] = owner  # ID of the user who created this task, used to notify that user.
        self.chat_id: Union[str, int, None] = chat_id
        self.file_path: str = file_path
        self.file_name: str = os.path.basename(file_path)
        self.file_id: int = file_id
        self.file_size: int = file_size
        self.file_part: list = file_part
        self.status: Union[UploadStatus, str] = status
        self.error_msg: Union[str, None] = error_msg
        self.with_delete: bool = with_delete
        self.file_total_parts = int(math.ceil(file_size / UploadTask.PART_SIZE))
        self.__media_group: asyncio.Task = media_group
        self.message_id: Optional[int] = message_id
        self.send_as_media_group: bool = send_as_media_group
        self.caption: Union[str, None] = caption
        self.caption_entities: Union[list, None] = caption_entities
        self.sha256: str = calc_sha256(file_path=self.file_path)
        self.prompt: str = ''
        self.task_id: Union[int, None] = None  # Progress-bar task ID, used by the web panel to associate upload progress.

    def __setattr__(self, name, value):
        if name.startswith('_'):
            super().__setattr__(name, value)
        else:
            if hasattr(self, name):
                old_value = getattr(self, name)
                if old_value != value:
                    super().__setattr__(name, value)
                    if name == 'status':
                        if value == UploadStatus.PENDING:
                            pass
                        elif value == UploadStatus.UPLOADING:
                            console.log(
                                f'{_t(KeyWord.UPLOAD_TASK)}'
                                f'{_t(KeyWord.CHANNEL)}:"{self.chat_id}",'
                                f'{_t(KeyWord.FILE)}:"{self.file_path}",'
                                f'{_t(KeyWord.SIZE)}:{MetaData.suitable_units_display(self.file_size)},'
                                f'{_t(KeyWord.STATUS)}:{_t(UploadStatus.UPLOADING)}。'
                            )
                        elif value == UploadStatus.SUCCESS:
                            more = ''
                            if self.send_as_media_group:
                                more += '(waiting for all media to finish uploading before sending the media group)'
                            if self.with_delete:
                                more += '(local file deleted)'
                            console.log(
                                f'{_t(KeyWord.UPLOAD_TASK)}'
                                f'{_t(KeyWord.CHANNEL)}:"{self.chat_id}",'
                                f'{_t(KeyWord.FILE)}:"{self.file_path}",'
                                f'{_t(KeyWord.SIZE)}:{MetaData.suitable_units_display(self.file_size)},'
                                f'{_t(KeyWord.STATUS)}:{_t(UploadStatus.SUCCESS)}{more}。',
                            )
                            self.notice(f'"{self.file_path}" ⬆️ "{self.chat_id}" upload complete.\n{more}')
                        elif value == UploadStatus.SENT:
                            pass
                        elif value == UploadStatus.FAILURE:
                            log.error(
                                f'{_t(KeyWord.UPLOAD_TASK)}'
                                f'{_t(KeyWord.CHANNEL)}:"{self.chat_id}",'
                                f'{_t(KeyWord.FILE)}:"{self.file_path}",'
                                f'{_t(KeyWord.SIZE)}:{MetaData.suitable_units_display(self.file_size)},'
                                f'{_t(KeyWord.REASON)}:"{self.error_msg}",'
                                f'{_t(KeyWord.STATUS)}:{_t(str(value))}。'
                            )
                            self.notice(f'"{self.file_path}" ⬆️ "{self.chat_id}" upload failed.')
                    elif name == 'chat_id':
                        if value:
                            self.upload_manager_path: str = os.path.join(
                                UploadTask.DIRECTORY_NAME,
                                f'{self.sha256}.json'
                            )
                        os.makedirs(os.path.dirname(self.upload_manager_path), exist_ok=True)
                        self.load_json()
                    elif name == 'prompt':
                        self.notice(self.prompt)

            else:
                super().__setattr__(name, value)

    @property
    def is_media_group(self) -> bool:
        if self.__media_group:
            return True
        return False

    async def get_media_group(self) -> Union[pyrogram.types.List, None]:
        if self.is_media_group:
            return await self.__media_group

    def notice(self, message: str):
        if isinstance(self.NOTIFY, Callable):
            asyncio.create_task(
                self.NOTIFY(
                    message, requester=self.owner, notice_type=NoticeType.UPLOAD
                )
            )

    @property
    def complete_task(self) -> int:
        complete = []
        for task in UploadTask.TASKS:
            if task.status == UploadStatus.SUCCESS:
                complete.append(task)
        return len(complete)

    def save_json(self):
        with open(file=self.upload_manager_path, mode='w', encoding='UTF-8') as f:
            json.dump(
                obj={
                    'file_id': self.file_id,
                    'file_size': self.file_size,
                    'file_part': self.file_part,
                    'file_total_parts': self.file_total_parts
                },
                fp=f,
                ensure_ascii=False,
                indent=4
            )

    def load_json(self):
        if not os.path.exists(self.upload_manager_path):
            self.save_json()
            return
        with open(file=self.upload_manager_path, mode='r', encoding='UTF-8') as f:
            _json: dict = {}
            try:
                _json = json.load(f)
            except Exception as e:
                log.info(f'UploadManager JSON may be empty; recreating it. {_t(KeyWord.REASON)}: "{e}"')
                safe_delete(self.upload_manager_path)
                self.save_json()
        self.file_id = _json.get('file_id', self.file_id)
        self.file_size = _json.get('file_size', self.file_size)
        self.file_part = _json.get('file_part', self.file_part)
        self.file_total_parts = _json.get('file_total_parts', self.file_total_parts)

    def update_file_part(self, file_part: int):
        if file_part not in self.file_part and file_part < self.file_total_parts:
            self.file_part.append(file_part)
            self.save_json()

    def reset_upload(self, file_id: int):
        """Discard the cached chunk history and re-upload all chunks using a new file_id."""
        self.file_id = file_id
        self.file_part = []
        self.save_json()

    @staticmethod
    def has_pending_media_group_tasks(
            message_ids: Optional[set] = None,
            origin_chat_id: Optional[int] = None
    ) -> bool:
        """Check for pending or uploading media-group tasks, or group members still downloading.

        Checking only the upload queue cannot confirm that a media group is complete: a member may
        still be downloading and have no upload task yet. Treating the group as complete then would
        send an incomplete album, so also check download tasks. Messages being parsed are not yet
        represented in the task system, so links not yet queued must also be checked.

        Args:
            message_ids: Set of message IDs in this media group. When provided, check only their
                download status to avoid waiting on unrelated tasks; otherwise check globally.
            origin_chat_id: Original channel ID, used with message_ids to match download reservations exactly.
        """
        # Links remain unqueued at the command layer, so their members are not yet in the task system.
        # This is different from having no pending tasks: keep waiting, or an incomplete album may be sent
        # before late-arriving members are sent separately.
        if DownloadTask.PENDING_ENQUEUE:
            return True
        for task in UploadTask.TASKS:
            if task.status in (UploadStatus.PENDING, UploadStatus.UPLOADING) and task.is_media_group:
                return True
        # Also check whether this media group's members are still downloading (PENDING/DOWNLOADING),
        # so the group is not mistaken for complete while a member is still downloading.
        if not message_ids:
            return DownloadTask.has_task()
        return DownloadTask.has_pending_message(message_ids=message_ids, chat_id=origin_chat_id)

    @staticmethod
    def get_media_group_task_count(message_ids: set) -> int:
        """Count created UploadTasks for the specified media_group_id and message_ids.

        Args:
            message_ids: Set of message IDs to check.

        Returns:
            int: Number of created UploadTasks, excluding sent and failed tasks.

        Failed tasks (for example, files exceeding the upload size limit or exhausted retries) will
        never be collected again. Counting them would prevent the media-group poll's
        created_count == collected_count condition from ever becoming true, leaving the album stuck.
        Exclude them along with SENT tasks so the remaining successful members can be sent.
        """
        if not message_ids:
            return 0

        count = 0
        for task in UploadTask.TASKS:
            if task.message_id in message_ids and task.status not in (UploadStatus.SENT, UploadStatus.FAILURE):
                count += 1

        return count

    def get_missing_parts(self) -> list:
        """Get the indexes of missing chunks."""
        valid_parts = []
        for part in self.file_part:
            if isinstance(part, int) and 0 <= part < self.file_total_parts and part not in valid_parts:
                valid_parts.append(part)
            else:
                log.info(f'Filtered invalid part index {part} (valid range: 0–{self.file_total_parts - 1}).')

        if len(valid_parts) != len(self.file_part):
            self.file_part = valid_parts
            self.save_json()
            log.info(f'Part indexes after cleanup: {valid_parts}.')

        all_parts = set(range(self.file_total_parts))
        uploaded_parts = set(valid_parts)
        missing_parts = sorted(list(all_parts - uploaded_parts))

        log.info(f'Total parts: {all_parts}; uploaded: {uploaded_parts}; missing: {missing_parts}.')
        return missing_parts
