# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2023-10-03 01:00:03
# File:downloader.py
import os
import sys
import asyncio

from functools import partial
from sqlite3 import OperationalError
from typing import (
    Set,
    Dict,
    Union,
    Callable,
    Optional
)

import pyrogram

from pyrogram.handlers import MessageHandler
from pyrogram.enums.parse_mode import ParseMode
from pyrogram.types.messages_and_media import ReplyParameters
from pyrogram.errors.exceptions.forbidden_403 import ChatWriteForbidden
from pyrogram.errors import (
    BadMsgNotification,
    FileReferenceExpired,
    FloodWait,
    FloodPremiumWait,
    AuthBytesInvalid
)
from pyrogram.errors.exceptions.bad_request_400 import (
    MsgIdInvalid,
    UsernameInvalid,
    ChannelInvalid,
    BotMethodInvalid,
    UsernameNotOccupied,
    PeerIdInvalid,
    MessageNotModified,
    ChannelPrivate as ChannelPrivate_400,
    ChatForwardsRestricted as ChatForwardsRestricted_400
)
from pyrogram.errors.exceptions.not_acceptable_406 import (
    ChannelPrivate as ChannelPrivate_406,
    ChatForwardsRestricted as ChatForwardsRestricted_406
)
from pyrogram.errors.exceptions.unauthorized_401 import (
    SessionRevoked,
    AuthKeyUnregistered,
    SessionExpired,
    Unauthorized
)
from pyrogram.types.bots_and_keyboards import (
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from module import (
    log,
    console,
    FORWARD_LIMIT
)
from module.web import Web
from module.remote import rc
from module.language import _t
from module.filter import Filter
from module.app import Application
from module.notice import NoticeHub
from module.parser import PARSE_ARGS
from module.uploader import TelegramUploader
from module.task import (
    DownloadTask,
    UploadTask
)
from module.stdio import (
    MetaData,
    ProgressBar,
    Base64Image,
    ConnectionStatus
)
from module.bot import (
    Bot,
    KeyboardButton,
    CallbackData,
    CallbackContext,
    dispatch_callback_data
)
from module.storage import (
    build_storage_database,
    StorageDatabase,
    StorageType,
    TRMDStorage
)
from module.enums import (
    Emoji,
    Issues,
    LinkType,
    KeyWord,
    BotButton,
    BotMessage,
    DownloadType,
    DownloadStatus,
    NoticeType,
    BotCallbackText,
    SaveDirectoryPrefix
)
from module.path_tool import (
    split_path,
    safe_delete,
    safe_replace,
    get_file_size,
    validate_title,
    compare_file_size,
    is_file_duplicate,
    move_to_save_directory
)
from module.util import (
    ChatInfo,
    LimitCall,
    ctrl_c,
    get_my_id,
    parse_link,
    parse_chat_id,
    js_referral,
    safe_length,
    safe_message,
    flip_emoji,
    get_executable_path,
    format_chat_link,
    check_environment,
    get_message_dtype,
    collect_message_id,
    safe_delete_message,
    get_message_by_link,
    get_chat_with_notify,
    save_message_entities,
    truncate_display_filename
)


class TelegramRestrictedMediaDownloader(Bot):

    def __init__(self):
        super().__init__()
        self.loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self.event: asyncio.Event = asyncio.Event()
        self.pause_event: asyncio.Event = asyncio.Event()  # Global pause event; clear while paused and set when resumed.
        self.queue: asyncio.Queue = asyncio.Queue()
        self.scheduler: Union[asyncio.Task, None] = None  # Download scheduler.
        self.pending_retry_tasks: Set[asyncio.Task] = set()  # Retries awaiting execution; keeps the main loop from exiting before a retry is requeued.
        self.app: Application = Application()
        self.is_running: bool = False
        self.running_log: Set[bool] = set()
        self.running_log.add(self.is_running)
        self.pb: ProgressBar = ProgressBar()
        self.uploader: Union[TelegramUploader, None] = None
        self.cd: Union[CallbackData, None] = None
        self.forward_limit_call: Union[LimitCall, None] = None  # Forwarding rate limiter to help avoid anti-abuse triggers from forwarding too quickly.
        self.web_remove_listen: set = set()  # Listener-removal commands from the web panel; remove directly without a second confirmation button.
        self.media_group_ids_cache: dict = {}  # Cache of media-group member IDs, keyed by media_group_id to avoid repeated get_media_group() calls.
        self.my_id: int = 0
        self.web: Web = Web(progress=self.pb.progress, app=self.app, downloader=self)  # The web panel is enabled by default; set its port with --port.
        self.storage_database: Union[StorageDatabase, None] = None  # Web storage database for download and upload records.
        self.pending_storage_tasks: Set[asyncio.Task] = set()  # Storage tasks awaiting database writes; wait for them on exit to avoid losing the last records.
        self.chat_progress_trackers: Set[asyncio.Task] = set()  # Background /download_chat progress trackers; the event loop holds only weak task references, so keep strong references here.

    def env_save_directory(
            self,
            message: pyrogram.types.Message
    ) -> str:
        save_directory = self.app.save_directory
        for placeholder in SaveDirectoryPrefix():
            if placeholder in save_directory:
                if placeholder == SaveDirectoryPrefix.CHAT_ID:
                    save_directory = save_directory.replace(
                        placeholder,
                        str(getattr(getattr(message, 'chat'), 'id', 'UNKNOWN_CHAT_ID'))
                    )
                if placeholder == SaveDirectoryPrefix.CHAT_NAME:
                    save_directory = save_directory.replace(
                        placeholder,
                        validate_title(str(getattr(getattr(message, 'chat'), 'full_name', 'UNKNOWN_CHAT_NAME')))
                    )
                if placeholder == SaveDirectoryPrefix.MIME_TYPE:
                    dtype: str = get_message_dtype(message, self.app.download_type)
                    if dtype:
                        save_directory = save_directory.replace(placeholder, dtype)
                if placeholder in (SaveDirectoryPrefix.MESSAGE_ID, SaveDirectoryPrefix.MESSAGE_ID_WITH_ENTITIES):
                    media_group_id = getattr(message, 'media_group_id', None)
                    if media_group_id:
                        group_ids = self.media_group_ids_cache.get(media_group_id)
                        group_range = f'{min(group_ids)}-{max(group_ids)}' if group_ids else None
                        save_directory = save_directory.replace(
                            placeholder, group_range if group_range else str(media_group_id))
                    else:
                        save_directory = save_directory.replace(
                            placeholder,
                            str(getattr(message, 'id', 'UNKNOWN_MESSAGE_ID'))
                        )
        return save_directory

    def add_web_storage(self, storage: TRMDStorage) -> None:
        """Register web download/upload storage.

        Storage is auxiliary: errors while scheduling database writes are logged only and never affect the main download/upload flow.
        """

        if self.storage_database is None:
            return
        try:
            task = asyncio.create_task(self.storage_database.add_storage(storage))
            self.pending_storage_tasks.add(task)
            task.add_done_callback(self.pending_storage_tasks.discard)
        except Exception as e:
            log.warning(f'Failed to register web storage, {_t(KeyWord.REASON)}: "{e}"')

    def storage_download(
            self,
            message: pyrogram.types.Message,
            link: str,
            file_name: str,
            file_size: int,
            status: str,
            error_msg: str = ''
    ) -> None:
        """Register a download record using the final save path after the download completes."""

        if self.storage_database is None:
            return
        chat = getattr(message, 'chat', None)
        chat_id = parse_chat_id(link, getattr(chat, 'id', None))
        self.add_web_storage(
            TRMDStorage(
                storage_type=StorageType.DOWNLOAD,
                chat_id=chat_id,
                chat_name=ChatInfo.get(chat_id) or str(
                    getattr(chat, 'title', '') or getattr(chat, 'first_name', '') or ''),
                message_id=getattr(message, 'id', None),
                file_name=file_name,
                file_path=os.path.join(self.env_save_directory(message), file_name),
                file_size=file_size,
                file_type=get_message_dtype(message, self.app.download_type) or '',
                status=status,
                error_msg=error_msg,
                link=str(link)
            )
        )

    async def get_download_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            with_upload: Union[dict, None] = None,
            owner: Union[int, None] = None
    ):
        link_meta: Union[dict, None] = await super().get_download_link_from_bot(client, message, owner=owner,
                                                                                with_upload=with_upload)
        if link_meta is None:
            return None
        right_link: set = link_meta.get('right_link')
        invalid_link: set = link_meta.get('invalid_link')
        last_bot_message: Union[pyrogram.types.Message, None] = link_meta.get('last_bot_message')
        link_count: int = len(right_link) + len(invalid_link)
        if last_bot_message and link_count <= Bot.MAX_BOT_NOTICE_ITEMS:  # Above this message-count limit, notices become too long and frequent edits risk rate limits, so no notice is sent.
            await self.safe_edit_message(
                client=client,
                message=message,
                last_message_id=last_bot_message.id,
                text=self.update_text(
                    right_link=right_link,
                    invalid_link=invalid_link
                )
            )
        elif not with_upload and link_count > Bot.MAX_BOT_NOTICE_ITEMS:  # Warn only when there are too many links and this is not a download-and-upload task; upload results report its outcomes, so suppressing this notice is not an error.
            log.info('Message is too long; this task notification cannot be displayed through the bot.')
        links: Union[set, None] = self.__process_links(link=list(right_link))

        if links is None:
            return None
        # Record the task creator so download-completion and follow-up download-and-upload notices go to the requester.
        # Prefer the explicitly supplied owner (for restricted download-and-upload tasks); otherwise use the message sender.
        requester = owner if owner is not None else message.from_user.id
        # Record the creator's display name so the web panel's "Notifications" section can show who created the task.
        NoticeHub.add_owner(owner=requester, user=message.from_user)
        for link in links:
            # Pre-register to cover the gap between the previous item being queued and the next item starting parsing; create_download_task removes it after enqueueing.
            DownloadTask.PENDING_ENQUEUE.add(link)
            task: dict = await self.create_download_task(
                message_ids=link,
                retry=None,
                with_upload=with_upload,
                owner=requester
            )
            dl_task = DownloadTask.get(link)
            # Different users may download the same link over time, and the task object remains cached in TASKS.
            # Refresh ownership on every request, or the first user's ownership will persist and completion notices will go to the wrong person.
            if dl_task is not None:
                dl_task.owner = requester
            if isinstance(with_upload, dict) and with_upload.get('owner') is None:
                with_upload['owner'] = requester
            invalid_link.add(link) if task.get('status') == DownloadStatus.FAILURE else self.bot_task_link.add(link)
        right_link -= invalid_link
        if last_bot_message and link_count <= Bot.MAX_BOT_NOTICE_ITEMS:
            await self.safe_edit_message(
                client=client,
                message=message,
                last_message_id=last_bot_message.id,
                text=self.update_text(
                    right_link=right_link,
                    invalid_link=invalid_link
                )
            )

    async def get_upload_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            delete: bool = False,
            save_directory: str = None,
            recursion: bool = False,
            valid_link_cache: dict = None
    ):
        link_meta: Union[dict, None] = await super().get_upload_link_from_bot(
            client=client,
            message=message,
            delete=delete,
            save_directory=save_directory,
            recursion=recursion,
            valid_link_cache=valid_link_cache
        )
        if link_meta is None:
            return None
        target_link: str = link_meta.get('target_link')
        valid_link_cache: dict = link_meta.get('valid_link_cache')
        upload_task = link_meta.get('upload_task')
        upload_task.with_delete = self.gc.upload_delete
        await self.uploader.create_upload_task(
            link=valid_link_cache.get(target_link, None) or target_link if valid_link_cache else target_link,
            upload_task=upload_task,
        )

    @staticmethod
    async def send_pay_qr(
            client: pyrogram.Client,
            chat_id: Union[int, str],
            load_name: str
    ) -> Union[list, str, None]:
        try:
            last_msg = await client.send_message(
                chat_id=chat_id,
                text=f'🚛 Loading {load_name}, please wait...',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            tasks = [client.send_photo(
                chat_id=chat_id,
                photo=Base64Image.base64_to_binary_io(Base64Image.pay),
                disable_notification=True
            ),
                client.edit_message_text(
                    chat_id=chat_id,
                    message_id=last_msg.id,
                    text=f'✅ {load_name} loaded successfully.'
                )]
            await asyncio.gather(*tasks)
        except Exception as e:
            return str(e)

    async def start(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        self.last_client: pyrogram.Client = client
        self.last_message: pyrogram.types.Message = message
        if getattr(PARSE_ARGS, 'test', False):
            return None
        if self.gc.config.get(BotCallbackText.NOTICE):
            chat_id = message.from_user.id
            await asyncio.gather(
                self.send_pay_qr(
                    client=client,
                    chat_id=chat_id,
                    load_name='Bot'
                ),
                super().start(client, message),
                client.send_message(
                    chat_id=chat_id,
                    text='😊 Welcome! Your support motivates me to keep improving the app.',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS)
            )
        else:
            await super().start(client, message)

    async def callback_data(self, client: pyrogram.Client, callback_query: pyrogram.types.CallbackQuery):
        data = await super().callback_data(client, callback_query)
        if data is None:
            return None
        kb = KeyboardButton(callback_query)
        ctx = CallbackContext(downloader=self, client=client, query=callback_query, kb=kb, data=data)
        await dispatch_callback_data(ctx)

    async def forward(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            message_id: int,
            origin_chat_id: Union[str, int],
            target_chat_id: Union[str, int],
            target_link: str,
            download_upload: Optional[bool] = False,
            media_group: Optional[list] = None,
            owner: Union[int, None] = None
    ):
        try:
            if not self.check_type(message):
                console.log(
                    f'{_t(KeyWord.CHANNEL)}:"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:"{message_id}"'
                    f' -> '
                    f'{_t(KeyWord.CHANNEL)}:"{target_chat_id}",'
                    f'{_t(KeyWord.STATUS)}:{_t(KeyWord.FORWARD_SKIP)}。'
                )
                await asyncio.create_task(
                    self.done_notice(
                        f'"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:{message_id}'
                        f' ➡️ '
                        f'"{target_chat_id}",{_t(KeyWord.FORWARD_SKIP)} (this media type was filtered out).',
                        requester=owner,
                        notice_type=NoticeType.FORWARD
                    )
                )
                return None
            # Do not forward while globally paused; wait until processing resumes.
            while self.app.is_paused:
                await self.pause_event.wait()
            # Limit forwards per minute to help avoid anti-abuse triggers from forwarding too quickly.
            await self.forward_limit_call.wait() if isinstance(self.forward_limit_call, LimitCall) else None
            if media_group:
                while True:
                    try:
                        await self.app.client.copy_media_group(
                            chat_id=target_chat_id,
                            from_chat_id=origin_chat_id,
                            message_id=message_id,
                            disable_notification=True
                        )
                        break
                    except (FloodWait, FloodPremiumWait) as e:
                        amount = e.value
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Message forwarding is being rate-limited; wait {amount} seconds before retrying.'
                        )
                        await asyncio.sleep(amount)
                        ConnectionStatus.leave_flood()
            elif getattr(message, 'text', False):
                while True:
                    try:
                        await self.app.client.send_message(
                            chat_id=target_chat_id,
                            text=message.text,
                            entities=getattr(message, 'entities', None),
                            disable_notification=True,
                            protect_content=False
                        )
                        break
                    except (FloodWait, FloodPremiumWait) as e:
                        amount = e.value
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Message sending is being rate-limited; wait {amount} seconds before retrying.'
                        )
                        await asyncio.sleep(amount)
                        ConnectionStatus.leave_flood()
                    except Exception as e:
                        log.error(f'Failed to forward message "{message.text}", {_t(KeyWord.REASON)}: "{e}"')
                        break
            else:
                while True:
                    try:
                        await self.app.client.copy_message(
                            chat_id=target_chat_id,
                            from_chat_id=origin_chat_id,
                            message_id=message_id,
                            disable_notification=True,
                            protect_content=False
                        )
                        break
                    except (FloodWait, FloodPremiumWait) as e:
                        amount = e.value
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Message forwarding is being rate-limited; wait {amount} seconds before retrying.'
                        )
                        await asyncio.sleep(amount)
                        ConnectionStatus.leave_flood()
            p_message_id = ','.join(map(str, media_group)) if media_group else message_id
            console.log(
                f'{_t(KeyWord.CHANNEL)}:"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:"{p_message_id}"'
                f' -> '
                f'{_t(KeyWord.CHANNEL)}:"{target_chat_id}",'
                f'{_t(KeyWord.STATUS)}:{_t(KeyWord.FORWARD_SUCCESS)}。'
            )
            await asyncio.create_task(
                self.done_notice(
                    f'"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:{p_message_id}'
                    f' ➡️ '
                    f'"{target_chat_id}",{_t(KeyWord.FORWARD_SUCCESS)}。',
                    requester=owner,
                    notice_type=NoticeType.FORWARD
                )
            )
        except (ChatForwardsRestricted_400, ChatForwardsRestricted_406):
            if not download_upload:
                if (
                        getattr(getattr(message, 'chat', None), 'is_creator', False) or
                        getattr(getattr(message, 'chat', None), 'is_admin', False)
                ) and (
                        getattr(getattr(message, 'from_user', None), 'id', -1) ==
                        getattr(getattr(client, 'me', None), 'id', None)
                ):
                    return None
                raise
            link = message.link
            if not self.gc.download_upload:
                await self.bot.send_message(
                    # Notify the creator of the forwarding task; if the creator was not recorded, fall back to the logged-in account.
                    chat_id=owner if owner is not None else client.me.id,
                    text=f'⚠️ Unable to forward\n'
                         f'`{link}`\n'
                         f'Content protection is enabled. To use download-and-upload for restricted forwards, configure it under Settings > Upload settings.',
                    reply_parameters=ReplyParameters(message_id=message_id),
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        BotButton.SETTING,
                        callback_data=BotCallbackText.SETTING
                    )]]))
                return None
            original_text = self.last_message.text
            try:
                self.last_message.text = f'/download {link}?single'
                await self.get_download_link_from_bot(
                    client=self.last_client,
                    message=self.last_message,
                    with_upload={
                        'link': target_link,
                        'file_name': None,
                        'with_delete': self.gc.upload_delete,
                        'send_as_media_group': True,
                        'owner': owner
                    },
                    owner=owner
                )
            finally:
                self.last_message.text = original_text
            p = f'{_t(KeyWord.DOWNLOAD_AND_UPLOAD_TASK)}{_t(KeyWord.CHANNEL)}:"{target_chat_id}",{_t(KeyWord.LINK)}:"{link}"。'
            console.log(p, style='#FF4689')
            log.info(p)

    async def forward_media_group(
            self,
            client: pyrogram.Client,
            group_messages: list,
            origin_chat_id: Union[str, int],
            target_chat_id: Union[str, int],
            target_link: str,
            storage_id: list,
            owner: Union[int, None] = None
    ):
        """Settle a media group; forward items individually if it contains filtered types to prevent the group forward from bypassing filter settings."""
        group_ids = sorted(m.id for m in group_messages)
        passed = [m for m in group_messages if self.check_type(m)]
        if passed and len(passed) != len(group_messages):
            # If the group contains filtered types, fall back to forwarding items individually; check_type in forward decides whether to forward or skip each item.
            for m in group_messages:
                await self.forward(
                    client=client,
                    message=m,
                    message_id=m.id,
                    origin_chat_id=origin_chat_id,
                    target_chat_id=target_chat_id,
                    target_link=target_link,
                    owner=owner
                )
                storage_id.append(m.id)
            return None
        await self.forward(
            client=client,
            message=group_messages[0],
            message_id=group_ids[0],
            origin_chat_id=origin_chat_id,
            target_chat_id=target_chat_id,
            target_link=target_link,
            media_group=group_ids,
            owner=owner
        )
        storage_id.extend(group_ids)

    async def get_forward_link_from_bot(
            self, client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> Union[dict, None]:
        meta: Union[dict, None] = await super().get_forward_link_from_bot(client, message)
        if meta is None:
            return None
        self.last_client: pyrogram.Client = client
        self.last_message: pyrogram.types.Message = message
        # Attribute the forward to its requester so follow-up notices and restricted-forward download-and-upload feedback go to that person.
        owner: Union[int, None] = message.from_user.id
        # Record the creator's display name so the web panel's "Notifications" section can show who created the task.
        NoticeHub.add_owner(owner=owner, user=message.from_user)
        origin_link: str = meta.get('origin_link')
        target_link: str = meta.get('target_link')
        start_id: int = meta.get('message_range')[0]
        end_id: int = meta.get('message_range')[1]
        last_message: Union[pyrogram.types.Message, None] = None
        loading = '🚛 Forwarding messages, please wait...'
        try:
            origin_meta: Union[dict, None] = await parse_link(
                client=self.app.client,
                link=origin_link
            )
            target_meta: Union[dict, None] = await parse_link(
                client=self.app.client,
                link=target_link
            )
            if not all([origin_meta, target_meta]):
                raise Exception('Invalid origin_link or target_link.')
            origin_chat_id = origin_meta.get('chat_id')
            target_chat_id = target_meta.get('chat_id')
            origin_chat: Union[pyrogram.types.Chat, None] = await get_chat_with_notify(
                user_client=self.app.client,
                bot_client=client,
                bot_message=message,
                chat_id=origin_chat_id,
                error_msg=f'⬇️ Source channel not found.\n{origin_link}'
            )
            target_chat: Union[pyrogram.types.Chat, None] = await get_chat_with_notify(
                user_client=self.app.client,
                bot_client=client,
                bot_message=message,
                chat_id=target_chat_id,
                error_msg=f'⬇️ Target channel not found.\n{target_link}'
            )
            if not all([origin_chat, target_chat]):
                return None
            my_id = await get_my_id(client)
            if target_chat.id == my_id:
                await client.send_message(
                    chat_id=message.from_user.id,
                    text='⚠️ This bot cannot forward messages to itself.',
                    reply_parameters=ReplyParameters(message_id=message.id),
                )
                return None
            storage_id: list = []
            last_message = await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                text=loading
            )
            # Media-group messages arrive consecutively from the source channel. Group them locally by media_group_id (grouped_id at the raw layer) to collect all IDs without an RPC, then forward the group and combine it into one log entry when the group ends.
            pending_group_id = None
            pending_messages: list = []
            async for i in self.app.client.get_chat_history(
                    chat_id=origin_chat.id,
                    offset_id=start_id,
                    max_id=end_id,
                    reverse=True
            ):
                try:
                    message_id = i.id
                    media_group_id = getattr(i, 'media_group_id', None)
                    if media_group_id is not None:
                        # Messages in a group arrive consecutively; collect all IDs, then forward the group when it ends.
                        if pending_group_id is None:
                            pending_group_id = media_group_id
                            pending_messages = [i]
                        elif media_group_id == pending_group_id:
                            pending_messages.append(i)
                        else:
                            # A new group should not appear before the current group ends, but settle the old group just in case.
                            group_messages = pending_messages
                            pending_group_id = media_group_id
                            pending_messages = [i]
                            await self.forward_media_group(
                                client=client,
                                group_messages=group_messages,
                                origin_chat_id=origin_chat_id,
                                target_chat_id=target_chat_id,
                                target_link=target_link,
                                storage_id=storage_id,
                                owner=owner
                            )
                        continue
                    # For a non-group message, settle any preceding media group that is still pending.
                    if pending_group_id is not None:
                        group_messages = pending_messages
                        pending_group_id = None
                        pending_messages = []
                        await self.forward_media_group(
                            client=client,
                            group_messages=group_messages,
                            origin_chat_id=origin_chat_id,
                            target_chat_id=target_chat_id,
                            target_link=target_link,
                            storage_id=storage_id,
                            owner=owner
                        )
                    await self.forward(
                        client=client,
                        message=i,
                        message_id=message_id,
                        origin_chat_id=origin_chat_id,
                        target_chat_id=target_chat_id,
                        target_link=target_link,
                        owner=owner
                    )
                    storage_id.append(message_id)
                except (ChatForwardsRestricted_400, ChatForwardsRestricted_406):
                    self.cd.data = {
                        'origin_link': origin_link,
                        'target_link': target_link,
                        'start_id': start_id,
                        'end_id': end_id
                    }
                    channel = '@' + origin_chat.username if isinstance(
                        getattr(origin_chat, 'username'),
                        str) else ''
                    if not self.gc.download_upload:
                        await client.send_message(
                            chat_id=message.from_user.id,
                            text=f'⚠️ Unable to forward\n`{origin_link}`\n{channel} has content protection enabled.',
                            parse_mode=ParseMode.MARKDOWN,
                            reply_parameters=ReplyParameters(message_id=message.id),
                            reply_markup=KeyboardButton.restrict_forward_button()
                        )
                        return None
                    original_text = self.last_message.text
                    try:
                        self.last_message.text = f'/download {origin_link} {start_id} {end_id}'
                        await self.get_download_link_from_bot(
                            client=self.last_client,
                            message=self.last_message,
                            with_upload={
                                'link': target_link,
                                'file_name': None,
                                'with_delete': self.gc.upload_delete,
                                'send_as_media_group': True,
                                'owner': owner
                            },
                            owner=owner
                        )
                    finally:
                        self.last_message.text = original_text
                    # Content protection: fall back to download-and-upload and replace the loading notice with a fallback notice instead of deleting it silently without feedback.
                    last_message = await self.safe_edit_message(
                        client=client, message=message,
                        last_message_id=last_message.id,
                        text=(
                            f'⚠️`{origin_link}`\n'
                            f'{channel} has content protection enabled. This task has fallen back to download-and-upload.\n'
                            f'(Download-and-upload tasks created with `/forward` do not apply the `[Forward settings]` type filters.)'
                        ),
                    )
                    break
                except Exception as e:
                    log.warning(
                        f'{_t(KeyWord.CHANNEL)}:"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:"{i.id}"'
                        f' -> '
                        f'{_t(KeyWord.CHANNEL)}:"{target_chat_id}",'
                        f'{_t(KeyWord.STATUS)}:{_t(KeyWord.FORWARD_FAILURE)},'
                        f'{_t(KeyWord.REASON)}:"{e}"')
                    await asyncio.create_task(
                        self.done_notice(
                            f'"{origin_chat_id}",{_t(KeyWord.MESSAGE_ID)}:{i.id}'
                            f' ➡️ '
                            f'"{target_chat_id}",{_t(KeyWord.FORWARD_FAILURE)}。'
                            f'\n(See the terminal for details.)',
                            requester=owner,
                            notice_type=NoticeType.FORWARD
                        )
                    )
            else:
                if pending_group_id is not None:
                    # When the loop ends normally, settle any trailing media group that has not yet been forwarded.
                    group_messages = pending_messages
                    try:
                        await self.forward_media_group(
                            client=client,
                            group_messages=group_messages,
                            origin_chat_id=origin_chat_id,
                            target_chat_id=target_chat_id,
                            target_link=target_link,
                            storage_id=storage_id,
                            owner=owner
                        )
                    except (ChatForwardsRestricted_400, ChatForwardsRestricted_406):
                        # If forwarding the trailing media group is restricted, fall back to downloading and uploading the whole group, as in the loop.
                        self.cd.data = {
                            'origin_link': origin_link,
                            'target_link': target_link,
                            'start_id': start_id,
                            'end_id': end_id
                        }
                        channel = '@' + origin_chat.username if isinstance(
                            getattr(origin_chat, 'username'), str) else ''
                        if not self.gc.download_upload:
                            await client.send_message(
                                chat_id=message.from_user.id,
                                text=f'⚠️ Unable to forward\n`{origin_link}`\n{channel} has content protection enabled.',
                                parse_mode=ParseMode.MARKDOWN,
                                reply_parameters=ReplyParameters(message_id=message.id),
                                reply_markup=KeyboardButton.restrict_forward_button()
                            )
                            return None
                        self.last_message.text = f'/download {origin_link} {start_id} {end_id}'
                        await self.get_download_link_from_bot(
                            client=self.last_client,
                            message=self.last_message,
                            with_upload={
                                'link': target_link,
                                'file_name': None,
                                'with_delete': self.gc.upload_delete,
                                'send_as_media_group': True
                            }
                        )
                        # Content protection: fall back to download-and-upload and replace the loading notice with a fallback notice instead of deleting it silently without feedback.
                        last_message = await self.safe_edit_message(
                            client=client, message=message,
                            last_message_id=last_message.id,
                            text=(
                                f'`{origin_link}`\n'
                                f'⚠️{channel} has content protection enabled. This task has fallen back to download-and-upload.\n'
                                f'(Download-and-upload tasks created with `/forward` do not apply the `[Forward settings]` type filters.)'
                            ),
                        )
                        return None
                if not storage_id:
                    last_message = await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text=safe_message('🌫️ No valid messages were found.')
                    )
                    return None
                invalid_id: list = []
                for i in range(start_id, end_id + 1):
                    if i not in storage_id:
                        invalid_id.append(i)
                if invalid_id:
                    if len(invalid_id) > Bot.MAX_BOT_NOTICE_ITEMS:
                        # Listing many missing items requires repeated edits or even resending the message, risking rate limits; report only the number skipped.
                        last_message = await self.safe_edit_message(
                            client=client,
                            message=message,
                            last_message_id=last_message.id,
                            text=safe_message(BotMessage.TOO_MANY_INVALID_FORWARD_MESSAGE.format(count=len(invalid_id)))
                        )
                    else:
                        last_message = await self.safe_edit_message(
                            client=client,
                            message=message,
                            last_message_id=last_message.id,
                            text=safe_message(BotMessage.INVALID)
                        )
                        invalid_chat = await format_chat_link(
                            link=origin_link,
                            client=self.app.client,
                            topic=origin_chat.is_forum
                        )
                        invalid_chat = invalid_chat if invalid_chat else 'Your Saved Messages'
                        invalid_text = '\n'.join(f'{invalid_chat}/{i}' for i in invalid_id)
                        await safe_delete_message(last_message) if len(invalid_text) >= 3969 else None
                        last_message = await self.safe_edit_message(
                            client=client,
                            message=message,
                            last_message_id=last_message.id,
                            text=safe_message(f'{last_message.text}\n{invalid_text}')
                        )
                direct_url: str = await format_chat_link(
                    link=target_link,
                    client=self.app.client,
                    topic=target_chat.is_forum
                )
                last_message = await self.safe_edit_message(
                    client=client,
                    message=message,
                    last_message_id=last_message.id,
                    text=safe_message(
                        f'{last_message.text.strip(loading)}\n🌟 Forwarding task completed.\n(If forwarding filters are configured, see the terminal for the forwarding log; it is not shown here.)'),
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    BotButton.CLICK_VIEW,
                                    url=direct_url
                                )
                            ]
                        ]
                    ) if direct_url else None
                )
        except AttributeError as e:
            log.exception(f'Error while forwarding, {_t(KeyWord.REASON)}: "{e}"')
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='⬇️ An error occurred.\n(See the terminal for details.)'
            )
        except (ValueError, KeyError, UsernameInvalid, ChatWriteForbidden):
            msg: str = ''
            if any('/c' in link for link in (origin_link, target_link)):
                msg = '(The logged-in account must be a member of private or topic-enabled source channels, and the target channel must allow uploads.)'
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ No valid links were found.\n' + msg
            )
        except Exception as e:
            log.exception(f'Error while forwarding, {_t(KeyWord.REASON)}: "{e}"')
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='⬇️ An error occurred.\n(See the terminal for details.)'
            )
        finally:
            if last_message and getattr(last_message, 'text', '') == loading:
                await safe_delete_message(last_message)

    async def cancel_listen(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            link: str,
            command: str,
            from_web: bool = False
    ):
        args: list = link.split()
        forward_emoji = ' ➡️ '
        named_link: str = link if len(args) == 1 else forward_emoji.join(args)
        if from_web:  # For removals initiated by the web panel, remove the listener directly without a second confirmation button.
            if command == '/listen_download':
                self.app.client.remove_handler(self.listen_download_chat.get(link))
                self.listen_download_chat.pop(link, None)
                p: str = f'Removed download listener for channel link "{link}".'
                log.info(f'{p} Current download listeners: {self.listen_download_chat}')
            else:
                self.app.client.remove_handler(self.listen_forward_chat.get(link))
                self.listen_forward_chat.pop(link, None)
                rule: str = ' -> '.join(args)
                p: str = f'Removed forwarding listener for rule "{rule}".'
                log.info(f'{p} Current forwarding listeners: {self.listen_forward_chat}')
            console.log(p, style='#FF4689')
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text=f'{named_link}',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            BotButton.ALREADY_REMOVE,
                            callback_data=BotCallbackText.NULL
                        )
                    ]
                ]
                )
            )
            return None
        if command == '/listen_forward':
            self.cd.data = {
                'link': link
            }
        await client.send_message(
            chat_id=message.from_user.id,
            reply_parameters=ReplyParameters(message_id=message.id),
            text=f'`{named_link}`\n🚛 Already on the monitoring list.',
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        BotButton.DROP,
                        callback_data=f'{BotCallbackText.REMOVE_LISTEN_DOWNLOAD} {link}' if command == '/listen_download' else BotCallbackText.REMOVE_LISTEN_FORWARD
                    )
                ]
            ]
            )
        )

    async def cancel_listen_from_web(
            self,
            kind: str,
            link: str
    ) -> dict:
        """Remove a registered download or forwarding listener at the web panel's request.

        The web panel has no inline button to click, so reuse the bot command: have the user client send the exact command used to register the listener.
        When the bot detects that the listener already exists, it removes it directly without sending a second confirmation button.

        Args:
            kind: Listener type: `download` for download monitoring or `forward` for forwarding monitoring.
            link: A channel link for download monitoring, or "source channel destination channel" for forwarding monitoring.

        Returns:
            dict: Whether removal succeeded in `status`; the failure reason is in `e_code`.
        """
        if not link:
            return {'status': False, 'e_code': 'The link to remove is missing.'}
        if not self.is_bot_running or self.bot is None:
            return {'status': False, 'e_code': 'The bot is not running, so the listener cannot be removed.'}
        if kind == 'download':
            if link not in self.listen_download_chat:
                return {'status': False, 'e_code': 'That download listener does not exist.'}
            text: str = f'/listen_download {link}'
        elif kind == 'forward':
            if link not in self.listen_forward_chat:
                return {'status': False, 'e_code': 'That forwarding listener does not exist.'}
            text: str = f'/listen_forward {link}'
        else:
            return {'status': False, 'e_code': 'Unknown listener type.'}
        self.web_remove_listen.add(text)  # Register first so the bot can identify the command as a web-panel removal request when it handles it.
        result = await self.send_message_to_bot(text=text)
        if isinstance(result, Exception) or result is None:
            self.web_remove_listen.discard(text)
            return {'status': False, 'e_code': f'Failed to send the removal command: "{result}"'}
        return {'status': True}

    async def on_listen(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        meta: Union[dict, None] = await super().on_listen(client, message)
        if meta is None:
            return None

        async def add_listen_chat(_link: str, _listen_chat: dict, _callback: Callable) -> bool:
            if _link not in _listen_chat:
                try:
                    chat = await self.user.get_chat(_link)
                    if chat.is_forum:
                        raise PeerIdInvalid
                    handler = MessageHandler(_callback, filters=pyrogram.filters.chat(chat.id))
                    _listen_chat[_link] = handler
                    self.user.add_handler(handler)
                    return True
                except PeerIdInvalid:
                    try:
                        link_meta: list = _link.split()
                        link_length: int = len(link_meta)
                        if link_length >= 1:  # v1.6.7: Fixed a ValueError while retrieving a link after add_listen_chat raised PeerIdInvalid.
                            l_link = link_meta[0]
                        else:
                            return False
                        m: dict = await parse_link(client=self.app.client, link=l_link)
                        topic_id = m.get('topic_id')
                        chat_id = m.get('chat_id')
                        if topic_id:
                            filters = pyrogram.filters.chat(
                                chat_id) & pyrogram.filters.topic(topic_id)
                        else:
                            filters = pyrogram.filters.chat(chat_id)
                        handler = MessageHandler(
                            _callback,
                            filters=filters
                        )
                        _listen_chat[_link] = handler
                        self.user.add_handler(handler)
                        return True
                    except ValueError as e:
                        await client.send_message(
                            chat_id=message.from_user.id,
                            reply_parameters=ReplyParameters(message_id=message.id),
                            link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                            text=f'⚠️ Unable to read\n`{_link}`\n(See the terminal for details.)'
                        )
                        log.error(f'Failed to parse channel "{_link}", {_t(KeyWord.REASON)}: "{e}"')
                        return False
                except Exception as e:
                    await client.send_message(
                        chat_id=message.from_user.id,
                        reply_parameters=ReplyParameters(message_id=message.id),
                        link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                        text=f'⚠️ Unable to read\n`{_link}`\n(See the terminal for details.)'
                    )
                    log.error(f'Error reading channel "{_link}", {_t(KeyWord.REASON)}: "{e}"')
                    return False
            else:
                text: str = f'{command} {_link}'
                from_web: bool = text in self.web_remove_listen
                if from_web:
                    self.web_remove_listen.discard(text)
                await self.cancel_listen(client, message, _link, command, from_web=from_web)
                return False

        links: list = meta.get('links')
        command: str = meta.get('command')
        if command == '/listen_download':
            last_message: Union[pyrogram.types.Message, None] = None
            for link in links:
                if await add_listen_chat(link, self.listen_download_chat, self.listen_download):
                    # Record the listener's creator so downloads triggered by it and their notices go to that person.
                    self.listen_download_owner[link] = message.from_user.id
                    # Record the creator's display name so the web panel's "Notifications" section can show who created the task.
                    NoticeHub.add_owner(owner=message.from_user.id, user=message.from_user)
                    _meta = await parse_link(client=self.app.client, link=link)
                    if isinstance(_meta, dict) and _meta.get('chat_id') is not None:
                        self.listen_download_chat_owner[_meta.get('chat_id')] = message.from_user.id
                    if not last_message:
                        last_message: Union[pyrogram.types.Message, str, None] = await client.send_message(
                            chat_id=message.from_user.id,
                            reply_parameters=ReplyParameters(message_id=message.id),
                            link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                            text=f'✅ Added to download monitoring:\n')
                    last_message: Union[pyrogram.types.Message, None] = await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text=safe_message(f'{last_message.text}\n{link}'),
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                BotButton.LOOKUP_LISTEN_INFO,
                                callback_data=BotCallbackText.LOOKUP_LISTEN_INFO
                            )
                        ]])
                    )
                    p = f'Added download listener for channel link "{link}".'
                    console.log(p, style='#FF4689')
                    log.info(f'{p} Current download listeners: {self.listen_download_chat}')
        elif command == '/listen_forward':
            listen_link, target_link = links
            if await add_listen_chat(f'{listen_link} {target_link}', self.listen_forward_chat, self.listen_forward):
                # Record the forwarding listener's creator so forwards triggered by it and their notices go to that person.
                self.listen_forward_owner[f'{listen_link} {target_link}'] = message.from_user.id
                # Record the creator's display name so the web panel's "Notifications" section can show who created the task.
                NoticeHub.add_owner(owner=message.from_user.id, user=message.from_user)
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                    text=f'✅ Added forwarding monitor:\n{listen_link} ➡️ {target_link}',
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    BotButton.LOOKUP_LISTEN_INFO,
                                    callback_data=BotCallbackText.LOOKUP_LISTEN_INFO
                                )
                            ]
                        ]
                    )
                )
                p = f'Added forwarding listener for rule "{listen_link} -> {target_link}".'
                console.log(p, style='#FF4689')
                log.info(f'{p} Current forwarding listeners: {self.listen_forward_chat}')

    async def listen_download(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        try:
            # Attribute the task to the person who created the listener so they receive the download-completion notice.
            owner = self.listen_download_chat_owner.get(getattr(getattr(message, 'chat', None), 'id', None))
            await self.create_download_task(message_ids=message.link, single_link=True, owner=owner)
        except Exception as e:
            log.exception(f'Error in download listener, {_t(KeyWord.REASON)}: "{e}"')

    def check_type(self, message: pyrogram.types.Message):
        for dtype, is_forward in self.gc.forward_type.items():
            if is_forward:
                result = getattr(message, dtype)
                if result:
                    return True
        return False

    async def listen_forward(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        try:
            link: str = message.link
            meta = await parse_link(client=self.app.client, link=link)
            listen_chat_id = meta.get('chat_id')
            for m in self.listen_forward_chat:
                listen_link, target_link = m.split()
                _listen_link_meta = await parse_link(
                    client=self.app.client,
                    link=listen_link
                )
                _target_link_meta = await parse_link(
                    client=self.app.client,
                    link=target_link
                )
                _listen_chat_id = _listen_link_meta.get('chat_id')
                _target_chat_id = _target_link_meta.get('chat_id')
                if listen_chat_id == _listen_chat_id:
                    try:
                        media_group_ids = await message.get_media_group()
                        if not media_group_ids:
                            raise ValueError
                        if (
                                not self.gc.forward_type.get('video') or
                                not self.gc.forward_type.get('photo')
                        ):
                            log.warning('Because photo or video forwarding is filtered, media groups will no longer be sent as groups.')
                            raise ValueError
                        if (
                                getattr(getattr(message, 'chat', None), 'is_creator', False) or
                                getattr(getattr(message, 'chat', None), 'is_admin', False)
                        ) and (
                                getattr(getattr(message, 'from_user', None), 'id', -1) ==
                                getattr(getattr(client, 'me', None), 'id', None)
                        ):
                            pass
                        elif (
                                getattr(getattr(message, 'chat', None), 'has_protected_content', False) or
                                getattr(getattr(message, 'sender_chat', None), 'has_protected_content', False) or
                                getattr(message, 'has_protected_content', False)
                        ):
                            raise ValueError
                        if not self.handle_media_groups.get(listen_chat_id):
                            self.handle_media_groups[listen_chat_id] = set()
                        if listen_chat_id in self.handle_media_groups and message.id not in self.handle_media_groups.get(
                                listen_chat_id):
                            ids: set = set()
                            for peer_message in media_group_ids:
                                peer_id = peer_message.id
                                ids.add(peer_id)
                            if ids:
                                old_ids: Union[None, set] = self.handle_media_groups.get(listen_chat_id)
                                if old_ids and isinstance(old_ids, set):
                                    old_ids.update(ids)
                                    self.handle_media_groups[listen_chat_id] = old_ids
                                else:
                                    self.handle_media_groups[listen_chat_id] = ids
                            await self.forward(
                                client=client,
                                message=message,
                                message_id=message.id,
                                origin_chat_id=_listen_chat_id,
                                target_chat_id=_target_chat_id,
                                target_link=target_link,
                                download_upload=False,
                                media_group=sorted(ids),
                                owner=self.listen_forward_owner.get(m)
                            )
                            break
                        break
                    except ValueError:
                        pass
                    await self.forward(
                        client=client,
                        message=message,
                        message_id=message.id,
                        origin_chat_id=_listen_chat_id,
                        target_chat_id=_target_chat_id,
                        target_link=target_link,
                        download_upload=True,
                        owner=self.listen_forward_owner.get(m)
                    )
        except (ValueError, KeyError, UsernameInvalid, ChatWriteForbidden) as e:
            log.error(
                f'Error in forwarding listener, {_t(KeyWord.REASON)}: {e}. The channel may have changed, for example, it may have been deleted, renamed, changed type, the account may lack permission to post in the destination, or it may have been removed from the channel.')
        except Exception as e:
            log.exception(f'Error in forwarding listener, {_t(KeyWord.REASON)}: "{e}"')

    async def handle_forwarded_media(
            self,
            user_client: pyrogram.Client,
            user_message: pyrogram.types.Message
    ):
        chat_id = user_message.from_user.id
        message_id = user_message.id
        # Record the creator's display name so the web panel's "Notifications" section can show who created the task.
        NoticeHub.add_owner(owner=chat_id, user=user_message.from_user)
        last_message = await self.bot.send_message(
            chat_id=chat_id,
            text=f'🔄 Processing forwarded message `{message_id}`...'
        )
        try:
            task = await self.create_download_task(
                message_ids=user_message,
                diy_download_type=[_ for _ in DownloadType()],
                single_link=True,
                owner=user_message.from_user.id
            )
            if task.get('status') == DownloadStatus.DOWNLOADING:
                await last_message.edit_text(text=f'✅ Download task `{message_id}` created.')
            else:
                error_msg = task.get('e_code', {}).get('error_msg', 'Unknown error.')
                await last_message.edit_text(text=f'❌ Unable to create download task `{message_id}`.\n{error_msg}')
        except Exception as e:
            log.error(f'Failed to get the original message, {_t(KeyWord.REASON)}: "{e}"')
            await last_message.edit_text(text=f'❌ Unable to create download task `{message_id}`.\n{e}')

    async def resume_download(
            self,
            message: pyrogram.types.Message,
            file_name: str,
            progress: Callable = None,
            progress_args: tuple = (),
            chunk_size: int = 1024 * 1024,
            compare_size: Union[int, None] = None,  # If not None, compare sizes to determine whether the file is complete.
            download_type: str = None
    ) -> str:
        temp_path = f'{file_name}.temp'
        if os.path.exists(file_name) and compare_size:
            local_file_size: int = get_file_size(file_path=file_name)
            if compare_file_size(a_size=local_file_size, b_size=compare_size):
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.RESUME)}:"{file_name}",'
                    f'{_t(KeyWord.STATUS)}:{_t(KeyWord.ALREADY_EXIST)}')
                return file_name
            else:
                result: str = safe_replace(origin_file=file_name, overwrite_file=temp_path).get('e_code')
                log.warning(result) if result is not None else None
                log.warning(
                    f'Incomplete file "{file_name}", '
                    f'Renamed it as a cache file: [{file_name}]({get_file_size(file_name)}) -> [{temp_path}]({compare_size}).')
        if os.path.exists(temp_path) and compare_size:
            local_file_size: int = get_file_size(file_path=temp_path)
            if compare_file_size(a_size=local_file_size, b_size=compare_size):
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.RESUME)}:"{temp_path}",'
                    f'{_t(KeyWord.STATUS)}:{_t(KeyWord.ALREADY_EXIST)}')
                result: str = safe_replace(origin_file=temp_path, overwrite_file=file_name).get('e_code')
                log.warning(result) if result is not None else None
                return file_name
            elif local_file_size > compare_size:
                safe_delete(temp_path)
                log.warning(
                    f'Invalid cache file "{temp_path}", '
                    f'Cleared it ({_t(KeyWord.ERROR_SIZE)}: {local_file_size} > {_t(KeyWord.ACTUAL_SIZE)}: {compare_size}).')
        downloaded = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0  # Get the number of bytes already downloaded.
        if downloaded == 0:
            mode = 'wb'
        else:
            mode = 'r+b'
            console.log(
                f'{_t(KeyWord.DOWNLOAD_TASK)}'
                f'{_t(KeyWord.RESUME)}:"{file_name}",'
                f'{_t(KeyWord.ERROR_SIZE)}:{MetaData.suitable_units_display(downloaded)}。')
        try:
            with open(file=temp_path, mode=mode) as f:
                skip_chunks: int = downloaded // chunk_size  # Calculate the number of chunks to skip.
                aligned_size: int = skip_chunks * chunk_size  # Align with the server offset unit (1 MiB), discarding any unaligned tail.
                if aligned_size != downloaded:
                    f.truncate(aligned_size)  # Truncate the unaligned tail to prevent an oversized file after resuming.
                    log.warning(
                        f'Cache file "{temp_path}" is not aligned to a chunk boundary; truncated from "{downloaded}" to "{aligned_size}".')
                    downloaded = aligned_size
                f.seek(aligned_size)
                log.info(
                    f'Processing "{temp_path}": skipping chunks "{downloaded}//{chunk_size}={skip_chunks}"; file pointer moved to "{downloaded}".')
                while True:
                    try:
                        async for chunk in self.app.client.stream_media(
                                message=message,
                                offset=skip_chunks,
                                download_type=download_type
                        ):
                            f.write(chunk)
                            downloaded += len(chunk)
                            progress(downloaded, *progress_args)
                        break
                    except AuthBytesInvalid as e:
                        log.warning(f'Provided file reference is invalid (possibly a transient issue), {_t(KeyWord.REASON)}: "{e}"')
                        break
                    except FileReferenceExpired as e:
                        try:
                            chat_id = message.chat.id
                            message_id = message.id
                            log.warning(
                                f'File reference for message "{message_id}" has expired; fetching the message again to refresh it. {_t(KeyWord.REASON)}: "{e}"')
                            message = await self.app.client.get_messages(chat_id=chat_id, message_ids=message_id)
                            log.info(f'Refreshed file reference for message "{message_id}".')
                            skip_chunks: int = downloaded // chunk_size
                            aligned_size: int = skip_chunks * chunk_size
                            if aligned_size != downloaded:
                                f.truncate(aligned_size)
                                log.warning(
                                    f'Cache file "{temp_path}" is not aligned to a chunk boundary; truncated from "{downloaded}" to "{aligned_size}".')
                                downloaded = aligned_size
                            f.seek(aligned_size)
                        except Exception as refresh_error:
                            log.error(f'Failed to refresh the file reference, {_t(KeyWord.REASON)}: "{refresh_error}"')
                            break
                    except (FloodWait, FloodPremiumWait) as e:
                        amount = e.value
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Downloads are being rate-limited; wait {amount} seconds before retrying.'
                        )
                        await asyncio.sleep(amount)
                        ConnectionStatus.leave_flood()
        except PermissionError as e:
            log.error(
                f'Could not open temporary file "{temp_path}" in mode "{mode}", {_t(KeyWord.REASON)}: "{e}"')
            raise
        if compare_size is None or compare_file_size(a_size=downloaded, b_size=compare_size):
            __cache_temp_size: int = os.path.getsize(temp_path) if os.path.exists(temp_path) else 0
            result: str = safe_replace(origin_file=temp_path, overwrite_file=file_name).get('e_code')
            log.warning(result) if result is not None else None
            log.info(
                f'Download complete for "{temp_path}"; renamed file: [{temp_path}]({__cache_temp_size}) -> [{file_name}]({compare_size})')
        return file_name

    def get_media_meta(self, message: pyrogram.types.Message, dtype) -> Dict[str, Union[int, str]]:
        """Get media metadata."""
        file_id: int = getattr(message, 'id')
        temp_file_path: str = self.app.get_temp_file_path(message, dtype)
        _sever_meta = getattr(message, dtype)
        sever_file_size: int = getattr(_sever_meta, 'file_size')
        file_name: str = split_path(temp_file_path).get('file_name')
        save_directory: str = os.path.join(self.env_save_directory(message), file_name)
        format_file_size: str = MetaData.suitable_units_display(sever_file_size)
        return {
            'file_id': file_id,
            'temp_file_path': temp_file_path,
            'sever_file_size': sever_file_size,
            'file_name': file_name,
            'save_directory': save_directory,
            'format_file_size': format_file_size
        }

    async def __download_scheduler(self) -> None:
        """Dispatch queued messages as download tasks, respecting the maximum concurrency limit."""
        while True:
            item: Union[dict, None] = None
            dispatched: bool = False
            # Do not dispatch new downloads while globally paused; wait until processing resumes.
            if self.app.is_paused:
                await self.pause_event.wait()
                continue
            try:
                while self.app.current_task_num < self.app.max_download_task:
                    item = DownloadTask.pick_pending()
                    if item is None:
                        break
                    task: DownloadTask = DownloadTask.get(item.get('link'))
                    message: pyrogram.types.Message = item.get('message')
                    # Mark this message as downloading to prevent concurrent tasks (such as a media group and one of its single-message tasks) from downloading it and racing.
                    dl_key = DownloadTask.download_key(message)
                    if dl_key is not None:
                        DownloadTask.DOWNLOADING_KEYS.add(dl_key)
                    task.set_item_status(message_id=message.id, status=DownloadStatus.DOWNLOADING)
                    await self.__add_task(
                        chat_id=item.get('chat_id'),
                        link_type=item.get('link_type'),
                        link=item.get('link'),
                        message=message,
                        retry=item.get('retry'),
                        with_upload=item.get('with_upload'),
                        diy_download_type=item.get('diy_download_type')
                    )
                    dispatched = True
            except asyncio.CancelledError:
                if item is not None:
                    task: DownloadTask = DownloadTask.get(item.get('link'))
                    task.set_item_status(message_id=item.get('message').id, status=DownloadStatus.PENDING)
                    dl_key = DownloadTask.download_key(item.get('message'))
                    if dl_key is not None:
                        DownloadTask.DOWNLOADING_KEYS.discard(dl_key)
                raise
            except Exception as e:
                log.exception(f'Error dispatching a task from the download scheduler, {_t(KeyWord.REASON)}: "{e}"')
                if item is not None:  # Remove failed tasks from the queue so the scheduler does not retry the same message repeatedly.
                    task: DownloadTask = DownloadTask.get(item.get('link'))
                    task.remove_item(message_id=item.get('message').id)
                    dl_key = DownloadTask.download_key(item.get('message'))
                    if dl_key is not None:
                        DownloadTask.DOWNLOADING_KEYS.discard(dl_key)
            if dispatched:
                continue
            self.event.clear()  # Wait for any task to free a download slot; check the queue again after a timeout to avoid spinning.
            try:
                await asyncio.wait_for(self.event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    async def __add_task(
            self,
            chat_id: Union[str, int],
            link_type: str,
            link: str,
            message: Union[pyrogram.types.Message, list],
            retry: dict,
            with_upload: Optional[dict] = None,
            diy_download_type: Optional[list] = None
    ) -> None:
        retry_count = retry.get('count')
        retry_id = retry.get('id')
        if isinstance(message, list):
            for _message in message:
                if retry_count != 0:
                    if _message.id == retry_id:
                        await self.__add_task(chat_id, link_type, link, _message, retry, with_upload, diy_download_type)
                        break
                else:
                    await self.__add_task(chat_id, link_type, link, _message, retry, with_upload, diy_download_type)
        else:
            _task = None
            task: DownloadTask = DownloadTask.get_or_create(link)
            download_type: list = diy_download_type if diy_download_type else self.app.download_type
            valid_dtype: str = get_message_dtype(message, download_type)  # Determine the message type from the download settings; whether live photos take priority depends on the configuration.
            if valid_dtype in download_type:
                # Create a task if the message type matches.
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.CHANNEL)}:"{chat_id}",'  # Channel name.
                    f'{_t(KeyWord.LINK)}:"{link}",'  # Link.
                    f'{_t(KeyWord.LINK_TYPE)}:{_t(link_type)}。'  # Link type.
                )
                task.set_item_status(message_id=message.id, status=DownloadStatus.DOWNLOADING)
                # If the save path contains the %MESSAGE_ID% placeholder, fetch and cache the media-group member IDs in advance.
                # collect_message_id checks for the placeholder itself and skips the request when the cache has a match.
                await collect_message_id(message, self.app.save_directory, self.media_group_ids_cache)
                file_id, temp_file_path, sever_file_size, file_name, save_directory, format_file_size = \
                    self.get_media_meta(
                        message=message,
                        dtype=valid_dtype).values()
                retry['id'] = file_id
                if is_file_duplicate(
                        save_directory=save_directory,
                        sever_file_size=sever_file_size
                ):  # Check whether it exists.
                    self.download_complete_callback(
                        sever_file_size=sever_file_size,
                        temp_file_path=temp_file_path,
                        link=link,
                        message=message,
                        file_name=file_name,
                        retry_count=retry_count,
                        file_id=file_id,
                        format_file_size=format_file_size,
                        task_id=None,
                        with_upload=with_upload,
                        diy_download_type=diy_download_type,
                        _future=save_directory
                    )
                else:
                    console.log(
                        f'{_t(KeyWord.DOWNLOAD_TASK)}'
                        f'{_t(KeyWord.FILE)}:"{file_name}",'
                        f'{_t(KeyWord.SIZE)}:{format_file_size},'
                        f'{_t(KeyWord.TYPE)}:{_t(self.app.get_file_type(message, file_name, DownloadStatus.DOWNLOADING))},'
                        f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.DOWNLOADING)}。'
                    )
                    ChatInfo.add(chat=getattr(message, 'chat', None), chat_id=chat_id)
                    task_id = self.pb.progress.add_task(
                        description='📥',
                        channel=str(chat_id),
                        filename=truncate_display_filename(file_name),
                        fullname=file_name,  # Keep the full filename for the web panel; filename is truncated to the terminal width for display only.
                        info=f'0.00B/{format_file_size}',
                        total=sever_file_size
                    )
                    task.update_member(
                        message_id=message.id,
                        status=DownloadStatus.DOWNLOADING,
                        name=file_name,
                        size=format_file_size,
                        size_byte=sever_file_size,
                        date=str(getattr(message, 'date', '') or '')[:10],
                        task_id=task_id
                    )
                    _task = self.loop.create_task(
                        self.resume_download(
                            message=message,
                            file_name=temp_file_path,
                            progress=self.pb.download,
                            progress_args=(
                                sever_file_size,
                                self.pb.progress,
                                task_id
                            ),
                            compare_size=sever_file_size,
                            download_type=valid_dtype
                        )
                    )
                    self.app.increase_task_num()
                    MetaData.print_current_task_num(
                        prompt=_t(KeyWord.CURRENT_DOWNLOAD_TASK),
                        num=self.app.current_task_num
                    )
                    _task.add_done_callback(
                        partial(
                            self.download_complete_callback,
                            sever_file_size,
                            temp_file_path,
                            link,
                            message,
                            file_name,
                            retry_count,
                            file_id,
                            format_file_size,
                            task_id,
                            with_upload,
                            diy_download_type
                        )
                    )
            else:
                task.remove_item(message_id=message.id)  # Remove ignored types from the queue immediately.
                task.member_num = max(task.member_num - 1, 0)  # Exclude unsupported or ignored types from the total so the remaining count for the link can reach zero.
                _error = 'Unsupported or ignored media type (cancelled).'
                _reason: str = _error.replace('。', '')
                try:
                    _, __, sever_file_size, file_name, ____, format_file_size = self.get_media_meta(
                        message=message,
                        dtype=valid_dtype
                    ).values()
                    if file_name:
                        console.log(
                            f'{_t(KeyWord.DOWNLOAD_TASK)}'
                            f'{_t(KeyWord.FILE)}:"{file_name}",'
                            f'{_t(KeyWord.SIZE)}:{format_file_size},'
                            f'{_t(KeyWord.TYPE)}:{_t(self.app.get_file_type(message, file_name, DownloadStatus.SKIP))},'
                            f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.SKIP)}。'
                        )
                        task.set_error(key=file_name, value=_reason)
                        task.update_member(
                            message_id=message.id,
                            status=DownloadStatus.SKIP,
                            name=file_name,
                            size=format_file_size,
                            size_byte=sever_file_size,
                            date=str(getattr(message, 'date', '') or '')[:10],
                            note=_reason
                        )
                    else:
                        raise Exception('Unsupported or ignored media type.')
                except Exception as e:
                    task.set_error(value=_reason)
                    task.update_member(message_id=message.id, status=DownloadStatus.SKIP, note=_reason)
                    console.log(
                        f'{_t(KeyWord.DOWNLOAD_TASK)}'
                        f'{_t(KeyWord.CHANNEL)}:"{chat_id}",'  # Channel name.
                        f'{_t(KeyWord.LINK)}:"{link}",'  # Link.
                        f'{_t(KeyWord.LINK_TYPE)}:{_error}'  # Link type.
                    )
                    log.info(
                        f'Skipped download "{link}": unsupported or ignored media type. {_t(KeyWord.REASON)}: "{str(e).replace("。", "")}"')
            self.queue.put_nowait(_task) if _task else None

    def __check_download_finish(
            self,
            message: pyrogram.types.Message,
            sever_file_size: int,
            temp_file_path: str,
            save_directory: str,
            with_move: bool = True
    ) -> bool:
        """Check whether the file has finished downloading."""
        temp_ext: str = '.temp'
        local_file_size: int = get_file_size(file_path=temp_file_path, temp_ext=temp_ext)
        format_local_size: str = MetaData.suitable_units_display(local_file_size)
        format_sever_size: str = MetaData.suitable_units_display(sever_file_size)
        _file_path: str = os.path.join(save_directory, split_path(temp_file_path).get('file_name'))
        file_path: str = _file_path[:-len(temp_ext)] if _file_path.endswith(temp_ext) else _file_path
        if compare_file_size(a_size=local_file_size, b_size=sever_file_size):
            if with_move:
                result: str = move_to_save_directory(
                    temp_file_path=temp_file_path,
                    save_directory=save_directory
                ).get('e_code')
                log.warning(result) if result is not None else None
            console.log(
                f'{_t(KeyWord.DOWNLOAD_TASK)}'
                f'{_t(KeyWord.FILE)}:"{file_path}",'
                f'{_t(KeyWord.SIZE)}:{format_local_size},'
                f'{_t(KeyWord.TYPE)}:{_t(self.app.get_file_type(message, temp_file_path, DownloadStatus.SUCCESS))},'
                f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.SUCCESS)}。',
            )
            return True
        console.log(
            f'{_t(KeyWord.DOWNLOAD_TASK)}'
            f'{_t(KeyWord.FILE)}:"{file_path}",'
            f'{_t(KeyWord.ERROR_SIZE)}:{format_local_size},'
            f'{_t(KeyWord.ACTUAL_SIZE)}:{format_sever_size},'
            f'{_t(KeyWord.TYPE)}:{_t(self.app.get_download_type(message, DownloadStatus.FAILURE))},'
            f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.FAILURE)}。'
        )
        return False

    @DownloadTask.on_complete
    def download_complete_callback(
            self,
            sever_file_size,
            temp_file_path,
            link,
            message,
            file_name,
            retry_count,
            file_id,
            format_file_size,
            task_id,
            with_upload,
            diy_download_type,
            _future
    ):
        # Release the message's reservation after the download finishes (success, skip, or failure), allowing other tasks to process it.
        dl_key = DownloadTask.download_key(message)
        if dl_key is not None:
            DownloadTask.DOWNLOADING_KEYS.discard(dl_key)
        download_task: Union[DownloadTask, None] = DownloadTask.get(link)
        if download_task is not None:
            download_task.remove_item(message_id=message.id)  # Processing is complete; remove it from the queue.
        if task_id is None:
            if retry_count == 0:
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.ALREADY_EXIST)}:"{_future}"'
                )
                console.log(
                    f'{_t(KeyWord.DOWNLOAD_TASK)}'
                    f'{_t(KeyWord.FILE)}:"{file_name}",'
                    f'{_t(KeyWord.SIZE)}:{format_file_size},'
                    f'{_t(KeyWord.TYPE)}:{_t(self.app.get_file_type(message, file_name, DownloadStatus.SKIP))},'
                    f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.SKIP)}。', style='#e6db74'
                )
                if download_task is not None:
                    download_task.update_member(  # The file already exists; mark it as skipped.
                        message_id=message.id,
                        status=DownloadStatus.SKIP,
                        name=file_name,
                        size=format_file_size,
                        size_byte=sever_file_size,
                        date=str(getattr(message, 'date', '') or '')[:10]
                    )
                self.storage_download(
                    message=message,
                    link=link,
                    file_name=file_name,
                    file_size=sever_file_size,
                    status=DownloadStatus.SKIP
                )
                if self.uploader:
                    if with_upload and isinstance(with_upload, dict):
                        try:
                            media_group = message.get_media_group()
                        except ValueError:
                            media_group = None
                        with_upload['message_id'] = message.id
                        with_upload['media_group'] = media_group
                        with_upload['caption'] = getattr(message, 'caption', None)
                        with_upload['caption_entities'] = getattr(message, 'caption_entities', None)
                        self.uploader.download_upload(
                            with_upload=with_upload,
                            file_path=os.path.join(self.env_save_directory(message), file_name)
                        )
        else:
            self.app.decrease_task_num()
            self.event.set()  # v1.3.4: Fixed an issue where retry downloads could get blocked.
            if self.__check_download_finish(
                    message=message,
                    sever_file_size=sever_file_size,
                    temp_file_path=temp_file_path,
                    save_directory=self.env_save_directory(message),
                    with_move=True
            ):
                try:
                    if SaveDirectoryPrefix.MESSAGE_ID_WITH_ENTITIES in self.app.save_directory:
                        save_message_entities(
                            message, self.env_save_directory(message), self.media_group_ids_cache)
                    MetaData.print_current_task_num(
                        prompt=_t(KeyWord.CURRENT_DOWNLOAD_TASK),
                        num=self.app.current_task_num
                    )
                    if download_task is not None:
                        download_task.clear_error(key=file_name)  # On success, including a successful retry, clear the file's previous failure record.
                        download_task.remove_fail(message_id=message.id)
                        download_task.update_member(
                            message_id=message.id,
                            status=DownloadStatus.SUCCESS,
                            name=file_name,
                            size=format_file_size,
                            size_byte=sever_file_size,
                            date=str(getattr(message, 'date', '') or '')[:10]
                        )
                    self.storage_download(
                        message=message,
                        link=link,
                        file_name=file_name,
                        file_size=sever_file_size,
                        status=DownloadStatus.SUCCESS
                    )
                    if self.uploader:
                        if with_upload and isinstance(with_upload, dict):
                            try:
                                media_group = message.get_media_group()
                            except ValueError:
                                media_group = None
                            with_upload['message_id'] = message.id
                            with_upload['media_group'] = media_group
                            with_upload['caption'] = getattr(message, 'caption', None)
                            with_upload['caption_entities'] = getattr(message, 'caption_entities', None)
                            self.uploader.download_upload(
                                with_upload=with_upload,
                                file_path=os.path.join(self.env_save_directory(message), file_name)
                            )
                finally:
                    self.queue.task_done()  # Always balance task_done(), even if finalization (saving, uploading, or updating status) fails, to prevent queue.join() from hanging.
            else:
                # Use the retry limit locked to the task (falling back to the current setting if download_task is None) so a configuration change does not fail an in-progress retry under a new limit.
                _max_retry = getattr(download_task, 'max_retry', None) or self.app.max_download_retries
                if retry_count < _max_retry:
                    retry_count += 1
                    # There is an event-loop tick between scheduling a retry with create_task and entering its body; during that gap the message is in neither DOWNLOADING_KEYS nor items.
                    # Register it before creating the task; create_download_task removes it after enqueueing.
                    DownloadTask.PENDING_ENQUEUE.add(link) if isinstance(link, str) else None
                    task = self.loop.create_task(
                        self.create_download_task(
                            message_ids=link if isinstance(link, str) else message,
                            retry={'id': file_id, 'count': retry_count},
                            with_upload=with_upload,
                            diy_download_type=diy_download_type
                        )
                    )
                    self.pending_retry_tasks.add(task)  # Register the pending retry so the main loop does not exit early.
                    task.add_done_callback(
                        partial(
                            self.__retry_call,
                            f'{_t(KeyWord.RE_DOWNLOAD)}:"{file_name}",'
                            f'{_t(KeyWord.RETRY_TIMES)}:{retry_count}/{_max_retry}。'
                        )
                    )
                else:
                    _error = f'(maximum retry count reached: {_max_retry}).'
                    console.log(
                        f'{_t(KeyWord.DOWNLOAD_TASK)}'
                        f'{_t(KeyWord.FILE)}:"{file_name}",'
                        f'{_t(KeyWord.SIZE)}:{format_file_size},'
                        f'{_t(KeyWord.TYPE)}:{_t(self.app.get_file_type(message, file_name, DownloadStatus.FAILURE))},'
                        f'{_t(KeyWord.STATUS)}:{_t(DownloadStatus.FAILURE)}'
                        f'{_error}'
                    )
                    download_task.set_error(key=file_name, value=_error.replace('。', ''))
                    download_task.add_fail(message_id=message.id)  # Retries are exhausted; record a final failure and exclude it from the queued count.
                    download_task.update_member(
                        message_id=message.id,
                        status=DownloadStatus.FAILURE,
                        name=file_name,
                        size=format_file_size,
                        size_byte=sever_file_size
                    )
                    self.storage_download(
                        message=message,
                        link=link,
                        file_name=file_name,
                        file_size=sever_file_size,
                        status=DownloadStatus.FAILURE,
                        error_msg=_error.replace('。', '')
                    )
                    self.bot_task_link.discard(link)
                    self.queue.task_done()
                link, file_name = None, None
            self.pb.progress.remove_task(task_id=task_id)
        return link, file_name

    async def download_chat(
            self,
            chat_id: str,
            callback_query: pyrogram.types.CallbackQuery
    ) -> Union[list, None]:
        async def _progress(
                _text: str,
                _reply_markup: InlineKeyboardMarkup
        ) -> Union[pyrogram.types.Message, None]:
            while True:
                try:
                    return await callback_query.message.edit_text(
                        text=_text,
                        reply_markup=_reply_markup
                    )
                except MessageNotModified:
                    return callback_query.message  # The text is already identical, a harmless no-op; treat it as success so the caller updates the timestamp instead of retrying in a busy loop.
                except (FloodWait, FloodPremiumWait) as _e:
                    _amount = _e.value
                    ConnectionStatus.enter_flood(
                        f'[{self.app.client.name}] Message edits are being rate-limited; wait {_amount} seconds before retrying.'
                    )
                    await asyncio.sleep(_amount)
                    ConnectionStatus.leave_flood()
                except Exception as _e:
                    log.info(
                        f'Failed to update the progress message during /download_chat; skipped this update. {_t(KeyWord.REASON)}: "{_e}"')
                    return

        origin_callback_query_text: str = callback_query.message.text
        _setup_text = f'{origin_callback_query_text}\n⏳ Searching for matching messages in this channel. Please wait.\n💡Ignore request-rate warnings in the terminal; they will not affect the download.'
        cq = await _progress(
            _text=_setup_text,
            _reply_markup=KeyboardButton.single_button(
                text=BotButton.RETRIEVE_MESSAGE,
                callback_data=BotCallbackText.NULL
            )
        )
        # If _progress returns None after a general exception, fall back to the intended setup text (not the message object) so callback_query_text does not revert to the original pre-edit text and later progress updates remain consistent.
        callback_query_text: str = cq.text if cq is not None else _setup_text
        last_displayed_count: int = -1  # Record the last displayed count; initialize to -1 to guarantee an initial update.
        search_icon: str = '🔎'  # Magnifying-glass icon for the search phase; switch between 🔎 and 🔍 only when the match count increases.
        last_update_time: float = 0  # Record the timestamp of the last update.
        update_interval: float = 5.0  # Base update interval in seconds; increase it by one step for each 100 items, up to 600 seconds.

        try:
            _filter = Filter()
            download_chat_filter: Union[dict, None] = None
            for i in self.download_chat_filter:
                if chat_id == i:
                    download_chat_filter = self.download_chat_filter.get(chat_id)
            if not download_chat_filter:
                return None
            if not isinstance(download_chat_filter, dict):
                return None
            # chat_id may be an integer (a private channel link parses to int) or a string (a public channel username); normalize the check by converting it to a string.
            chat_id: Union[str, int] = int(chat_id) if str(chat_id).startswith('-') else chat_id
            date_filter = download_chat_filter.get('date_range')
            start_date = date_filter.get('start_date')
            end_date = date_filter.get('end_date')
            download_type: dict = download_chat_filter.get('download_type')
            keyword_filter: dict = download_chat_filter.get('keyword', {})
            include_comment: bool = download_chat_filter.get('comment', False)
            # Use the person who clicked "Start download" as the owner (the callback-query sender is the command requester; they are the same in a private chat).
            # There is no need to store the owner separately in the filter configuration.
            owner = callback_query.from_user.id
            active_keywords = [k for k, v in keyword_filter.items() if v]
            diy_download_type: list = [_ for _ in DownloadType()]  # Shared by tasks created during search; construct it in advance to avoid defining it again in phase three.
            instant_album_groups: set = set()  # media_group_id values for groups whose tasks were created immediately; prevents duplicate creation in the post-iteration pass.
            links: list = []
            # Phase one: collect matching messages.
            messages_to_download = []
            matched_message_ids: set = set()  # Processed (chat_id, message_id) pairs, including members rejected by type/date filters, to avoid reprocessing after expanding a media group.
            media_group_matched: set = set()  # Expanded media_group_id values, to avoid repeated get_media_group calls for the same group.
            media_group_added: set = set()  # Selected media_group_id values; each group counts as one link so an album is not split into multiple links.
            album_members: dict = {}  # media_group_id -> group members that passed type/date filters individually; package them together without expanding via RPC when dispatching.
            matched_file_count: int = 0  # Number of selected media files; count each media-group member for search progress.
            media_group_thread_id: dict = {}  # ID of the first member (smallest message ID) with the media group's comments, used to search comments in phase two.
            extra_comment_ids: set = set()  # Non-group message IDs rejected by type filters but with comments to scan separately.
            downloaded_message_ids: set = set()  # (chat_id, message_id) pairs already in the download list, for quickly checking whether a message was filtered by type.
            search_icon = flip_emoji(search_icon, advanced=True, emoji=Emoji.SEARCH)  # Show search progress for the first time and switch the magnifying-glass icon once.
            await _progress(
                _text=f'{callback_query_text}\n'
                      f'{search_icon} Searching messages; 0 media items matched.',
                _reply_markup=KeyboardButton.single_button(
                    text=BotButton.RETRIEVE_MESSAGE,
                    callback_data=BotCallbackText.NULL)
            )
            async for message in self.app.client.get_chat_history(
                    chat_id=chat_id,
                    reverse=True
            ):
                # A few messages (for example, anonymous posts or missing from_id) cannot be resolved to a source chat, as with the None message.chat case in create_download_task; skip them to avoid aborting the search.
                if message.chat is None:
                    log.info(
                        f'Skipped a message whose channel could not be resolved during /download_chat (ID: {getattr(message, "id", "Unknown")}).')
                    continue
                msg_key = (message.chat.id, message.id)
                # Skip messages already processed, including members expanded from a media group, to avoid duplicates.
                if msg_key in matched_message_ids:
                    continue
                # A keyword/date match selects the message regardless of type: media-group members may have different types, and only the first caption carries keywords, so a match selects the whole group.
                if not (_filter.date_range(message, start_date, end_date) and
                        _filter.keyword_filter(message, active_keywords)):
                    continue
                # First apply the type filter to the message that matched the keyword.
                if _filter.dtype(message, download_type):
                    matched_file_count += 1
                    group_id = getattr(message, 'media_group_id', None)
                    if group_id is None:
                        messages_to_download.append(message)
                        downloaded_message_ids.add(msg_key)
                        # Create a download task as soon as a single message matches; dispatch it during the search instead of waiting for the full search to finish.
                        await self.create_download_task(
                            message_ids=message,
                            single_link=True,
                            diy_download_type=diy_download_type,
                            owner=owner,
                            album_chat_id=chat_id
                        )
                    else:
                        # For a media group, filter each member by type/date and add passing members to the group; the whole group counts as one link.
                        album_members.setdefault(group_id, []).append(message)
                        if group_id not in media_group_added:
                            media_group_added.add(group_id)
                            messages_to_download.append(message)
                            downloaded_message_ids.add(msg_key)
                matched_message_ids.add(msg_key)
                # For a matching media-group member, fetch the whole group and filter each member independently by type/date. This avoids depending on iteration order, losing the group when its first member is filtered, or skipping member type filters.
                # Without keywords or comment search, each group member matches during iteration, so no RPC expansion is needed.
                # Accumulate the first (smallest ID) member in the current window here; when searching comments, the absolute first member is needed as an anchor, so get_media_group below handles it instead.
                if getattr(message, 'media_group_id', None) and not active_keywords and not include_comment:
                    media_group_thread_id[message.media_group_id] = min(
                        media_group_thread_id.get(message.media_group_id, message.id),
                        message.id
                    )
                if message.media_group_id and message.media_group_id not in media_group_matched:
                    # Expand the group via RPC only when keywords are active (the matched member may not be first) or comments are included (the absolute first member is needed as the comment anchor); otherwise use the fast iteration path below.
                    if active_keywords or include_comment:
                        while True:
                            try:
                                group_members = await message.get_media_group()
                                break
                            except (ValueError, AttributeError, MsgIdInvalid):
                                group_members = []
                                break
                            except (FloodWait, FloodPremiumWait) as e:
                                amount = e.value
                                ConnectionStatus.enter_flood(
                                    f'[{self.app.client.name}] Media group message requests are being rate-limited; wait {amount} seconds before retrying.'
                                )
                                await asyncio.sleep(amount)
                                ConnectionStatus.leave_flood()
                        if group_members:
                            # Mark the group as processed only after a successful fetch; on failure, leave it unmarked so another matching member can retry.
                            media_group_matched.add(message.media_group_id)
                            # Record the ID of the first media-group member (smallest message ID), which owns the comments; phase two uses it to search the comment thread.
                            media_group_thread_id[message.media_group_id] = min(
                                m.id for m in group_members
                            )
                        else:
                            # The group could not be fetched (for example, the message expired or has no comments), so the group cannot be completed beyond the matching first member; log this to avoid silent loss.
                            log.warning(
                                f'Failed to get a media group during /download_chat (message ID: {message.id}); other items in the group may not be downloaded.')
                        for member in group_members:
                            # As above, a media-group member may not resolve to a chat; skip it to avoid aborting the search.
                            if member.chat is None:
                                log.info(
                                    f'Skipped a media group member whose channel could not be resolved during /download_chat (ID: {getattr(member, "id", "Unknown")}).')
                                continue
                            member_key = (member.chat.id, member.id)
                            if member_key in matched_message_ids:
                                continue
                            # Filter group members individually by type/date (the group already matched the keyword) and download only those that pass.
                            if _filter.date_range(
                                    member,
                                    start_date,
                                    end_date
                            ) and _filter.dtype(
                                member,
                                download_type
                            ):
                                matched_file_count += 1
                                # As above, filter each member by type/date and add passing members to the group; the whole group counts as one link.
                                member_group_id = getattr(member, 'media_group_id', None)
                                if member_group_id is None:
                                    messages_to_download.append(member)
                                else:
                                    album_members.setdefault(member_group_id, []).append(member)
                                    if member_group_id not in media_group_added:
                                        media_group_added.add(member_group_id)
                                        messages_to_download.append(member)
                            matched_message_ids.add(member_key)
                        # Slow-path media groups: after RPC expansion and individual filtering, album_members contains the final download list; create a group task immediately.
                        # If expansion fails (group_members is empty), defer to the post-iteration fallback so a successful retry does not create a duplicate task.
                        if group_members and message.media_group_id not in instant_album_groups:
                            instant_group_members = album_members.get(message.media_group_id)
                            if instant_group_members:
                                instant_album_groups.add(message.media_group_id)
                                await self.create_download_task(
                                    message_ids=instant_group_members[0],
                                    single_link=True,
                                    diy_download_type=diy_download_type,
                                    owner=owner,
                                    album_members=instant_group_members,
                                    album_chat_id=chat_id
                                )
                    else:
                        # Without keywords, iteration finds every group member; no RPC expansion is needed, so only mark the group as processed.
                        media_group_matched.add(message.media_group_id)
                # Comment search is independent of the message's type: scan comments even when the message's type is disabled and it is not in the download list.
                # Record only messages known to have comments to avoid unnecessary RPCs.
                # Use the raw Message.replies field (MessageReplies.replies is the comment count), available in the get_chat_history response without another RPC. Media groups are handled by their first member, so skip them here.
                if include_comment and not getattr(message, 'media_group_id', None):
                    if msg_key not in downloaded_message_ids:
                        _raw = getattr(message, 'raw', None)
                        _rep = getattr(_raw, 'replies', None) if _raw is not None else None
                        if _rep is not None and getattr(_rep, 'replies', 0) > 0:
                            extra_comment_ids.add(message.id)
                # Throttle updates by time to avoid frequent API calls.
                current_time = asyncio.get_event_loop().time()
                current_count = matched_file_count  # Show the actual number of selected media files, counting each media-group member.
                # Searches take longer as the match count grows; increase the edit interval by one step for every 100 items to reduce FloodWait risk on long-running messages.
                count_scale: int = max(1, (current_count + 99) // 100)
                if current_time - last_update_time >= min(update_interval * count_scale, 600.0):
                    search_icon = flip_emoji(
                        search_icon,
                        advanced=current_count > last_displayed_count,
                        emoji=Emoji.SEARCH
                    )
                    await _progress(
                        _text=f'{callback_query_text}\n'
                              f'{search_icon} Searching messages; {current_count} media items matched.',
                        _reply_markup=KeyboardButton.single_button(
                            text=BotButton.RETRIEVE_MESSAGE,
                            callback_data=BotCallbackText.NULL)
                    )
                    last_displayed_count = current_count
                    last_update_time = current_time
            # Ensure the final update shows the correct message count.
            final_count = matched_file_count
            if final_count != last_displayed_count:
                search_icon = flip_emoji(
                    search_icon,
                    advanced=final_count > last_displayed_count,
                    emoji=Emoji.SEARCH
                )
                await _progress(
                    _text=f'{callback_query_text}\n'
                          f'{search_icon} Searching messages; {final_count} media items matched.',
                    _reply_markup=KeyboardButton.single_button(
                        text=BotButton.RETRIEVE_MESSAGE,
                        callback_data=BotCallbackText.NULL)
                )
            if not messages_to_download:
                await _progress(
                    _text=f'{callback_query.message.text}\n'
                          '❎ No matching messages were found.',
                    _reply_markup=KeyboardButton.single_button(
                        text=BotButton.TASK_CANCEL,
                        callback_data=BotCallbackText.NULL
                    )

                )
                return None
            # Fast-path media groups (no keywords and no comment search): members are added during iteration, so album_members is complete only afterward; create those tasks here.
            # This also handles groups whose slow-path expansion failed; skip groups already created immediately to avoid duplicates.
            for group_id in media_group_added:
                if group_id in instant_album_groups:
                    continue
                pending_group_members = album_members.get(group_id)
                if pending_group_members:
                    instant_album_groups.add(group_id)
                    await self.create_download_task(
                        message_ids=pending_group_members[0],
                        single_link=True,
                        diy_download_type=diy_download_type,
                        owner=owner,
                        album_members=pending_group_members,
                        album_chat_id=chat_id
                    )
            message_count: int = len(messages_to_download)
            last_displayed_comment_count: int = -1  # Record the last displayed comment count; initialize to -1 to guarantee an initial update.
            last_comment_update_time: float = 0  # Record the timestamp of the last comment update.
            processed_message_count: int = 0  # Record the number of messages processed.
            comment_fetched_groups: set = set()  # Media groups whose comments have been searched, to avoid calling get_discussion_replies for every member of the same group.
            # Phase two: process matching messages and retrieve their comments.
            if include_comment:
                search_icon = flip_emoji(search_icon, advanced=True, emoji=Emoji.SEARCH)  # Show comment-search progress for the first time and switch the magnifying-glass icon once.
                await _progress(
                    _text=f'{callback_query_text}\n'
                          f'{search_icon} Searching comments; 0 messages matched.',
                    _reply_markup=KeyboardButton.single_button(
                        text=BotButton.RETRIEVE_COMMENT,
                        callback_data=BotCallbackText.NULL)
                )
            # Use the link's index in links as the key; Message objects cannot be used because pyrogram.Object explicitly sets __hash__ = None.
            group_members_by_index: dict = {}
            for message in messages_to_download:
                message_link = message.link if message.link else message
                group_id = getattr(message, 'media_group_id', None)
                if group_id is not None and group_id in album_members:
                    group_members_by_index[len(links)] = album_members[group_id]
                links.append(message_link)
                processed_message_count += 1
                if not include_comment:
                    continue
                # Search comments only for the first media-group member: other members have no separate comment thread, so the call would raise the already-caught MsgIdInvalid, waste an RPC, and risk duplicate comment records.
                # The thread belongs to the first group member (smallest message ID), not the current member; use the first-member ID recorded during expansion so comments are not missed if that member's type was filtered out.
                thread_id = message.id
                if getattr(message, 'media_group_id', None):
                    if message.media_group_id in comment_fetched_groups:
                        continue
                    comment_fetched_groups.add(message.media_group_id)
                    thread_id = media_group_thread_id.get(message.media_group_id, message.id)
                # Check for and fetch comments. links_mark stores the link count before this search; on FloodWait, roll back later comments to avoid duplicate records.
                links_mark = len(links)
                while True:
                    try:
                        async for comment in self.app.client.get_discussion_replies(
                                chat_id=chat_id,
                                message_id=thread_id
                        ):
                            # Filter comment media by the user's download_type setting, but do not apply a specific time filter.
                            if not _filter.dtype(comment, download_type):
                                continue
                            comment_link = comment.link if comment.link else comment
                            links.append(comment_link)
                            # Throttle updates by time to avoid frequent API calls.
                            current_time = asyncio.get_event_loop().time()
                            # Calculate the comment count as total links minus processed messages.
                            current_comment_count = len(links) - processed_message_count
                            # Searches take longer as more comments match; increase the edit interval by one step for every 100 items to reduce FloodWait risk on long-running messages.
                            count_scale: int = max(1, (current_comment_count + 99) // 100)
                            if current_time - last_comment_update_time >= min(update_interval * count_scale, 600.0):
                                search_icon = flip_emoji(
                                    search_icon,
                                    advanced=current_comment_count > last_displayed_comment_count,
                                    emoji=Emoji.SEARCH
                                )
                                await _progress(
                                    _text=f'{callback_query_text}\n'
                                          f'{search_icon} Searching comments; {current_comment_count} messages matched.',
                                    _reply_markup=KeyboardButton.single_button(
                                        text=BotButton.RETRIEVE_COMMENT,
                                        callback_data=BotCallbackText.NULL)
                                )
                                last_displayed_comment_count = current_comment_count
                                last_comment_update_time = current_time
                        break
                    except (ValueError, AttributeError, MsgIdInvalid):
                        break  # Skip messages with no comment thread or an invalid message ID.
                    except (FloodWait, FloodPremiumWait) as e:
                        amount = e.value
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Comment message requests are being rate-limited; wait {amount} seconds before retrying.'
                        )
                        await asyncio.sleep(amount)
                        ConnectionStatus.leave_flood()
                        del links[links_mark:]  # Roll back comments collected during this attempt so they can be recollected on retry.
            # Scan messages filtered out by type but with comments (for example, videos are disabled but their comment threads contain images).
            if include_comment:
                for source_id in extra_comment_ids:
                    # links_mark stores the link count before this search; on FloodWait, roll back comments added after it to avoid duplicate records.
                    links_mark = len(links)
                    while True:
                        try:
                            async for comment in self.app.client.get_discussion_replies(
                                    chat_id=chat_id,
                                    message_id=source_id
                            ):
                                # Filter comment media by the user's download_type setting, but do not apply a specific time filter.
                                if not _filter.dtype(comment, download_type):
                                    continue
                                comment_link = comment.link if comment.link else comment
                                links.append(comment_link)
                                # Throttle updates by time to avoid frequent API calls.
                                current_time = asyncio.get_event_loop().time()
                                # Calculate the comment count as total links minus processed messages.
                                current_comment_count = len(links) - processed_message_count
                                # Searches take longer as more comments match; increase the edit interval by one step for every 100 items to reduce FloodWait risk on long-running messages.
                                count_scale: int = max(1, (current_comment_count + 99) // 100)
                                if current_time - last_comment_update_time >= min(update_interval * count_scale, 600.0):
                                    search_icon = flip_emoji(
                                        search_icon,
                                        advanced=current_comment_count > last_displayed_comment_count,
                                        emoji=Emoji.SEARCH
                                    )
                                    await _progress(
                                        _text=f'{callback_query_text}\n'
                                              f'{search_icon} Searching comments; {current_comment_count} messages matched.',
                                        _reply_markup=KeyboardButton.single_button(
                                            text=BotButton.RETRIEVE_COMMENT,
                                            callback_data=BotCallbackText.NULL)
                                    )
                                    last_displayed_comment_count = current_comment_count
                                    last_comment_update_time = current_time
                            break
                        except (ValueError, AttributeError, MsgIdInvalid):
                            break  # Skip messages with no comment thread or an invalid message ID.
                        except (FloodWait, FloodPremiumWait) as e:
                            amount = e.value
                            ConnectionStatus.enter_flood(
                                f'[{self.app.client.name}] Comment message requests are being rate-limited; wait {amount} seconds before retrying.'
                            )
                            await asyncio.sleep(amount)
                            ConnectionStatus.leave_flood()
                            del links[links_mark:]  # Roll back comments collected during this attempt so they can be recollected on retry.
            # Ensure the final update shows the correct comment count.
            if include_comment:
                final_comment_count = len(links) - message_count
                if final_comment_count != last_displayed_comment_count:
                    search_icon = flip_emoji(
                        search_icon,
                        advanced=final_comment_count > last_displayed_comment_count,
                        emoji=Emoji.SEARCH
                    )
                    await _progress(
                        _text=f'{callback_query_text}\n'
                              f'{search_icon}Searching comments; {final_comment_count} messages matched.',
                        _reply_markup=KeyboardButton.single_button(
                            text=BotButton.RETRIEVE_COMMENT,
                            callback_data=BotCallbackText.NULL)
                    )
            comment_count: int = (len(links) - message_count) if include_comment else 0
            total_count: int = message_count + comment_count
            # Message tasks were created during search; start from the message count here and assign only comment tasks.
            assigned_count: int = message_count
            last_progress_update_time: float = 0  # Record the timestamp of the last task-assignment progress update.
            sandglass: str = '⏳'  # Current hourglass icon; switch it only when assignment progress increases, avoiding pointless frequent changes.
            last_assigned_count: int = -1  # Record the assigned count at the last edit to determine whether progress has increased.
            for index, link in enumerate(links):
                # Message tasks (the first message_count links) were created immediately in phase one; skip them and create tasks only for comments.
                if index < message_count:
                    continue
                if assigned_count == total_count:
                    reply_markup = KeyboardButton.single_button(
                        text=BotButton.TASK_ASSIGN,
                        callback_data=BotCallbackText.NULL
                    )
                else:
                    reply_markup = KeyboardButton.single_button(
                        text=BotButton.ASSIGNING_TASK,
                        callback_data=BotCallbackText.NULL
                    )

                # Throttle task-assignment progress updates by time.
                current_time = asyncio.get_event_loop().time()
                # Assignment takes longer as more tasks are added; increase the edit interval by one step for every 100 items to reduce FloodWait risk on long-running messages.
                count_scale: int = max(1, (assigned_count + 99) // 100)
                if current_time - last_progress_update_time >= min(update_interval * count_scale, 600.0):
                    # Switch the hourglass only when the assigned count has increased since the last edit; otherwise keep the current icon.
                    sandglass = flip_emoji(
                        sandglass,
                        advanced=assigned_count > last_assigned_count,
                        emoji=Emoji.HOURGLASS
                    )
                    last_assigned_count = assigned_count
                    if await _progress(
                            _text=f'{origin_callback_query_text}\n'
                                  f'🔎 Matched messages: {message_count}; comments: {comment_count}; total: {total_count}.\n'
                                  f'⭐️[{assigned_count}/{total_count}] Assigning downloads...\n'
                                  f'{sandglass}{self.pb.bot(assigned_count, total_count)}',
                            _reply_markup=reply_markup
                    ) is not None:
                        last_progress_update_time = current_time
                await self.create_download_task(
                    message_ids=link,
                    single_link=True,
                    diy_download_type=diy_download_type,
                    owner=owner,
                    album_members=group_members_by_index.get(index),  # Pass the pre-filtered members for a media group so they are packaged together.
                    album_chat_id=chat_id
                )
                assigned_count += 1
            # Track the actual completion of queued tasks in the background, refreshing the inline-keyboard progress bar until this run finishes.
            # All tasks are queued by this point; tracker exceptions are logged only and never propagated, so they cannot affect downloads.
            # The command coroutine does not wait here; the background coroutine keeps the bot message reference and continues editing the progress message.
            tracker: asyncio.Task = asyncio.create_task(self.track_download_chat_progress(
                links=links,
                bot_message=callback_query.message,
                base_text=origin_callback_query_text,
                message_count=message_count,
                comment_count=comment_count,
                matched_file_count=matched_file_count,
                total_count=total_count
            ))
            self.chat_progress_trackers.add(tracker)
            tracker.add_done_callback(self.chat_progress_trackers.discard)
            return links
        except Exception as e:
            log.error(
                f'{_t(KeyWord.CHANNEL)}: "{chat_id}"; unable to download. {_t(KeyWord.REASON)}: "{e}"',
                exc_info=True
            )
            # Send a new failure notice instead of overwriting the original menu, preserving its "Run | Cancel task" buttons for retrying or canceling.
            asyncio.create_task(callback_query.message.reply_text(
                text=f'⚠️ Unable to start the channel download because "{e}".\n'
                     f'Retry or cancel the task from the menu above.'
            ))

    async def track_download_chat_progress(
            self,
            links: list,
            bot_message: pyrogram.types.Message,
            base_text: str,
            message_count: int,
            comment_count: int,
            matched_file_count: int,
            total_count: int
    ) -> None:
        """Track the actual completion of queued /download_chat tasks in the background and keep the inline-keyboard progress bar updated.

        Progress is based on task-member states (member_info): completed, failed, and skipped are terminal states, while retries reset a member to pending.
        This naturally keeps progress incomplete while work remains in the queue; do not use the member_num/complete_num ratio because retries inflate member_num and progress would never reach 100%.
        This coroutine runs independently; any exception is logged before it exits and is never propagated or allowed to affect queued downloads.
        """
        # Match the keys registered in TASKS by create_download_task: keep string links unchanged; for Message objects (queued as objects only when link is empty), use their link or ID.
        # Deduplicate while preserving order to avoid counting the same key more than once.
        task_keys: list = []
        for _link in links:
            if isinstance(_link, pyrogram.types.Message):
                task_keys.append(str(_link.link if getattr(_link, 'link', None) else _link.id))
            else:
                task_keys.append(str(_link))
        task_keys = list(dict.fromkeys(task_keys))
        last_update_time: float = 0
        update_interval: float = 5.0  # Base update interval in seconds; scale it by the number of concurrent trackers and total messages.
        edit_fail_count: int = 0  # Count consecutive edit failures; stop tracking when the limit is exceeded because the message is likely invalid.
        sandglass: str = '⏳'  # Current hourglass icon; switch it only when completion progress increases, avoiding pointless frequent changes.
        last_done: int = 0  # Record the completed count at the last edit; initialize to 0 so the first frame with done=0 does not incorrectly switch from 0 > -1 to ⌛.
        while True:
            try:
                total: int = 0
                done: int = 0
                for key in task_keys:
                    task: Union[DownloadTask, None] = DownloadTask.get(key)
                    if task is None:  # The task was cleared (for example, the whole link was removed); treat it as finished.
                        continue
                    for member in task.member_info.values():
                        total += 1
                        if member.get('state') not in (DownloadStatus.PENDING, DownloadStatus.DOWNLOADING):
                            done += 1
                finished: bool = total == 0 or done >= total
                # Larger message counts take longer to download; increase the edit interval by one step for every 100 actual members to reduce FloodWait risk on long-running messages.
                count_scale: int = max(1, (total + 99) // 100)
                interval: float = min(
                    safe_length(self.chat_progress_trackers, default=1) * update_interval * count_scale,
                    600.0
                )
                current_time = asyncio.get_event_loop().time()
                if finished or current_time - last_update_time >= interval:
                    if total == 0:
                        progress_text: str = '⭐️ This download run has ended (the task was cleared or canceled).'
                    else:
                        # Switch the hourglass only when the completed count has increased since the last edit; otherwise keep the current icon.
                        sandglass = flip_emoji(sandglass, advanced=done > last_done, emoji=Emoji.HOURGLASS)
                        last_done = done
                        progress_text: str = (
                            f'⭐️[{done}/{total}] Download task {"completed" if finished else "in progress"}.\n'
                            f'{sandglass}{self.pb.bot(done, total)}'
                        )
                    try:
                        await bot_message.edit_text(
                            text=f'{base_text}\n'
                                 f'🔎 Matching messages: {message_count} (media files: {matched_file_count}); '
                                 f'comments: {comment_count}; total messages: {total_count}.\n'
                                 f'{progress_text}',
                            reply_markup=KeyboardButton.single_button(
                                text=BotButton.DOWNLOAD_TASK_DONE if finished else BotButton.DOWNLOAD_TASK_DOING,
                                callback_data=BotCallbackText.NULL
                            )
                        )
                    except MessageNotModified:
                        last_update_time = current_time  # The text is already identical, a harmless no-op; treat it as success to avoid a busy loop.
                    except (FloodWait, FloodPremiumWait) as _e:
                        ConnectionStatus.enter_flood(
                            f'[{self.app.client.name}] Message edits are being rate-limited; wait {_e.value} seconds before retrying.'
                        )
                        await asyncio.sleep(_e.value)
                        ConnectionStatus.leave_flood()
                        continue  # Keep the timestamp unchanged and try the edit again in the next iteration.
                    except Exception as _e:
                        # Log edit failures (for example, a deleted message or missing permissions) only; progress display is optional and must never affect downloads.
                        edit_fail_count += 1
                        log.info(
                            f'Failed to update download progress during /download_chat; skipped this update. '
                            f'{_t(KeyWord.REASON)}:"{_e}"')
                        if edit_fail_count >= 5:
                            log.warning('Stopped tracking after repeated failures to update /download_chat progress; downloads are unaffected.')
                            return
                    else:
                        last_update_time = current_time
                        edit_fail_count = 0
                if finished:
                    return
                await asyncio.sleep(update_interval)  # Use a fixed base interval rather than a dynamic one so the finished-state check runs every second.
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Fallback: log and exit silently if the tracking logic itself fails; never propagate the error or affect downloads.
                log.warning(
                    f'Unexpected error while tracking /download_chat progress; stopped tracking (downloads are unaffected). '
                    f'{_t(KeyWord.REASON)}:"{e}"'
                )
                return

    @DownloadTask.on_create_task
    async def create_download_task(
            self,
            message_ids: Union[pyrogram.types.Message, str],
            retry: Union[dict, None] = None,
            single_link: bool = False,
            with_upload: Union[dict, None] = None,
            diy_download_type: Optional[list] = None,
            owner: Union[int, None] = None,
            album_members: Optional[list] = None,
            album_chat_id: Optional[Union[int, str]] = None
    ) -> dict:
        retry = retry if retry else {'id': -1, 'count': 0}
        diy_download_type = [_ for _ in DownloadType()] if with_upload else diy_download_type
        # Message objects are unhashable (pyrogram.Object disables __hash__), so only link strings can be used as registration keys.
        enqueue_key: Union[str, None] = message_ids if isinstance(message_ids, str) else None
        try:
            if enqueue_key:
                # The link is not queued until parsing (including RPCs) finishes; register it so the uploader's media-group poller can check whether members are still awaiting enqueueing.
                DownloadTask.PENDING_ENQUEUE.add(enqueue_key)
            if album_members:
                # Media groups from download_chat: each member already passed type/date filtering during search, so package the group directly.
                # Do not expand the group via RPC again (avoids losing the group if expansion fails) or filter it again during download
                # (avoids inconsistencies with the search phase, such as expired dates or live-photo type detection).
                _first = album_members[0]
                meta: dict = {
                    'link_type': LinkType.GROUP if len(album_members) > 1 else LinkType.SINGLE,
                    # Prefer the known channel ID supplied by the caller: message.chat may be None for some messages, and accessing .chat.id would raise AttributeError.
                    'chat_id': album_chat_id if album_chat_id is not None
                    else getattr(getattr(_first, 'chat', None), 'id', None),
                    'message': album_members,
                    'member_num': len(album_members)
                }
                link = _first.link if _first.link else _first.id
            elif isinstance(message_ids, pyrogram.types.Message):
                chat_id = message_ids.chat.id
                meta: dict = {
                    'link_type': LinkType.SINGLE,
                    'chat_id': chat_id,
                    'message': message_ids,
                    'member_num': 1
                }
                link = message_ids.link if message_ids.link else message_ids.id
            else:
                meta: dict = await get_message_by_link(
                    client=self.app.client,
                    link=message_ids,
                    single_link=single_link
                )
                link = message_ids

            link_type, chat_id, message, member_num = meta.values()
            if str(chat_id) in ('me', 'self'):
                chat_id = self.my_id or chat_id  # Normalize me/self.
            task: DownloadTask = DownloadTask.get_or_create(link)
            # Lock the owner when creating the task and refresh it to the current requester on every request,
            # so a later user downloading the same link does not inherit the first user's ownership and receive the wrong notices.
            if owner is not None:
                task.owner = owner
            task.link_type = link_type
            task.chat_id = chat_id
            # Retries reparse the link (expanding media groups and inflating member_num); overwriting it would keep member_num above complete_num
            # and prevent the "Download complete" notice from firing, so set it only on the initial fetch, not on retries.
            if retry.get('count', 0) == 0:
                task.member_num = member_num
            # Lock the retry limit when creating a task. Retries for the same link reuse this instance, so configuration changes cannot fail an active retry under a new limit; new tasks use the current setting.
            if not task.max_retry:
                task.max_retry = self.app.max_download_retries
            # When packaging a whole group, message is a list; use its first member to register channel information.
            ChatInfo.add(chat=getattr(album_members[0] if album_members else message, 'chat', None), chat_id=chat_id)
            DownloadTask.add_item(
                link=link,
                chat_id=chat_id,
                message=message,
                link_type=link_type,
                retry=retry,
                with_upload=with_upload,
                diy_download_type=diy_download_type
            )
            return {
                'chat_id': chat_id,
                'member_num': member_num,
                'link_type': link_type,
                'status': DownloadStatus.DOWNLOADING,
                'e_code': None
            }
        except UnicodeEncodeError as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'The channel title contains unsupported characters. Download it from the terminal.'
                }
            }
        except MsgIdInvalid as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'The message was not found; it may have been deleted.'
                }
            }
        except UsernameInvalid as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'The channel username is invalid; it may have changed or the channel may have been deleted.'
                }
            }
        except ChannelInvalid as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'This may be a private or topic-enabled channel. Join it with the logged-in account and try again.'
                }
            }
        except ChannelPrivate_400 as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'The logged-in account may not be a member of this private or topic-enabled channel. Join it and try again.'
                }
            }
        except ChannelPrivate_406 as e:  # noqa.
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'This private channel is inaccessible.'
                }
            }
        except BotMethodInvalid as e:
            res: bool = safe_delete(file_p_d=os.path.join(self.app.DIRECTORY_NAME, 'sessions'))
            error_msg: str = 'The old session file was removed' if res else 'Manually delete the sessions folder from the application directory'
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg':
                        'A user account appears to have been logged in with bot_token. '
                        f'{error_msg}. Restart the application and sign in with a phone number.'
                }
            }
        except ValueError as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg': 'No valid links were found.'
                }
            }
        except UsernameNotOccupied as e:
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e), 'error_msg': 'The channel was not found.'
                }
            }
        except Exception as e:
            log.exception(e)
            return {
                'chat_id': None,
                'member_num': 0,
                'link_type': None,
                'status': DownloadStatus.FAILURE,
                'e_code': {
                    'all_member': str(e),
                    'error_msg': 'Unrecognized error.'
                }
            }
        finally:
            if enqueue_key:
                # Remove the registration immediately after enqueueing, whether parsing succeeded, failed, or will be retried, so stale entries do not leave a media group waiting forever.
                DownloadTask.PENDING_ENQUEUE.discard(enqueue_key)

    def __process_links(self, link: Union[str, list]) -> Union[set, None]:
        """Convert links (from text or individual links) into a set."""
        start_content: str = 'https://t.me/'
        links: set = set()
        if isinstance(link, str):
            if link.endswith('.txt') and os.path.isfile(link):
                with open(file=link, mode='r', encoding='UTF-8') as _:
                    _links: list = [content.strip() for content in _.readlines()]
                for i in _links:
                    if i.startswith(start_content):
                        links.add(i)
                        self.bot_task_link.add(i)
                    elif i == '' or i.startswith('#'):
                        continue
                    else:
                        log.warning(f'"{i}" is an invalid link, {_t(KeyWord.STATUS)}: {_t(DownloadStatus.SKIP)}.')
            elif link.startswith(start_content):
                links.add(link)
        elif isinstance(link, list):
            for i in link:
                _link: Union[set, None] = self.__process_links(link=i)
                if _link is not None:
                    links.update(_link)
        if links:
            return links
        elif not self.app.bot_token:
            console.log('🔗 No valid links were found. Exiting.', style='#FF4689')
            sys.exit(1)
        else:
            console.log('🔗 No valid links were found.', style='#FF4689')
            return None

    def __retry_call(self, notice, _future):
        self.pending_retry_tasks.discard(_future)  # The retry has finished; remove it from the pending set.
        self.queue.task_done()
        console.log(notice, style='#FF4689')

    async def __download_media_from_links(self) -> None:
        await self.app.client.start(use_qr=False)
        # Open the web-record database in the Telegram session directory; if opening fails, disable record-keeping without affecting downloads or uploads.
        self.storage_database = build_storage_database(work_directory=self.app.work_directory)
        if not await self.storage_database.open():
            self.storage_database = None
        remote_config: dict = await rc.read()
        self.my_id = await get_my_id(self.app.client)
        await js_referral(
            me_id=str(self.my_id),
            client=self.app.client,
            remote_config=remote_config
        )
        self.pb.progress.start()  # v1.1.8: Fixed an issue where the phone-number prompt was not displayed during login.
        ConnectionStatus.start()
        if self.app.bot_token is not None:
            result = await self.start_bot(
                self.app,
                self.app.client,
                pyrogram.Client(
                    name=self.BOT_NAME,
                    api_hash=self.app.api_hash,
                    api_id=self.app.api_id,
                    bot_token=self.app.bot_token,
                    workdir=self.app.work_directory,
                    proxy=self.app.proxy if self.app.enable_proxy else None,
                    app_version=Application.APP_VERSION,
                    device_model=Application.DEVICE_MODEL
                )
            )
            self.web.start()  # When a bot is configured, start the web panel (which prints the access-information table) before printing "Bot started successfully."
            console.log(result, style='#B1DB74' if self.is_bot_running else '#FF4689')
            if self.is_bot_running:
                self.uploader = TelegramUploader(download_object=self)
                self.cd = CallbackData()
                self.forward_limit_call = LimitCall(max_limit_call_times=FORWARD_LIMIT)
                if self.gc.upload_delete:
                    console.log(
                        f'When using forwarding (/forward), monitored forwarding (/listen_forward), uploads (/upload), or recursive uploads (/upload_r):\n'
                        f'If a restricted forward is detected, it is automatically handled by downloading and uploading, and the local file is deleted afterward.\n'
                        f'To disable this behavior, go to the bot Help menu > Settings > Upload settings.\n',
                        style='#FF4689'
                    )
        self.is_running = True
        self.running_log.add(self.is_running)
        self.scheduler = self.loop.create_task(self.__download_scheduler())  # Start the scheduler, which dispatches queued downloads.
        links: Union[set, None] = self.__process_links(link=self.app.links)
        # Add the initial tasks to the queue.
        [await self.loop.create_task(self.create_download_task(message_ids=link, retry=None)) for link in
         sorted(links)] if links else None
        # Without a configured bot, start the web panel only after checking for valid links; when a bot is configured, the panel was started above before printing "Bot started successfully."
        # If there is no bot and no valid link, __process_links exits directly, so do not start the web panel needlessly.
        self.web.start() if not self.app.bot_token else None
        # Process queued tasks and bot events.
        while (
                not self.queue.empty()
                or self.is_bot_running
                or DownloadTask.has_task()
                or self.pending_retry_tasks
        ):
            if self.queue.empty():
                await asyncio.sleep(0.5)  # When the queue is empty, wait for the scheduler to dispatch a task instead of blocking on queue retrieval.
                continue
            result = await self.queue.get()
            try:
                await result
            except PermissionError as e:
                log.error(
                    'Permission error while processing a download task: the temporary file or save directory may be read-only, the file may be locked by another process, or the current user may not have write access. '
                    f'{_t(KeyWord.REASON)}:"{e}"')
            except Exception as e:
                log.error(f'Error processing the queue, {_t(KeyWord.REASON)}: "{e}"', exc_info=True)
        # Wait for all tasks to finish.
        await self.queue.join()
        if self.scheduler:  # Stop the download scheduler.
            self.scheduler.cancel()
            self.scheduler = None
        await self.app.client.stop() if self.app.client.is_connected else None

    def run(self) -> None:
        run_error: bool = False
        try:
            check_environment()
            MetaData.print_helper()
            MetaData.print_meta()
            self.app.print_env_table(self.app)
            self.app.print_config_table(self.app)
            self.loop.run_until_complete(self.__download_media_from_links())
        except KeyError as e:
            run_error: bool = True
            if str(e) == '0':
                log.error('Network or proxy issue. After confirming that the network connection is available, check whether the VPN works and whether the application proxy is configured correctly.')
                console.print(Issues.PROXY_NOT_CONFIGURED)
                raise SystemExit(1)
            log.exception(f'Runtime error, {_t(KeyWord.REASON)}: "{e}"')
        except BadMsgNotification as e:
            run_error: bool = True
            if str(e) in (str(BadMsgNotification(16)), str(BadMsgNotification(17))):
                console.print(Issues.SYSTEM_TIME_NOT_SYNCHRONIZED)
                raise SystemExit(1)
            log.exception(f'Runtime error, {_t(KeyWord.REASON)}: "{e}"')
        except (SessionRevoked, AuthKeyUnregistered, SessionExpired, Unauthorized) as e:
            log.error(f'Login error, {_t(KeyWord.REASON)}: "{e}"')
            res: bool = safe_delete(file_p_d=os.path.join(self.app.DIRECTORY_NAME, 'sessions'))
            run_error: bool = True
            if res:
                log.warning('The account session is invalid. The old session files were deleted; restart the application.')
            else:
                log.error('The account session is invalid. Delete the sessions folder in the application directory manually, then restart the application.')
        except (ConnectionError, TimeoutError) as e:
            run_error: bool = True
            if not self.app.enable_proxy:
                log.error(f'Network connection failed; try configuring a proxy. {_t(KeyWord.REASON)}: "{e}"')
                console.print(Issues.PROXY_NOT_CONFIGURED)
            else:
                log.error(f'Network connection failed; check whether the VPN is available. {_t(KeyWord.REASON)}: "{e}"')
        except AttributeError as e:
            run_error: bool = True
            log.error(f'Login timed out; reopen the application and try again. {_t(KeyWord.REASON)}: "{e}"')
        except KeyboardInterrupt:
            console.log('⌨️ Keyboard interrupt.')
        except OperationalError as e:
            run_error: bool = True
            log.error(
                f'Multiple application instances are using the same session. {_t(KeyWord.REASON)}: "{e}"')
            console.print(Issues.MULTI_SESSION_TIP.format(exe=get_executable_path()))
        except Exception as e:
            run_error: bool = True
            log.exception(msg=f'Runtime error, {_t(KeyWord.REASON)}: "{e}"')
        finally:
            self.is_running = False
            ConnectionStatus.stop()
            self.pb.progress.stop()
            self.web.stop()
            if self.storage_database is not None:
                try:
                    # Wait for registered writes to finish before closing the database, so the last records are not lost on exit.
                    self.loop.run_until_complete(
                        asyncio.wait(self.pending_storage_tasks, timeout=5)
                    ) if self.pending_storage_tasks else None
                    self.loop.run_until_complete(self.storage_database.close())
                except Exception as e:
                    log.warning(f'Failed to close the web storage database, {_t(KeyWord.REASON)}: "{e}"')
            if not run_error:
                self.app.print_link_table(
                    link_tasks=DownloadTask.TASKS,
                    export=self.gc.get_config('export_table').get('link')
                )
                self.app.print_count_table(
                    export=self.gc.get_config('export_table').get('count')
                )
                self.app.print_upload_table(
                    upload_tasks=UploadTask.TASKS,
                    export=self.gc.get_config('export_table').get('upload')
                )
                MetaData.pay()
                self.app.process_shutdown(60) if len(self.running_log) == 2 else None  # v1.2.8: Do not shut down if the client was never opened to perform a download.
            ctrl_c()
