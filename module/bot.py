# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2025-1-24 21:27:00
# File:bot.py
import os
import copy
import asyncio
import datetime
import calendar

from functools import partial
from dataclasses import dataclass
from abc import (
    ABC,
    abstractmethod
)
from typing import (
    List,
    Dict,
    Union,
    Optional,
    Callable
)

import pyrogram
from pyrogram.types.messages_and_media import (
    ReplyParameters,
    LinkPreviewOptions
)
from pyrogram.handlers import (
    MessageHandler,
    CallbackQueryHandler
)
from pyrogram.errors import (
    FloodWait,
    FloodPremiumWait
)
from pyrogram.errors.exceptions.bad_request_400 import (
    MessageNotModified,
    AccessTokenInvalid
)
from pyrogram.types.bots_and_keyboards import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from module import (
    __version__,
    __copyright__,
    __license__,
    log,
    console,
    VERSION_SEMVER,
    SOFTWARE_SHORT_NAME
)
from module.remote import rc
from module.language import _t
from module.notice import NoticeHub
from module.config import GlobalConfig
from module.path_tool import safe_scan_directory_file
from module.stdio import (
    MetaData,
    PanelTable,
    ConnectionStatus
)
from module.task import (
    DownloadTask,
    UploadTask
)
from module.util import (
    is_docker,
    parse_link,
    safe_index,
    check_update,
    safe_message,
    attach_task,
    resolve_chat_id,
    is_allow_upload,
    get_valid_chat_id,
    parse_task_callback
)
from module.enums import (
    Issues,
    KeyWord,
    BotButton,
    BotMessage,
    BotStepText,
    UploadStatus,
    DownloadType,
    NoticeType,
    BotStepKeyword,
    BotCommandText,
    BotCallbackText,
    CalenderKeyboard,
    BotCallbackPrefix
)


class Bot:
    BOT_NAME: str = 'TRMD_BOT'
    COMMANDS: List[BotCommand] = [
        BotCommand(BotCommandText.HELP[0], BotCommandText.HELP[1].split('\n')[0]),
        BotCommand(BotCommandText.DOWNLOAD[0], BotCommandText.DOWNLOAD[1].split('\n')[0]),
        BotCommand(BotCommandText.TABLE[0], BotCommandText.TABLE[1].split('\n')[0]),
        BotCommand(BotCommandText.FORWARD[0], BotCommandText.FORWARD[1].split('\n')[0]),
        BotCommand(BotCommandText.EXIT[0], BotCommandText.EXIT[1].split('\n')[0]),
        BotCommand(BotCommandText.LISTEN_DOWNLOAD[0], BotCommandText.LISTEN_DOWNLOAD[1].split('\n')[0]),
        BotCommand(BotCommandText.LISTEN_FORWARD[0], BotCommandText.LISTEN_FORWARD[1].split('\n')[0]),
        BotCommand(BotCommandText.LISTEN_INFO[0], BotCommandText.LISTEN_INFO[1].split('\n')[0]),
        BotCommand(BotCommandText.UPLOAD[0], BotCommandText.UPLOAD[1].split('\n')[0]),
        BotCommand(BotCommandText.UPLOAD_R[0], BotCommandText.UPLOAD_R[1].split('\n')[0]),
        BotCommand(BotCommandText.DOWNLOAD_CHAT[0], BotCommandText.DOWNLOAD_CHAT[1].split('\n')[0]),
        BotCommand(BotCommandText.AUTH[0], BotCommandText.AUTH[1].split('\n')[0])
    ]
    COMMAND_STEPS: dict = {
        BotCommandText.DOWNLOAD[0]: (
            BotStepText.DOWNLOAD_LINK,
        ),
        BotCommandText.DOWNLOAD_CHAT[0]: (
            BotStepText.DOWNLOAD_CHAT_LINK,
        ),
        BotCommandText.UPLOAD[0]: (
            BotStepText.UPLOAD_PATH,
            BotStepText.UPLOAD_TARGET,
        ),
        BotCommandText.UPLOAD_R[0]: (
            BotStepText.UPLOAD_R_PATH,
            BotStepText.UPLOAD_R_TARGET,
        ),
        BotCommandText.FORWARD[0]: (
            BotStepText.FORWARD_ORIGIN,
            BotStepText.FORWARD_TARGET,
            BotStepText.FORWARD_START_ID,
            BotStepText.FORWARD_END_ID,
        ),
        BotCommandText.LISTEN_DOWNLOAD[0]: (
            BotStepText.LISTEN_DOWNLOAD_ORIGIN,
        ),
        BotCommandText.LISTEN_FORWARD[0]: (
            BotStepText.LISTEN_FORWARD_ORIGIN,
            BotStepText.LISTEN_FORWARD_TARGET,
        )
    }
    COMMAND_PREFIX_BLACKLIST: tuple = tuple(
        BotCommandText.commands_with_prefix()
    ) + ('/start',)
    LINK_PREVIEW_OPTIONS = LinkPreviewOptions(is_disabled=True)
    MAX_BOT_NOTICE_ITEMS = 20  # Maximum number of bot notice items. If a command has more links than this, stop sending notices through the bot to avoid overly long messages and frequent edits triggering rate limits.

    def __init__(self):
        self.application = None
        self.user: Union[pyrogram.Client, None] = None
        self.bot: Union[pyrogram.Client, None] = None
        self.is_bot_running: bool = False
        self.bot_task_link: set = set()
        self.gc = GlobalConfig()
        self.root: list = []
        self.auth_filter: Union[pyrogram.filters.Filter, None] = None
        self.last_client: Union[pyrogram.Client, None] = None
        self.last_message: Union[pyrogram.types.Message, None] = None
        self.listen_download_chat: dict = {}
        self.listen_forward_chat: dict = {}
        # Creator to notify (the user who created it): link/rule -> creator user ID.
        self.listen_download_owner: dict = {}
        self.listen_forward_owner: dict = {}
        # Monitored channel ID -> creator user ID, so listener callbacks can look up ownership by channel.
        self.listen_download_chat_owner: dict = {}
        self.handle_media_groups: dict = {}
        self.download_chat_filter: dict = {}
        self.download_chat_active: dict = {}  # Map users in the download_chat setup flow to their target channel IDs; isolate by user for concurrent use.
        self.adding_keywords: dict = {}  # Per-user list of keywords currently being added, supporting concurrent prompts.
        self.command_handlers: dict = {}  # Command-input handlers isolated by chat_id, supporting concurrent prompts.
        self.command_processed: set = set()  # Message IDs already handled in command-input mode, preventing duplicate handling by existing handlers.
        self.pending_tasks: dict = {}  # Pending task state for multi-step prompts.
        self.keyword_handlers: dict = {}  # Keyword-input handlers isolated by chat_id.
        self.auth_handlers: dict = {}  # Add-authorized-user input handlers isolated by chat_id.

    @staticmethod
    async def authorized_filter(flt, _client, update) -> bool:
        """Custom authorization filter that reads the authorized-user list (flt.authorized_ids) in real time to support hot updates."""
        user = getattr(update, 'from_user', None)
        uid = getattr(user, 'id', None)
        return uid is not None and uid in flt.authorized_ids

    def add_handler(self, handler, group: int = 0):
        """Add a handler to the specified group by modifying dispatcher.groups directly to ensure it is added correctly."""
        if group not in self.bot.dispatcher.groups:
            self.bot.dispatcher.groups[group] = []
        self.bot.dispatcher.groups[group].append(handler)
        log.info(f'Added handler to group={group}; current handler count: {len(self.bot.dispatcher.groups[group])}.')

    def remove_handler(self, handler, group: int = 0):
        """Remove a handler from the specified group by modifying dispatcher.groups directly to ensure it is removed correctly."""
        if group in self.bot.dispatcher.groups and handler in self.bot.dispatcher.groups[group]:
            self.bot.dispatcher.groups[group].remove(handler)
            log.info(f'Removed handler from group={group}; remaining handler count: {len(self.bot.dispatcher.groups[group])}.')

    def add_keyword_mode_handler(
            self,
            chat_id,
            callback_query: CallbackQuery,
            callback_prompt: Callable,
            enable: bool,
            task_chat_id=None
    ):
        """Add or remove the keyword-input-mode handler.

        chat_id is the session (user) receiving text input. Using it as the key ensures that each user has only one input mode at a time;
        task_chat_id is the download task (channel) associated with the input mode, so each of a user's tasks updates its own configuration.
        Each dictionary value is (task channel ID, handler), allowing the previous task association to be identified when switching input modes.
        """
        if task_chat_id is None:
            task_chat_id = chat_id
        if enable:
            # Remove this user's previous handler first, if any, to prevent stale handlers from accumulating.
            old = self.keyword_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old[1], group=-1)
            keyword_handler = MessageHandler(
                partial(self.handle_keyword_input, task_chat_id, callback_query, callback_prompt),
                filters=self.auth_filter & pyrogram.filters.chat(chat_id) & pyrogram.filters.text & (
                    lambda client, m: isinstance(
                        m,
                        pyrogram.types.Message
                    ) and m.text and m.text.strip() and not m.text.startswith(
                        '/') and not m.text.startswith('http')
                )
            )
            self.keyword_handlers[chat_id] = (task_chat_id, keyword_handler)
            self.add_handler(keyword_handler, group=-1)
            log.info(f'User input mode enabled; handler: "{keyword_handler}".')
        else:
            old = self.keyword_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old[1], group=-1)
                log.info('User input mode disabled; handlers cleared.')

    def add_command_mode_handler(
            self,
            chat_id,
            callback_query: CallbackQuery,
            command: str,
            enable: bool
    ):
        """Add or remove the command-input-mode handler, isolated by chat_id to prevent interference between users."""
        if enable:
            # Remove this user's previous handler first, if any, to prevent stale handlers from accumulating.
            old = self.command_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old, group=-1)
            self.pending_tasks[chat_id] = {'command': command, 'step': 0, 'data': {}}
            command_handler = MessageHandler(
                partial(self.handle_command_input, chat_id, callback_query, command),
                filters=self.auth_filter & pyrogram.filters.chat(chat_id) & pyrogram.filters.text & (
                    lambda client, m: isinstance(
                        m,
                        pyrogram.types.Message
                    ) and m.text and m.text.strip() and not m.text.startswith(self.COMMAND_PREFIX_BLACKLIST)
                )
            )
            self.command_handlers[chat_id] = command_handler
            self.add_handler(command_handler, group=-1)
            log.info(f'Command input mode enabled; handler: "{command_handler}".')
        else:
            old = self.command_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old, group=-1)
                log.info('Command input mode disabled; handlers cleared.')
            self.pending_tasks.pop(chat_id, None)

    async def start_command_guide(
            self,
            message: pyrogram.types.Message,
            command: str,
            callback_query: CallbackQuery = None
    ) -> None:
        """Start a multi-step command prompt, equivalent to clicking a blue menu button.

        When a user sends a command without arguments (such as `/download`), this replaces the syntax hint
        with the first-step prompt, then collects arguments using ForceReply and assembles the command for the existing flow.

        Note: In a callback, message is the menu message sent by the bot, so its from_user is the bot itself.
        Use the clicker's (callback_query.from_user) ID as chat_id, or sending a message to the bot itself will fail.
        """
        chat_id = callback_query.from_user.id if callback_query is not None else message.from_user.id
        steps = Bot.COMMAND_STEPS.get(command)
        if not steps:
            return None
        await self.bot.send_message(
            chat_id=chat_id,
            reply_parameters=ReplyParameters(message_id=message.id),
            text=steps[0][1],
            reply_markup=pyrogram.types.ForceReply(),
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS
        )
        self.add_command_mode_handler(
            chat_id=chat_id,
            callback_query=callback_query,
            command=command,
            enable=True
        )

    async def handle_command_input(
            self,
            chat_id,
            callback_query: CallbackQuery,
            command: str,
            _client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> None:
        """Collect user input for each command-defined step, then assemble the command for the existing flow."""
        pending = self.pending_tasks.get(chat_id)
        if not pending:
            self.add_command_mode_handler(
                chat_id=chat_id, callback_query=callback_query, command=command, enable=False)
            return None
        # Route using the latest command recorded in pending, not the stale argument bound to the handler, to prevent an old handler from creating a task.
        command = pending['command']
        steps = self.COMMAND_STEPS.get(command, ())
        if not steps:
            self.add_command_mode_handler(
                chat_id=chat_id, callback_query=callback_query, command=command, enable=False)
            return None
        step_idx = pending['step']
        field = steps[step_idx][0]
        text: str = message.text.strip()
        # Validate user input according to the field type; if invalid, ask for the current step again.
        if field in (BotStepKeyword.LINK, BotStepKeyword.ORIGIN, BotStepKeyword.TARGET):
            valid_http = text.startswith('http')
            # The download_chat link field and target fields for forward/listen_forward/upload/upload_r also accept me/self, referring to the logged-in account itself (such as Saved Messages).
            valid_me = (text in ('me', 'self') and (
                    (field == BotStepKeyword.LINK and command == BotCommandText.DOWNLOAD_CHAT[0])
                    or (field == BotStepKeyword.TARGET and command in (
                BotCommandText.FORWARD[0],
                BotCommandText.LISTEN_FORWARD[0],
                BotCommandText.UPLOAD[0],
                BotCommandText.UPLOAD_R[0]
            ))))
            if not (valid_http or valid_me):
                await _client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text='❌ Please enter a valid link and send it again.',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
                return None
        elif field in ('start_id', 'end_id'):
            if not text.isdigit():
                await _client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text='❌ Please enter a numeric ID and send it again.',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
                return None
        pending['data'][field] = str(text)
        pending['step'] += 1
        # More steps remain. Prevent group=0 links or incorrect handlers from interfering, then send the next prompt and continue waiting.
        if pending['step'] < len(steps):
            self.command_processed.add(message.id)
            next_hint = steps[pending['step']][1]
            await _client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text=next_hint,
                reply_markup=pyrogram.types.ForceReply(),
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None
        # All steps are complete. Assemble the command for the existing flow and prevent duplicate triggers in group=0.
        data = pending['data']
        if command == BotCommandText.DOWNLOAD[0]:
            await self.get_download_link_from_bot(client=_client, message=message)
        elif command == BotCommandText.DOWNLOAD_CHAT[0]:
            new_message = copy.copy(message)
            new_message.text = f'/{BotCommandText.DOWNLOAD_CHAT[0]} {data[BotStepKeyword.LINK]}'
            await self.get_download_chat_link_from_bot(client=self.bot, message=new_message)
        elif command in (BotCommandText.UPLOAD[0], BotCommandText.UPLOAD_R[0]):
            cmd = f'/{BotCommandText.UPLOAD[0]}' if command == BotCommandText.UPLOAD[
                0] else f'/{BotCommandText.UPLOAD_R[0]}'
            new_message = copy.copy(message)
            new_message.text = f'{cmd} {data[BotStepKeyword.PATH]} {data[BotStepKeyword.TARGET]}'
            await self.get_upload_link_from_bot(client=self.bot, message=new_message)
        elif command == BotCommandText.FORWARD[0]:
            new_message = copy.copy(message)
            new_message.text = f'/{BotCommandText.FORWARD[0]} {data[BotStepKeyword.ORIGIN]} {data[BotStepKeyword.TARGET]} {data[BotStepKeyword.START_ID]} {data[BotStepKeyword.END_ID]}'
            await self.get_forward_link_from_bot(client=self.bot, message=new_message)
        elif command == BotCommandText.LISTEN_DOWNLOAD[0]:
            new_message = copy.copy(message)
            new_message.text = f'/{BotCommandText.LISTEN_DOWNLOAD[0]} {data[BotStepKeyword.ORIGIN]}'
            await self.on_listen(client=self.bot, message=new_message)
        elif command == BotCommandText.LISTEN_FORWARD[0]:
            new_message = copy.copy(message)
            new_message.text = f'/{BotCommandText.LISTEN_FORWARD[0]} {data[BotStepKeyword.ORIGIN]} {data[BotStepKeyword.TARGET]}'
            await self.on_listen(client=self.bot, message=new_message)
        self.command_processed.add(message.id)
        self.add_command_mode_handler(
            chat_id=chat_id, callback_query=callback_query, command=command, enable=False)
        self.pending_tasks.pop(chat_id, None)

    async def process_error_message(self, client: pyrogram.Client, message: pyrogram.types.Message) -> None:
        if message.from_user.id in self.keyword_handlers:
            return
        if message.from_user.id in self.auth_handlers:
            return
        if message.id in self.command_processed:
            return
        await self.help(client, message)
        await client.send_message(
            chat_id=message.from_user.id,
            reply_parameters=ReplyParameters(message_id=message.id),
            text='⚠️ Unknown command.\nCheck the help menu and try again.',
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS
        )

    async def handle_keyword_input(
            self,
            chat_id: Union[str, int],
            callback_query: CallbackQuery,
            callback_prompt: Callable,
            _client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> None:
        """Handle user-entered keywords. chat_id is the ID of the download task (channel) associated with this input mode."""

        text: str = message.text.strip()

        if not text:
            return None
        # Ignore input if this task has already run or been canceled (its configuration was removed), so obsolete configuration is not updated.
        if chat_id not in self.download_chat_filter:
            return None

        # Split keywords on whitespace.
        keywords = [kw.strip() for kw in text.split() if kw.strip()]
        for keyword in keywords:
            if keyword in self.adding_keywords.get(chat_id, []):
                # Include only the keyword's list index in callback data to avoid exceeding the 64-byte limit with long keywords.
                keyword_index: int = self.adding_keywords[chat_id].index(keyword)
                try:
                    await callback_query.message.edit_text(
                        text=f'🚛 `{keyword}` was added. Choose how to handle it to continue.',
                        reply_markup=attach_task(
                            InlineKeyboardMarkup([
                                [
                                    InlineKeyboardButton(
                                        text=BotButton.DROP,
                                        callback_data=f'{BotCallbackText.DROP_KEYWORD}_{keyword_index}'
                                    ),
                                    InlineKeyboardButton(
                                        text=BotButton.IGNORE,
                                        callback_data=f'{BotCallbackText.IGNORE_KEYWORD}_{keyword_index}'
                                    )
                                ]
                            ]
                            ),
                            chat_id
                        )
                    )
                    return None
                except MessageNotModified:
                    pass
            else:
                self.download_chat_filter[chat_id]['keyword'][keyword] = True
                self.adding_keywords.setdefault(chat_id, []).append(keyword)  # Add to the list of keywords currently being added.
                try:
                    await callback_query.message.edit_text(
                        text=callback_prompt(),
                        reply_markup=attach_task(
                            KeyboardButton.keyword_filter_button(self.adding_keywords.get(chat_id, [])),
                            chat_id
                        )
                    )
                except MessageNotModified:
                    pass

    @staticmethod
    async def check_download_range(
            start_id: int,
            end_id: int,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> bool:
        if end_id != -1:
            if start_id > end_id:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text='❌ The start ID must not be greater than the end ID.'
                )
                return False
        if start_id == -1 or end_id == -1:
            text: str = 'Unknown error.'
            if start_id == -1:
                text: str = 'Start ID was not specified.'
            if end_id == -1:
                text: str = 'End ID was not specified.'
            if start_id == end_id:
                text: str = 'Neither the start nor end ID was specified.'
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text=f'❌{text}'
            )
            return False
        return True

    async def get_download_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            with_upload: Union[dict, None] = None,
            owner: Union[int, None] = None
    ) -> Union[Dict[str, Union[set, pyrogram.types.Message]], None]:
        if message.id in self.command_processed:
            return None
        requester: int = owner if owner is not None else message.from_user.id
        text: str = message.text
        if text == '/download':
            await self.start_command_guide(message=message, command=BotCommandText.DOWNLOAD[0])
            return None
        elif text.startswith('https://t.me/'):
            if text[len('https://t.me/'):].count('/') >= 1:
                text = f'/download {text}'
                return await self.parse_download_command(text, client, message, requester, with_upload)
            else:
                await client.send_message(
                    chat_id=requester,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'⬇️ Use this command to create a download task:\n`/download https://t.me/x/x`',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
        elif len(text) <= 25 or text == '/download https://t.me/x/x' or text.endswith('.txt'):
            await self.help(client, message)
            await client.send_message(
                chat_id=requester,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ Invalid link.\nCheck the help menu and try again.',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
        else:
            return await self.parse_download_command(text, client, message, requester, with_upload)

    async def parse_download_command(
            self,
            text: str,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            requester: Union[int, None] = None,
            with_upload: Union[dict, None] = None
    ) -> Union[Dict[str, Union[set, pyrogram.types.Message, None]], None]:
        """Parse the /download command (including after normalizing a bare link) and return link information."""
        link: list = text.split()
        link.remove('/download') if '/download' in link else None
        link = [_.rstrip('/') for _ in link]
        if (
                safe_index(link, 0, '').startswith('https://t.me/') and
                not safe_index(link, 1, 'https://t.me/').startswith('https://t.me/') and
                len(link) == 3
        ):
            # Range downloads supported since v1.5.1.
            start_id: int = int(safe_index(link, 1, -1))
            end_id: int = int(safe_index(link, 2, -1))
            if not await self.check_download_range(
                    start_id=start_id,
                    end_id=end_id,
                    client=client,
                    message=message
            ):
                return None
            right_link: set = set()
            invalid_link: set = set()
            for i in range(start_id, end_id + 1):
                right_link.add(f'{link[0]}/{i}?single')  # v1.6.7: Fix duplicate downloads when range links resolve to a group.
        else:
            right_link: set = set([_ for _ in link if _.startswith('https://t.me/')])
            invalid_link: set = set([_ for _ in link if not _.startswith('https://t.me/')])
        if right_link:
            if with_upload:
                # When downloading and then uploading, the upload result reports the download status, so do not send a separate notice here and duplicate notifications.
                # Return silently; never reach the TOO_MANY_MESSAGE or other notification branches below.
                return {
                    'right_link': right_link,
                    'invalid_link': invalid_link,
                    'last_bot_message': None
                }
            # For downloads without a subsequent upload, send the usual task-created notice (or indicate that notices are disabled when there are too many links).
            link_count: int = len(right_link) + len(invalid_link)
            if link_count <= Bot.MAX_BOT_NOTICE_ITEMS:
                notify_text: list = self.update_text(
                    right_link=right_link,
                    invalid_link=invalid_link
                )
            elif invalid_link:
                notify_text: list = [BotMessage.TOO_MANY_INVALID_DOWNLOAD_MESSAGE.format(count=len(invalid_link))]
            else:
                notify_text: list = ['\n'.join([BotMessage.TASK_ASSIGN, BotMessage.TOO_MANY_MESSAGE])]
            return {
                'right_link': right_link,
                'invalid_link': invalid_link,
                'last_bot_message': await self.safe_process_message(
                    client=client, message=message, requester=requester,
                    text=notify_text
                )
            }
        else:
            return None

    async def get_download_chat_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
    ):
        text: str = message.text
        if text == '/download_chat':
            await self.start_command_guide(message=message, command=BotCommandText.DOWNLOAD_CHAT[0])
            return None
        command = text.split()
        if len(command) != 2:
            await self.help(client, message)
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ Invalid command syntax.\nCheck the help menu and try again.',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None
        chat_link = command[1]
        try:
            meta = await parse_link(client=self.user, link=chat_link)
        except ValueError:
            meta = None
        if not isinstance(meta, dict):
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ Channel not found.',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None
        chat_id = meta.get('chat_id')
        if not chat_id:
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ Could not retrieve the channel name.',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None
        if chat_id in self.download_chat_filter:
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='⚠️ This channel is already being downloaded.\n'
                     f'{chat_link}',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None
        self.download_chat_filter[chat_id] = {
            'date_range':
                {
                    'start_date': None,
                    'end_date': None,
                    'adjust_step': 1
                },
            'download_type':
                {
                    'video': True,
                    'photo': True,
                    'document': True,
                    'audio': True,
                    'voice': True,
                    'animation': True,
                    'video_note': True,
                    'live_photo': True
                },
            'keyword': {},
            'title': {},
            'comment': False
        }
        self.download_chat_active[message.from_user.id] = chat_id
        log.info(f'Added "{chat_id}" to the download chat filters: {self.download_chat_filter}.')
        format_dtype = ','.join([_t(_) for _ in DownloadType()])
        include_comment = self.download_chat_filter[chat_id]['comment']
        comment: str = 'On' if include_comment else 'Off'
        await client.send_message(
            chat_id=message.from_user.id,
            reply_parameters=ReplyParameters(message_id=message.id),
            text=f'💬 Download channel: `{chat_id}`\n'
                 f'⏮️ Start date: Not set\n'
                 f'⏭️ End date: Not set\n'
                 f'📝 Download types: {format_dtype}\n'
                 f'🔑 Matching keywords: None\n'
                 f'👥 Include comments: {comment}',
            reply_markup=attach_task(KeyboardButton.download_chat_filter_button(include_comment), chat_id),
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS
        )

    @staticmethod
    async def safe_process_message(
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            text: list, last_message_id: int = -1,
            reply_markup: Union[pyrogram.types.InlineKeyboardMarkup, None] = None,
            requester: Union[int, None] = None
    ) -> pyrogram.types.Message:
        chat_id = requester if requester is not None else message.from_user.id
        if len(text) == 1 and last_message_id != -1:
            last_bot_message = await client.edit_message_text(
                chat_id=chat_id,
                message_id=last_message_id,
                text=text[0],
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                reply_markup=reply_markup
            )
            return last_bot_message

        last_bot_messages: list = []
        for t in text:
            last_bot_message: pyrogram.types.Message = await client.send_message(
                chat_id=chat_id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text=t,
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            if last_bot_message not in last_bot_messages:
                last_bot_messages.append(last_bot_message)
        return last_bot_messages[-1]

    @staticmethod
    def menu_keyboard(level: str = 'main', is_root: bool = False) -> InlineKeyboardMarkup:
        """Return the inline keyboard for a menu level: main is the grouped main menu; download/listen/upload/auth are second-level submenus."""
        config: dict = rc.cached_config()
        if level == 'download':
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        text=BotButton.CMD_DOWNLOAD,
                        callback_data=BotCallbackText.COMMAND_DOWNLOAD
                    ),
                    InlineKeyboardButton(
                        text=BotButton.CMD_DOWNLOAD_CHAT,
                        callback_data=BotCallbackText.COMMAND_DOWNLOAD_CHAT
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.HELP_PAGE,
                        callback_data=BotCallbackText.MENU_BACK
                    )
                ]
            ])
        if level == 'listen':
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        text=BotButton.LISTEN_DOWNLOAD_BTN,
                        callback_data=BotCallbackText.LISTEN_DOWNLOAD_BTN),
                    InlineKeyboardButton(
                        text=BotButton.LISTEN_FORWARD_BTN,
                        callback_data=BotCallbackText.LISTEN_FORWARD_BTN
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.LOOKUP_LISTEN_INFO,
                        callback_data=BotCallbackText.LOOKUP_LISTEN_INFO
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.HELP_PAGE,
                        callback_data=BotCallbackText.MENU_BACK
                    )
                ]
            ])
        if level == 'upload':
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        text=BotButton.CMD_UPLOAD,
                        callback_data=BotCallbackText.COMMAND_UPLOAD
                    ),
                    InlineKeyboardButton(
                        text=BotButton.CMD_UPLOAD_R,
                        callback_data=BotCallbackText.COMMAND_UPLOAD_R
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.HELP_PAGE,
                        callback_data=BotCallbackText.MENU_BACK
                    )
                ]
            ])
        if level == 'auth':
            return InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        text=BotButton.AUTH,
                        callback_data=BotCallbackText.AUTH
                    ),
                    InlineKeyboardButton(
                        text=BotButton.LOOKUP_AUTH_INFO,
                        callback_data=BotCallbackText.LOOKUP_AUTH_INFO
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.HELP_PAGE,
                        callback_data=BotCallbackText.MENU_BACK
                    )
                ]
            ])
        feature_rows = [
            [
                InlineKeyboardButton(
                    text=BotButton.MENU_DOWNLOAD,
                    callback_data=BotCallbackText.MENU_DOWNLOAD,
                    style=pyrogram.enums.ButtonStyle.PRIMARY
                ),
                InlineKeyboardButton(
                    text=BotButton.MENU_UPLOAD,
                    callback_data=BotCallbackText.MENU_UPLOAD,
                    style=pyrogram.enums.ButtonStyle.PRIMARY
                )
            ],
            [
                InlineKeyboardButton(
                    text=BotButton.CMD_FORWARD,
                    callback_data=BotCallbackText.COMMAND_FORWARD,
                    style=pyrogram.enums.ButtonStyle.PRIMARY
                ),
                InlineKeyboardButton(
                    text=BotButton.MENU_LISTEN,
                    callback_data=BotCallbackText.MENU_LISTEN,
                    style=pyrogram.enums.ButtonStyle.PRIMARY
                )
            ]
        ]
        auth_row = [
            [
                InlineKeyboardButton(
                    text=BotButton.AUTH_MENU,
                    callback_data=BotCallbackText.MENU_AUTH,
                    style=pyrogram.enums.ButtonStyle.PRIMARY
                )
            ]
        ] if is_root else []
        proxy_seller_url: str = config.get('proxy_seller', rc.DEFAULT_PROXY_SELLER)
        proxy_seller_row: list = [[
            InlineKeyboardButton(
                text=BotButton.PROXY_SELLER,
                url=proxy_seller_url,
                style=pyrogram.enums.ButtonStyle.DANGER
            )
        ]] if proxy_seller_url else []
        return InlineKeyboardMarkup(
            feature_rows + auth_row + [
                [
                    InlineKeyboardButton(
                        text=BotButton.GITHUB,
                        url=config.get('github', rc.DEFAULT_GITHUB) + '/releases'
                    ),
                    InlineKeyboardButton(
                        text=BotButton.SUBSCRIBE_CHANNEL,
                        url=config.get('subscribe_channel', rc.DEFAULT_SUBSCRIBE_CHANNEL)
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.VIDEO_TUTORIAL,
                        url=config.get('video_tutorial', rc.DEFAULT_VIDEO_TUTORIAL)
                    ),
                    InlineKeyboardButton(
                        text=BotButton.PAY,
                        callback_data=BotCallbackText.PAY,
                        style=pyrogram.enums.ButtonStyle.SUCCESS
                    )
                ],
                *proxy_seller_row,
                [
                    InlineKeyboardButton(
                        text=BotButton.SETTING,
                        callback_data=BotCallbackText.SETTING
                    )
                ]
            ]
        )

    async def help(
            self,
            client: Union[pyrogram.Client, None] = None,
            message: Union[pyrogram.types.Message, None] = None,
            user_id: Union[int, None] = None
    ) -> Union[None, dict]:  # Return the keyboard and text when both client and message are None.
        web = getattr(self, 'web', None)  # Web panel instance, used to display authentication information.
        web_auth: str = ''
        docker_host_ip_tip: str = ''
        more_feature: bool = False
        if user_id is not None:
            uid = user_id
        elif message and message.from_user:
            uid = message.from_user.id
        else:
            uid = None
        if uid is None or not self.root or uid == self.root[0]:
            more_feature = True
        if web is not None:
            docker_host_ip_tip: str = f'\n{Issues.DOCKER_HOST_IP_TIP}' if is_docker() else docker_host_ip_tip
            web_link: str = f'{web.protocol}://{web.LOCAL_IP}:{web.port}'
            web_rows = [
                ['Port', str(web.port)],
                ['Username', f'`{web.username}`'],
                ['Password', f'`{web.password}`'],
                ['Link', f'[{web_link}]({web_link})'],
            ]
            web_panel = PanelTable(title='🌐 Web settings', header=('Property', 'Value'), data=web_rows)
            web_auth = web_panel.to_markdown_chunks()[0]
        config: dict = rc.cached_config()
        update_version: str = check_update(  # Return the remote version if it is newer, so the user can be notified of an available update.
            remote_version=config.get('version', __version__),
            local_version=__version__
        )
        version: str = f'{VERSION_SEMVER}({update_version}⬆)' if update_version else VERSION_SEMVER
        keyboard = self.menu_keyboard(
            'main',
            is_root=(uid is None) or (not self.root) or (uid == self.root[0])
        )

        # Assemble the command list in its original order; show the authorization command only to admins (more_feature).
        command_items = [
            BotCommandText.HELP,
            BotCommandText.DOWNLOAD,
            BotCommandText.TABLE,
            BotCommandText.FORWARD,
            BotCommandText.EXIT,
            BotCommandText.LISTEN_DOWNLOAD,
            BotCommandText.LISTEN_FORWARD,
            BotCommandText.LISTEN_INFO,
            BotCommandText.UPLOAD,
            BotCommandText.UPLOAD_R,
            BotCommandText.DOWNLOAD_CHAT
        ]
        if more_feature:
            command_items.append(BotCommandText.AUTH)
        command_rows = []
        for item in command_items:
            # Split at the first \n: the first part is the description and the second is the syntax example (empty if there is no \n).
            _parts = item[1].split('\n', 1)
            _desc = _parts[0]
            _syntax = _parts[1] if len(_parts) > 1 else '&ndash;'
            command_rows.append([f'/{item[0]}', _desc, _syntax])
        # Reuse PanelTable to render a GitHub-style rich-text table like /table, with separate description and syntax columns.
        panel = PanelTable(title='🎮️ Available commands', header=('Command', 'Description', 'Syntax'), data=command_rows)
        table_markdown: str = panel.to_markdown_chunks()[0]
        # Reuse PanelTable to render a GitHub-style rich-text table like /table, with separate version, copyright, and license columns.
        info_rows = [
            ['Version', f'`{version}`'],
            ['Copyright', f'`{__copyright__.replace(" <https://github.com/Gentlesprite>", ".")}`'],
            ['License', f'`Licensed under the terms of the {__license__}.`']
        ]
        info_panel = PanelTable(
            title=f'💎 {SOFTWARE_SHORT_NAME}',
            header=('Property', 'Value'),
            data=info_rows
        )
        header_md: str = info_panel.to_markdown_chunks()[0]
        parts = [header_md, '', table_markdown]
        if web_auth:
            parts.append('')
            parts.append(web_auth.rstrip('\n'))
        if docker_host_ip_tip:
            parts.append('')
            parts.append(Issues.DOCKER_HOST_IP_TIP)
        if more_feature:
            parts.append('')
            feature_panel = PanelTable(
                title='✨ Other features',
                header=('Feature', 'Description'),
                data=[
                    [
                        '📨 Forward messages',
                        'Forward a `video`, `photo`, `audio`, `voice`, `GIF`, `document`, `video note`, or `live photo`'
                        ' message to the bot to create a download task.'
                    ]
                ]
            )
            parts.append(feature_panel.to_markdown_chunks()[0])
        text = '\n'.join(parts)
        if not all([client, message]):
            return {
                'keyboard': keyboard,
                'text': text
            }
        await client.send_rich_message(
            chat_id=message.from_user.id,
            rich_message=pyrogram.types.InputRichMessage(
                markdown=text,
                skip_entity_detection=True
            ),
            reply_markup=keyboard
        )

    async def start(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        await self.help(client, message)

    @staticmethod
    async def callback_data(client: pyrogram.Client, callback_query: CallbackQuery) -> Union[str, None]:
        await callback_query.answer()
        data = callback_query.data
        if not data:
            return None
        if isinstance(data, str):
            return data

    @staticmethod
    async def table(
            client: Union[pyrogram.Client, None] = None,
            message: Union[pyrogram.types.Message, None] = None
    ) -> Union[None, dict]:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        BotButton.LINK_TABLE,
                        callback_data=BotCallbackText.LINK_TABLE
                    ),
                    InlineKeyboardButton(
                        BotButton.COUNT_TABLE,
                        callback_data=BotCallbackText.COUNT_TABLE
                    )
                ],
                [
                    InlineKeyboardButton(
                        BotButton.UPLOAD_TABLE,
                        callback_data=BotCallbackText.UPLOAD_TABLE
                    )
                ],
                [
                    InlineKeyboardButton(
                        BotButton.HELP_PAGE,
                        callback_data=BotCallbackText.BACK_HELP
                    )
                ]
            ]
        )
        text: str = '📊 Select the type of statistics table to display:'
        if not all([client, message]):
            return {
                'keyboard': keyboard,
                'text': text
            }
        await client.send_message(
            chat_id=message.from_user.id,
            text=text,
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
            reply_markup=keyboard
        )

    async def get_forward_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> Union[Dict[str, Union[list, str]], None]:

        text: str = message.text
        args: list = text.split(maxsplit=5)
        if text == '/forward':
            await self.start_command_guide(message=message, command=BotCommandText.FORWARD[0])
            return None
        try:
            start_id: int = int(safe_index(args, 3, -1))
            end_id: int = int(safe_index(args, 4, -1))
            if not await self.check_download_range(
                    start_id=start_id,
                    end_id=end_id,
                    client=client,
                    message=message):
                return None
        except Exception as e:
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text=f'❌ Command error:\n{e}\nUse `/forward https://t.me/A https://t.me/B 1 100`.'
            )
            return None
        return {
            'origin_link': args[1],
            'target_link': args[2],
            'message_range': [start_id, end_id]
        }

    async def get_upload_link_from_bot(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            delete: bool = False,
            save_directory: str = None,
            recursion: bool = False,
            valid_link_cache: dict = None
    ):
        if not recursion:
            valid_link_cache = {}

        text: str = message.text
        if text == '/upload' or text == '/upload_r':
            command = BotCommandText.UPLOAD[0] if text == '/upload' else BotCommandText.UPLOAD_R[0]
            await self.start_command_guide(message=message, command=command)
            return None

        if text.startswith('/upload '):
            remaining_text = text[len('/upload '):].strip()
            command = '/upload'
        elif text.startswith('/upload_r '):
            remaining_text = text[len('/upload_r '):].strip()
            command = '/upload_r'
        else:
            return None

        parts = remaining_text.rsplit(maxsplit=1)

        if len(parts) == 2:
            file_path = parts[0]  # Filename portion (may contain spaces).
            target_link = parts[1]  # URL portion.
            if not recursion:
                if target_link not in valid_link_cache:
                    valid_link_cache[target_link] = await get_valid_chat_id(
                        link=target_link,
                        user_client=self.user,
                        bot_client=self.bot,
                        bot_message=message,
                        error_msg=f'⬇️ Destination channel not found:\n{target_link}'
                    )
                if not valid_link_cache[target_link]:
                    return None
            if os.path.isdir(file_path):
                upload_folder = []
                if command == f'/{BotCommandText.UPLOAD_R[0]}':
                    upload_files = [os.path.join(root, filename) for root, dirs, files in os.walk(file_path) for
                                    filename in files]
                else:
                    upload_files = safe_scan_directory_file(file_path)
                for file_name in upload_files:
                    new_message = copy.copy(message)
                    new_message.text = f'/{BotCommandText.UPLOAD[0]} {os.path.join(file_path, file_name)} {target_link}'
                    upload_folder.append(
                        self.get_upload_link_from_bot(
                            client=client,
                            message=new_message,
                            delete=delete,
                            save_directory=save_directory,
                            recursion=True,
                            valid_link_cache=valid_link_cache
                        )
                    )
                if upload_folder:
                    await client.send_message(
                        chat_id=message.from_user.id,
                        reply_parameters=ReplyParameters(message_id=message.id),
                        text=f'📤 Upload task created. Please wait.\n`{file_path}`',
                        link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                    )
                    await asyncio.gather(*upload_folder)
                else:
                    await client.send_message(
                        chat_id=message.from_user.id,
                        reply_parameters=ReplyParameters(message_id=message.id),
                        text=f'⚠️ Folder is empty.\n`{file_path}`',
                        link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                    )
                return None
            if not os.path.isfile(file_path):
                log.error(f'Upload error, {_t(KeyWord.REASON)}: "{file_path}" does not exist.')
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'⚠️ Upload file not found.\n`{file_path}`',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
                return None
            file_size = os.path.getsize(file_path)
            if file_size == 0:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'⚠️ Upload file is empty (0 bytes).\n`{file_path}`',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )

            if not is_allow_upload(file_size=file_size, is_premium=self.user.me.is_premium):
                format_file_size: str = MetaData.suitable_units_display(file_size, unit='MiB', mebibyte=True)
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'⚠️ Upload size exceeds the limit ({format_file_size}).\n'
                         f'`{file_path}`\n'
                         f'(2,000 MiB for standard users; 4,000 MiB for Premium users)',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
            if not recursion:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'📤 Upload task created. Please wait.\n`{file_path}`',
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
            log.info(f'Uploading file "{file_path}" to channel "{target_link}".')
            # Record the upload task creator so the web panel can show who created the task in completion or failure notices.
            NoticeHub.add_owner(owner=message.from_user.id, user=message.from_user)
            if target_link.startswith('https://t.me/') or target_link in ('me', 'self'):  # Validate the target link format.
                return {
                    'target_link': target_link,
                    'valid_link_cache': valid_link_cache,
                    'upload_task': UploadTask(
                        chat_id=None,
                        file_path=file_path,
                        file_id=self.user.rnd_id(),
                        file_size=os.path.getsize(file_path),
                        file_part=[],
                        status=UploadStatus.PENDING,
                        owner=message.from_user.id
                    )
                }
        if not recursion:
            await self.help(client, message)
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='❌ Invalid command.\nCheck the help menu and try again.',
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS
            )
            return None

    async def exit(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> None:
        last_message = await client.send_message(
            chat_id=message.from_user.id,
            text='🚧 Exit command received.',
            reply_parameters=ReplyParameters(message_id=message.id),
            link_preview_options=Bot.LINK_PREVIEW_OPTIONS
        )
        self.is_bot_running = False
        await self.safe_edit_message(
            client=client,
            message=message,
            last_message_id=last_message.id,
            text='✅ Exited successfully.'
        )
        raise SystemExit(0)

    async def on_listen(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> Union[Dict[str, list], None]:
        text: str = message.text
        args: list = text.split()
        command: str = args[0]
        links: list = args[1:]
        if text.startswith('/listen_download'):
            if len(args) == 1:
                await self.start_command_guide(message=message, command=BotCommandText.LISTEN_DOWNLOAD[0])
                return None
            last_message: Union[pyrogram.types.Message, str, None] = None
            invalid_links: list = []
            for link in links:
                if not link.startswith('https://t.me/'):
                    invalid_links.append(link)
                    if not last_message:
                        last_message = await client.send_message(
                            chat_id=message.from_user.id,
                            reply_parameters=ReplyParameters(message_id=message.id),
                            text=BotMessage.INVALID
                        )
                    last_message: Union[pyrogram.types.Message, str, None] = await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text=safe_message(f'{last_message.text}\n{link}')
                    )
                for meta in self.listen_forward_chat:
                    listen_link, target_link = meta.split()
                    if listen_link == link:
                        invalid_links.append(listen_link)
                        if not last_message:
                            last_message = await client.send_message(
                                chat_id=message.from_user.id,
                                reply_parameters=ReplyParameters(message_id=message.id),
                                text='❌ A channel cannot have two listeners at once.\n(You already created a forwarding listener with `/listen_forward` for the following link.)'
                            )
                        last_message: Union[pyrogram.types.Message, str, None] = await self.safe_edit_message(
                            client=client,
                            message=message,
                            last_message_id=last_message.id,
                            text=safe_message(f'{last_message.text}\n{listen_link}')
                        )

            if invalid_links:
                for ivl in invalid_links:
                    if ivl in links:
                        links.remove(ivl)
                if not links:
                    await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text='❌ No valid links found.'
                    )
                    return None
            links: list = list(set(links))

        elif text.startswith('/listen_forward'):
            e: str = ''
            len_args: int = len(args)
            if len_args != 3:
                if len_args == 1:
                    await self.start_command_guide(message=message, command=BotCommandText.LISTEN_FORWARD[0])
                    return None
                elif len_args == 2:
                    e: str = 'The command is missing the destination channel.'
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'❌{e}\n'
                         '⬇️ Syntax:\n'
                         f'`/listen_forward source_channel destination_channel`\n'
                         '⬇️ Example:\n'
                         f'`/listen_forward https://t.me/A https://t.me/B`\n'
                )
                return None
            listen_link: str = args[1]
            target_link: str = args[2]
            if listen_link in self.listen_download_chat:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text='❌ A channel cannot have two listeners at once.\n(You already created a download listener with `/listen_download` for the following link.)\n'
                         f'{listen_link}'
                )
                return None
            if not listen_link.startswith('https://t.me/'):
                e = 'Invalid monitoring channel link.'
            if not target_link.startswith('https://t.me/'):
                e = 'Invalid destination channel link.'
            if e != '':
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=f'❌{e}\n'
                         '⬇️ Syntax:\n'
                         f'`/listen_forward source_channel destination_channel`\n'
                         '⬇️ Example:\n'
                         f'`/listen_forward https://t.me/A https://t.me/B`\n'
                )
                return None
        return {'command': command, 'links': links}

    @staticmethod
    async def listen_download(
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        pass

    @staticmethod
    async def listen_forward(
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ):
        pass

    async def cancel_listen(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            link: str,
            command: str,
            from_web: bool = False
    ):
        pass

    async def listen_info(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            target: Union[int, None] = None,
            edit_message: Union[pyrogram.types.Message, None] = None
    ):
        async def __listen_info(_listen_chat: dict, _text: str):
            if edit_message is not None:
                # On a button click, edit the current message in place instead of sending a new message to a possibly bot-owned chat.
                text = _text
                for link in _listen_chat:
                    args: list = link.split()
                    if len(args) == 1:
                        text = f'{text}\n{link}'
                    elif len(args) == 2:
                        text = f'{text}\n{args[0]} ➡️ {args[1]}'
                await self.safe_edit_message(
                    client=client,
                    message=edit_message,
                    last_message_id=edit_message.id,
                    text=safe_message(text)
                )
                return
            last_message = await client.send_message(
                chat_id=target if target is not None else message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                text=_text
            )
            for link in _listen_chat:
                args: list = link.split()
                len_args: int = len(args)
                if len_args == 1:
                    last_message = await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text=safe_message(f'{last_message.text}\n{link}')
                    )
                elif len_args == 2:
                    forward_emoji = ' ➡️ '
                    last_message = await self.safe_edit_message(
                        client=client,
                        message=message,
                        last_message_id=last_message.id,
                        text=safe_message(f'{last_message.text}\n{args[0]}{forward_emoji}{args[1]}')
                    )

        if not self.listen_forward_chat and not self.listen_download_chat:
            if edit_message is not None:
                try:
                    await edit_message.edit_text(
                        text='🌫️ No channels are currently being monitored.',
                        reply_markup=self.menu_keyboard('listen'))
                except MessageNotModified:
                    pass
            else:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                    text='🌫️ No channels are currently being monitored.'
                )
        else:
            if self.listen_download_chat:
                await __listen_info(self.listen_download_chat, '🕵️ Download listeners are configured for these links:\n')
            if self.listen_forward_chat:
                await __listen_info(self.listen_forward_chat, '📲 Forwarding listeners are configured for these links:\n')
            if edit_message is not None:
                try:
                    await edit_message.edit_reply_markup(self.menu_keyboard('listen'))
                except MessageNotModified:
                    pass

    async def auth_user(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> None:
        """Hot-add or hot-remove an authorized user by user ID or @username."""
        # /auth is for root only; admins (created by root) are told directly that the command is unavailable.
        if not self.root or message.from_user.id != self.root[0]:
            await client.send_message(
                chat_id=message.from_user.id,
                reply_parameters=ReplyParameters(message_id=message.id),
                text='⛔ This command is available to `root` only.'
            )
            return None
        text: str = message.text
        args: list = text.split()
        if len(args) == 1:
            # With no arguments, show the authorization-management menu; display the list only after clicking 'View authorized users'.
            await self.show_auth_menu(client=client, message=message)
            return None
        await self.add_authorized_user(client=client, message=message, target=args[1])

    async def add_authorized_user(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            target: str,
            edit_message: Union[pyrogram.types.Message, None] = None
    ) -> None:
        """Resolve a user ID or @username and hot-add the user to the authorized list (root-only; root is not checked here).

        When edit_message is provided (input mode), edit that message with the result instead of sending another one, avoiding duplicate prompts.
        """
        auth_kb = self.menu_keyboard('auth')
        # Use pyrogram to consistently verify that the user exists; accept a user ID or @username.
        target = target.lstrip('@')

        async def _respond(text: str, reply_markup=None):
            if edit_message is not None:
                try:
                    await edit_message.edit_text(text=text, reply_markup=reply_markup)
                except MessageNotModified:
                    pass
            else:
                await client.send_message(
                    chat_id=message.from_user.id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=text,
                    reply_markup=reply_markup
                )

        try:
            uid = (await self.user.get_users(
                int(target) if target.isdigit() else target
            )).id
        except Exception as e:
            await _respond(
                text=f'❌ Could not resolve user "{target}".\n{_t(KeyWord.REASON)}: "{e}"',
                reply_markup=auth_kb if edit_message is not None else None
            )
            return None
        if uid is None:
            return None
        # The root user already has all permissions and does not need to be authorized again.
        if self.root and uid == self.root[0]:
            await _respond(
                text='👑 This user is `root` and already has all permissions; no authorization is needed.',
                reply_markup=auth_kb if edit_message is not None else None
            )
            return None
        # If the user is already authorized, show a remove button instead of adding them again.
        if uid in self.gc.authorized_users:
            await _respond(
                text=f'👥 User `{uid}` is already authorized. Remove them?',
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            text=BotButton.REMOVE_AUTH,
                            callback_data=f'{BotCallbackText.REMOVE_AUTH_USER}_{uid}'
                        ),
                        InlineKeyboardButton(
                            text=BotButton.LOOKUP_AUTH_INFO,
                            callback_data=BotCallbackText.LOOKUP_AUTH_INFO
                        )
                    ]
                ])
            )
            return None
        # Hot-add the authorized user: update the filter immediately and persist the change in the global configuration.
        self.gc.authorized_users.append(uid)
        self.root.append(uid)
        self.gc.config['authorized_users'] = self.gc.authorized_users
        self.gc.save_config(self.gc.config)
        await _respond(
            text=f'✅ Authorized user added (`ID`):\n`{uid}`',
            reply_markup=auth_kb
        )
        log.info(f'Authorized user added: {uid}; current authorized users: {self.gc.authorized_users}.')

    def add_auth_mode_handler(
            self,
            chat_id,
            callback_query: CallbackQuery,
            enable: bool
    ):
        """Add or remove the "add authorized user" input-mode handler, isolated by chat_id to prevent interference between users."""
        if enable:
            # Remove this user's previous handler first, if any, to prevent stale handlers from accumulating.
            old = self.auth_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old, group=-1)
            auth_handler = MessageHandler(
                partial(self.handle_auth_input, chat_id, callback_query),
                filters=self.auth_filter & pyrogram.filters.chat(chat_id) & pyrogram.filters.text & (
                    lambda client, m: isinstance(
                        m,
                        pyrogram.types.Message
                    ) and m.text and m.text.strip() and not m.text.startswith('/')
                )
            )
            self.auth_handlers[chat_id] = auth_handler
            self.add_handler(auth_handler, group=-1)
            log.info(f'Add-authorized-user input mode enabled; handler: "{auth_handler}".')
        else:
            old = self.auth_handlers.pop(chat_id, None)
            if old:
                self.remove_handler(old, group=-1)
                log.info('Add-authorized-user input mode disabled; handlers cleared.')

    async def handle_auth_input(
            self,
            chat_id,
            callback_query: CallbackQuery,
            _client: pyrogram.Client,
            message: pyrogram.types.Message
    ) -> None:
        """Handle the user ID or @username that root submits for authorization in input mode."""
        # Only root can authorize users, and accept input only from the user who initiated the flow.
        if not self.root or message.from_user.id != self.root[0] or message.from_user.id != chat_id:
            self.add_auth_mode_handler(chat_id=chat_id, callback_query=callback_query, enable=False)
            return None
        # Have add_authorized_user edit the "🔐Authorized User Management" message with the result, avoiding a duplicate prompt.
        await self.add_authorized_user(
            client=self.bot,
            message=message,
            target=message.text.strip(),
            edit_message=callback_query.message
        )
        # Close input mode when processing is complete.
        self.add_auth_mode_handler(chat_id=chat_id, callback_query=callback_query, enable=False)

    @staticmethod
    async def show_auth_menu(
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            edit_message: Union[pyrogram.types.Message, None] = None
    ) -> None:
        """The /auth entry menu: show a row of buttons first, and display the user list only after 'View authorized users' is clicked."""
        auth_menu_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    text=BotButton.AUTH,
                    callback_data=BotCallbackText.AUTH
                ),
                InlineKeyboardButton(
                    text=BotButton.VIEW_AUTH_LIST,
                    callback_data=BotCallbackText.VIEW_AUTH_LIST
                )
            ],
            [
                InlineKeyboardButton(
                    text=BotButton.HELP_PAGE,
                    callback_data=BotCallbackText.MENU_BACK
                )
            ]
        ])
        text = '🔐 Authorized user management. Choose an action:'
        if edit_message is not None:
            try:
                await edit_message.edit_text(text=text, reply_markup=auth_menu_kb)
            except MessageNotModified:
                pass
        else:
            await client.send_message(
                chat_id=message.from_user.id,
                text=text,
                reply_markup=auth_menu_kb
            )

    async def show_authorized_users(
            self,
            client: pyrogram.Client,
            message: pyrogram.types.Message,
            target: Union[int, None] = None,
            edit_message: Union[pyrogram.types.Message, None] = None
    ) -> None:
        """Display the current list of additional authorized users. When edit_message is provided (button click), edit that message directly."""
        users = self.gc.authorized_users
        chat_id = target if target is not None else message.from_user.id
        auth_kb = self.menu_keyboard('auth')

        async def _respond(text: str):
            if edit_message is not None:
                try:
                    await edit_message.edit_text(text=text, reply_markup=auth_kb)
                except MessageNotModified:
                    pass
            else:
                await client.send_message(
                    chat_id=chat_id,
                    reply_parameters=ReplyParameters(message_id=message.id),
                    text=text
                )

        if not users:
            await _respond('🌫️ No additional users are authorized; only `root` can use the bot.')
            return None
        lines = '\n'.join(str(u) for u in users)
        await _respond(f'👥 Authorized user IDs:\n`{lines}`')

    async def handle_forwarded_media(
            self,
            user_client: pyrogram.Client,
            user_message: pyrogram.types.Message
    ):
        pass

    async def done_notice(
            self,
            text,
            requester: Union[int, None] = None,
            notice_type: str = NoticeType.DOWNLOAD
    ):
        # The bot no longer sends these notices directly; register them with the notice center for display in the web panel's Notifications section.
        # Attribute each task to its creator; if requester is unspecified, fall back to the latest message for backward compatibility.
        # This fallback is compatibility-only: log a warning whenever it is used so a notice sent to the wrong person is not silent.
        owner: Union[int, None] = requester
        if owner is None:
            if self.last_message is not None:
                owner = self.last_message.from_user.id
                log.warning(
                    'done_notice has no requester; falling back to last_message(chat_id={chat_id}). Set owner at the call site to avoid this fallback.')
            else:
                log.warning('done_notice has no requester and last_message is empty; this notice will have no owner.')
        NoticeHub.push(notice_type=notice_type, text=text, owner=owner)
        log.debug(f'Notice sent, {_t(KeyWord.TYPE)}: "{notice_type}", owner: "{owner}", content: "{text}".')

    async def start_bot(
            self,
            application,
            user_client_obj: pyrogram.Client,
            bot_client_obj: pyrogram.Client,
    ) -> str:
        """Start the bot."""
        try:
            self.application = application
            self.bot = bot_client_obj
            self.user = user_client_obj
            root = await self.user.get_me()
            self.root.append(root.id)
            # Include authorized users from the global configuration so they can also operate the bot.
            self.root.extend(
                uid for uid in self.gc.authorized_users
                if isinstance(uid, int) and uid != root.id
            )
            # Build a custom filter from the authorized-user list (self.root), reading it in real time to support hot additions and removals.
            self.auth_filter = pyrogram.filters.create(
                self.authorized_filter,
                name='AuthorizedUser',
                authorized_ids=self.root
            )
            await bot_client_obj.start()
            await self.bot.set_bot_commands(self.COMMANDS)
            bot = await self.bot.get_me()
            bot_username = getattr(bot, 'username', None)

            self.bot.add_handler(
                MessageHandler(
                    self.start,
                    filters=pyrogram.filters.command(['start']) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.help,
                    filters=pyrogram.filters.command([BotCommandText.HELP[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_download_link_from_bot,
                    filters=pyrogram.filters.command([BotCommandText.DOWNLOAD[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_download_chat_link_from_bot,
                    filters=pyrogram.filters.command([BotCommandText.DOWNLOAD_CHAT[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_upload_link_from_bot,
                    filters=pyrogram.filters.command([BotCommandText.UPLOAD[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_upload_link_from_bot,
                    filters=pyrogram.filters.command([BotCommandText.UPLOAD_R[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.table,
                    filters=pyrogram.filters.command([BotCommandText.TABLE[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_forward_link_from_bot,
                    filters=pyrogram.filters.command([BotCommandText.FORWARD[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.exit,
                    filters=pyrogram.filters.command([BotCommandText.EXIT[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.on_listen,
                    filters=pyrogram.filters.command(
                        [BotCommandText.LISTEN_DOWNLOAD[0], BotCommandText.LISTEN_FORWARD[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.listen_info,
                    filters=pyrogram.filters.command([BotCommandText.LISTEN_INFO[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.auth_user,
                    filters=pyrogram.filters.command([BotCommandText.AUTH[0]]) & self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.get_download_link_from_bot,
                    # During command-input mode, route this chat's links only to command_handler to avoid also triggering the download handler.
                    filters=pyrogram.filters.regex(r'^https://t.me.*') & self.auth_filter & (
                        lambda client, m: m.chat.id not in self.pending_tasks
                    )
                )
            )
            self.user.add_handler(
                MessageHandler(
                    self.handle_forwarded_media,
                    filters=self.auth_filter & pyrogram.filters.forwarded & pyrogram.filters.chat(
                        bot_username) & (
                                    pyrogram.filters.video
                                    | pyrogram.filters.photo
                                    | pyrogram.filters.audio
                                    | pyrogram.filters.voice
                                    | pyrogram.filters.animation
                                    | pyrogram.filters.document
                                    | pyrogram.filters.video_note
                            )
                )
            )
            self.bot.add_handler(
                CallbackQueryHandler(
                    self.callback_data,
                    filters=self.auth_filter
                )
            )
            self.bot.add_handler(
                MessageHandler(
                    self.process_error_message,
                    filters=self.auth_filter & ~(
                            pyrogram.filters.video
                            | pyrogram.filters.photo
                            | pyrogram.filters.audio
                            | pyrogram.filters.voice
                            | pyrogram.filters.animation
                            | pyrogram.filters.document
                            | pyrogram.filters.video_note
                    ) & (
                                lambda client, m: m.chat.id not in self.pending_tasks
                            )
                )
            )
            self.is_bot_running: bool = True
            await self.send_message_to_bot(text='/start')
            return f'🤖 Bot started successfully ({BotButton.CLOSE_NOTICE if self.gc.config.get(BotCallbackText.NOTICE) else BotButton.OPEN_NOTICE}).'
        except AccessTokenInvalid as e:
            self.is_bot_running: bool = False
            return f'🤖 Bot failed to start: invalid bot_token. {_t(KeyWord.REASON)}: "{e}"'
        except Exception as e:
            self.is_bot_running: bool = False
            return f'🤖 Bot failed to start. {_t(KeyWord.REASON)}: "{e}"'

    async def send_message_to_bot(self, text: str, catch: bool = False):
        try:
            bot_username = getattr(await self.bot.get_me(), 'username', None)
            if bot_username:
                return await self.user.send_message(
                    chat_id=bot_username,
                    text=text,
                    link_preview_options=Bot.LINK_PREVIEW_OPTIONS
                )
        except Exception as e:
            if catch:
                raise Exception(str(e))
            else:
                return e

    @staticmethod
    def update_text(
            right_link: set,
            invalid_link: set
    ) -> list:
        n = '\n'
        right_msg = f'{BotMessage.RIGHT}{n.join(sorted(right_link))}' if right_link else ''
        invalid_msg = f'{BotMessage.INVALID}{n.join(sorted(invalid_link))}{n}(See the terminal for details.)' if invalid_link else ''
        return safe_message(f'{right_msg}{n}{invalid_msg}')

    async def safe_edit_message(
            self, client: pyrogram.Client,
            message: pyrogram.types.Message,
            last_message_id: int,
            text: Union[str, List[str]],
            reply_markup: Union[pyrogram.types.InlineKeyboardMarkup, None] = None
    ) -> Union[pyrogram.types.Message, None]:
        while True:
            try:
                if isinstance(text, list):
                    last_message: pyrogram.types.Message = await self.safe_process_message(
                        client=client,
                        message=message,
                        last_message_id=last_message_id,
                        text=text,
                        reply_markup=reply_markup
                    )
                    return last_message
                elif isinstance(text, str):
                    await client.edit_message_text(
                        chat_id=message.from_user.id,
                        message_id=last_message_id,
                        text=text,
                        link_preview_options=Bot.LINK_PREVIEW_OPTIONS,
                        reply_markup=reply_markup
                    )
                    return None
            except MessageNotModified:
                return None
            except (FloodWait, FloodPremiumWait) as e:
                amount = e.value
                ConnectionStatus.enter_flood(
                    f'[{self.bot.name}] Message edits are being rate-limited; wait {amount} seconds before retrying.'
                )
                await asyncio.sleep(amount)
                ConnectionStatus.leave_flood()
            except Exception:
                raise

    async def send_rich_table(self, message: pyrogram.types.Message, chunks: list) -> None:
        """Send Markdown chunks of a statistics table to the user as rich-text messages through the bot.

        ``chunks`` is a list of Markdown strings: edit the original message with the first chunk (so a keyboard can be attached),
        then send the remaining chunks as new messages to avoid the rich-text message length limit.
        """
        if self.bot is None or not chunks:
            return None
        chat_id: int = message.chat.id
        first, *rest = chunks
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message.id,
                rich_message=pyrogram.types.InputRichMessage(markdown=first)
            )
        except Exception as e:
            log.error(f'Failed to send the first statistics table chunk through the bot, {_t(KeyWord.REASON)}: "{e}"')
        for index, chunk in enumerate(rest, start=2):
            try:
                await self.bot.send_rich_message(
                    chat_id=chat_id,
                    rich_message=pyrogram.types.InputRichMessage(markdown=chunk)
                )
            except Exception as e:
                log.error(f'Failed to send statistics table chunk {index} through the bot, {_t(KeyWord.REASON)}: "{e}"')


class KeyboardButton:
    def __init__(self, callback_query: pyrogram.types.CallbackQuery):
        self.callback_query = callback_query

    async def choice_export_table_button(
            self,
            choice: Union[BotCallbackText, str]
    ) -> None:
        export_callback_data: str = ''
        if choice == BotCallbackText.EXPORT_LINK_TABLE:
            export_callback_data = BotCallbackText.EXPORT_LINK_TABLE
        elif choice == BotCallbackText.EXPORT_COUNT_TABLE:
            export_callback_data = BotCallbackText.EXPORT_COUNT_TABLE
        elif choice == BotCallbackText.EXPORT_UPLOAD_TABLE:
            export_callback_data = BotCallbackText.EXPORT_UPLOAD_TABLE
        try:
            await self.callback_query.message.edit_reply_markup(InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text=BotButton.EXPORT_TABLE,
                            callback_data=export_callback_data
                        ),
                        InlineKeyboardButton(
                            text=BotButton.RESELECT,
                            callback_data=BotCallbackText.BACK_TABLE
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BotButton.HELP_PAGE,
                            callback_data=BotCallbackText.BACK_HELP
                        )
                    ]
                ]
            )
            )
        except MessageNotModified:
            pass

    async def toggle_setting_button(
            self,
            global_config: dict,
            user_config: dict
    ) -> None:
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            text=BotButton.CLOSE_NOTICE if global_config.get(
                                BotCallbackText.NOTICE) else BotButton.OPEN_NOTICE,
                            callback_data=BotCallbackText.NOTICE
                        ),
                        InlineKeyboardButton(
                            text=BotButton.EXPORT_TABLE,
                            callback_data=BotCallbackText.EXPORT_TABLE
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BotButton.CLOSE_EXIT_SHUTDOWN if user_config.get(
                                'is_shutdown') else BotButton.OPEN_EXIT_SHUTDOWN,
                            callback_data=BotCallbackText.SHUTDOWN
                        ),
                        InlineKeyboardButton(
                            text=BotButton.FORWARD_SETTING,
                            callback_data=BotCallbackText.FORWARD_SETTING
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BotButton.DOWNLOAD_SETTING,
                            callback_data=BotCallbackText.DOWNLOAD_SETTING
                        ),
                        InlineKeyboardButton(
                            text=BotButton.UPLOAD_SETTING,
                            callback_data=BotCallbackText.UPLOAD_SETTING
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text=BotButton.HELP_PAGE,
                            callback_data=BotCallbackText.BACK_HELP
                        )
                    ]
                ])
            )
        except MessageNotModified:
            pass
        except Exception as e:
            await self.callback_query.message.reply_text('Failed to update the button state.\n(See the terminal for details.)')
            log.error(f'Failed to toggle the button state, {_t(KeyWord.REASON)}: "{e}"')

    async def toggle_upload_setting_button(
            self,
            global_config: dict
    ):
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.CLOSE_UPLOAD_DOWNLOAD if global_config.get('upload').get(
                                    'download_upload') else BotButton.OPEN_UPLOAD_DOWNLOAD,
                                callback_data=BotCallbackText.UPLOAD_DOWNLOAD
                            ),
                            InlineKeyboardButton(
                                text=BotButton.CLOSE_UPLOAD_DOWNLOAD_DELETE if global_config.get('upload').get(
                                    'delete') else BotButton.OPEN_UPLOAD_DOWNLOAD_DELETE,
                                callback_data=BotCallbackText.UPLOAD_DOWNLOAD_DELETE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.RETURN,
                                callback_data=BotCallbackText.SETTING
                            )
                        ]
                    ]
                )
            )
        except MessageNotModified:
            pass

    async def toggle_download_setting_button(
            self,
            user_config: dict
    ):
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.VIDEO_ON if DownloadType.VIDEO in user_config.get(
                                    'download_type') else BotButton.VIDEO_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_VIDEO
                            ),
                            InlineKeyboardButton(
                                text=BotButton.PHOTO_ON if DownloadType.PHOTO in user_config.get(
                                    'download_type') else BotButton.PHOTO_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_PHOTO
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.AUDIO_ON if DownloadType.AUDIO in user_config.get(
                                    'download_type') else BotButton.AUDIO_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_AUDIO
                            ),
                            InlineKeyboardButton(
                                text=BotButton.VOICE_ON if DownloadType.VOICE in user_config.get(
                                    'download_type') else BotButton.VOICE_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_VOICE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.ANIMATION_ON if DownloadType.ANIMATION in user_config.get(
                                    'download_type') else BotButton.ANIMATION_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_ANIMATION
                            ),
                            InlineKeyboardButton(
                                text=BotButton.DOCUMENT_ON if DownloadType.DOCUMENT in user_config.get(
                                    'download_type') else BotButton.DOCUMENT_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_DOCUMENT
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.VIDEO_NOTE_ON if DownloadType.VIDEO_NOTE in user_config.get(
                                    'download_type') else BotButton.VIDEO_NOTE_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_VIDEO_NOTE
                            ),
                            InlineKeyboardButton(
                                text=BotButton.LIVE_PHOTO_ON if DownloadType.LIVE_PHOTO in user_config.get(
                                    'download_type') else BotButton.LIVE_PHOTO_OFF,
                                callback_data=BotCallbackText.TOGGLE_DOWNLOAD_LIVE_PHOTO
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.RETURN,
                                callback_data=BotCallbackText.SETTING
                            )
                        ]
                    ]
                )
            )
        except MessageNotModified:
            pass

    async def toggle_forward_setting_button(
            self,
            global_config: dict
    ):
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.VIDEO_ON if global_config.get('forward_type').get(
                                    'video') else BotButton.VIDEO_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_VIDEO
                            ),
                            InlineKeyboardButton(
                                text=BotButton.PHOTO_ON if global_config.get('forward_type').get(
                                    'photo') else BotButton.PHOTO_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_PHOTO
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.AUDIO_ON if global_config.get('forward_type').get(
                                    'audio') else BotButton.AUDIO_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_AUDIO
                            ),
                            InlineKeyboardButton(
                                text=BotButton.VOICE_ON if global_config.get('forward_type').get(
                                    'voice') else BotButton.VOICE_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_VOICE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.ANIMATION_ON if global_config.get('forward_type').get(
                                    'animation') else BotButton.ANIMATION_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_ANIMATION
                            ),
                            InlineKeyboardButton(
                                text=BotButton.DOCUMENT_ON if global_config.get('forward_type').get(
                                    'document') else BotButton.DOCUMENT_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_DOCUMENT
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.TEXT_ON if global_config.get('forward_type').get(
                                    'text') else BotButton.TEXT_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_TEXT
                            ),
                            InlineKeyboardButton(
                                text=BotButton.VIDEO_NOTE_ON if global_config.get('forward_type').get(
                                    'video_note') else BotButton.VIDEO_NOTE_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_VIDEO_NOTE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.LIVE_PHOTO_ON if global_config.get('forward_type').get(
                                    'live_photo') else BotButton.LIVE_PHOTO_OFF,
                                callback_data=BotCallbackText.TOGGLE_FORWARD_LIVE_PHOTO
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.RETURN,
                                callback_data=BotCallbackText.SETTING
                            )
                        ]
                    ]
                )
            )
        except MessageNotModified:
            pass

    @staticmethod
    def toggle_download_chat_type_filter_button(
            filter_config: dict
    ):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=BotButton.VIDEO_ON if
                        filter_config['download_type'][
                            DownloadType.VIDEO] else BotButton.VIDEO_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO
                    ),
                    InlineKeyboardButton(
                        text=BotButton.PHOTO_ON if
                        filter_config['download_type'][
                            DownloadType.PHOTO] else BotButton.PHOTO_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_PHOTO
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.AUDIO_ON if
                        filter_config['download_type'][
                            DownloadType.AUDIO] else BotButton.AUDIO_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_AUDIO
                    ),
                    InlineKeyboardButton(
                        text=BotButton.VOICE_ON if
                        filter_config['download_type'][
                            DownloadType.VOICE] else BotButton.VOICE_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VOICE
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.ANIMATION_ON if
                        filter_config['download_type'][
                            DownloadType.ANIMATION] else BotButton.ANIMATION_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_ANIMATION
                    ),
                    InlineKeyboardButton(
                        text=BotButton.DOCUMENT_ON if
                        filter_config['download_type'][
                            DownloadType.DOCUMENT] else BotButton.DOCUMENT_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_DOCUMENT
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.VIDEO_NOTE_ON if
                        filter_config['download_type'][
                            DownloadType.VIDEO_NOTE] else BotButton.VIDEO_NOTE_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO_NOTE
                    ),
                    InlineKeyboardButton(
                        text=BotButton.LIVE_PHOTO_ON if
                        filter_config['download_type'][
                            DownloadType.LIVE_PHOTO] else BotButton.LIVE_PHOTO_OFF,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_LIVE_PHOTO
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.RETURN,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_FILTER
                    )
                ]
            ]
        )

    async def toggle_table_button(
            self,
            config: dict,
            choice: Union[str, None] = None
    ) -> None:
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.CLOSE_LINK_TABLE if config.get(
                                    'export_table').get('link') else BotButton.OPEN_LINK_TABLE,
                                callback_data=BotCallbackText.TOGGLE_LINK_TABLE
                            ),
                            InlineKeyboardButton(
                                text=BotButton.CLOSE_COUNT_TABLE if config.get(
                                    'export_table').get('count') else BotButton.OPEN_COUNT_TABLE,
                                callback_data=BotCallbackText.TOGGLE_COUNT_TABLE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.CLOSE_UPLOAD_TABLE if config.get(
                                    'export_table').get('upload') else BotButton.OPEN_UPLOAD_TABLE,
                                callback_data=BotCallbackText.TOGGLE_UPLOAD_TABLE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.RETURN,
                                callback_data=BotCallbackText.SETTING
                            )
                        ]
                    ]
                )
            )
        except MessageNotModified:
            pass
        except Exception as _e:
            if choice:
                if choice == 'link':
                    prompt: str = 'link'
                elif choice == 'count':
                    prompt: str = 'count'
                elif choice == 'upload':
                    prompt: str = 'upload'
                else:
                    prompt: str = ''
                await self.callback_query.message.reply_text(
                    f'Failed to update the export setting for the {prompt} table.\n(See the terminal for details.)'
                )
                log.error(f'Failed to update the export setting for the {prompt} table. {_t(KeyWord.REASON)}: "{_e}"')
            else:
                log.error(f'Failed to update the table export setting. {_t(KeyWord.REASON)}: "{_e}"')

    async def back_table_button(self):
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.RESELECT,
                                callback_data=BotCallbackText.BACK_TABLE
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                text=BotButton.HELP_PAGE,
                                callback_data=BotCallbackText.BACK_HELP
                            )
                        ]
                    ]
                ))
        except MessageNotModified:
            pass

    async def task_assign_button(self):
        try:
            await self.callback_query.message.edit_reply_markup(
                InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                text=BotButton.TASK_ASSIGN,
                                callback_data=BotCallbackText.NULL
                            )
                        ]
                    ]
                )
            )
        except MessageNotModified:
            pass

    @staticmethod
    def restrict_forward_button():
        return (
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            BotButton.DOWNLOAD,
                            callback_data=BotCallbackText.DOWNLOAD
                        ),
                        InlineKeyboardButton(
                            BotButton.DOWNLOAD_UPLOAD,
                            callback_data=BotCallbackText.DOWNLOAD_UPLOAD
                        ),
                    ]
                ]
            )
        )

    @staticmethod
    def single_button(text: str, callback_data: str):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=text,
                        callback_data=callback_data
                    )
                ]
            ]
        )

    @staticmethod
    def download_chat_filter_button(
            include_comment: bool
    ):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=BotButton.DATE_RANGE_SETTING,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER
                    ),
                    InlineKeyboardButton(
                        text=BotButton.DOWNLOAD_DTYPE_SETTING,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_DTYPE_FILTER
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.KEYWORD_FILTER_SETTING,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_KEYWORD_FILTER
                    ),
                    InlineKeyboardButton(
                        text=BotButton.INCLUDE_COMMENT if include_comment else BotButton.IGNORE_COMMENT,
                        callback_data=BotCallbackText.TOGGLE_DOWNLOAD_CHAT_COMMENT
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.EXECUTE_TASK,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_ID
                    ),
                    InlineKeyboardButton(
                        text=BotButton.CANCEL_TASK,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL
                    )
                ]
            ]
        )

    @staticmethod
    def filter_date_range_button():
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text=BotButton.SELECT_START_DATE,
                        callback_data=BotCallbackText.FILTER_START_DATE
                    ),
                    InlineKeyboardButton(
                        text=BotButton.SELECT_END_DATE,
                        callback_data=BotCallbackText.FILTER_END_DATE
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.RETURN,
                        callback_data=BotCallbackText.DOWNLOAD_CHAT_FILTER
                    )
                ]
            ]
        )

    async def calendar_keyboard(
            self,
            dtype: Union[CalenderKeyboard, str],
            year: Optional[int] = datetime.datetime.now().year,
            month: Optional[int] = datetime.datetime.now().month,
            selected_date: Optional[str] = None,
            chat_id=None
    ):
        keyboard: list = []
        prev_month: int = month - 1 if month > 1 else 12
        prev_year: int = year if month > 1 else year - 1
        next_month: int = month + 1 if month < 12 else 1
        next_year: int = year if month < 12 else year + 1
        if dtype == CalenderKeyboard.START_TIME_BUTTON:
            _dtype = 'start'
        elif dtype == CalenderKeyboard.END_TIME_BUTTON:
            _dtype = 'end'
        else:
            return None
        nav_row = [
            InlineKeyboardButton('◀️', callback_data=f'time_dec_month_{_dtype}_{prev_year}_{prev_month}'),
            # The clickable year-month button in the middle opens the year-selection keyboard, initially selecting the calendar's current year.
            InlineKeyboardButton(
                f'{year}-{month:02d}',
                callback_data=f'select_year_{_dtype}_{year}_{month}_{year}'
            ),
            InlineKeyboardButton('▶️', callback_data=f'time_inc_month_{_dtype}_{next_year}_{next_month}')
        ]
        keyboard.append(nav_row)

        week_days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        week_row = [InlineKeyboardButton(day, callback_data=BotCallbackText.NULL) for day in week_days]
        keyboard.append(week_row)

        cal = calendar.monthcalendar(year, month)
        # If the selected date is in the displayed year and month, mark that day with a green button.
        selected_day: Optional[int] = None
        if selected_date:
            selected_dt = datetime.datetime.strptime(selected_date, '%Y-%m-%d %H:%M:%S')
            if selected_dt.year == year and selected_dt.month == month:
                selected_day = selected_dt.day
        for week in cal:
            row = []
            for day in week:
                if day == 0:
                    row.append(InlineKeyboardButton(' ', callback_data=BotCallbackText.NULL))
                else:
                    date_str = f'{year}-{month:02d}-{day:02d} 00:00:00'
                    day_style = pyrogram.enums.ButtonStyle.SUCCESS if day == selected_day else pyrogram.enums.ButtonStyle.DEFAULT
                    row.append(InlineKeyboardButton(
                        text=str(day),
                        callback_data=f'set_specific_time_{_dtype}_{date_str}',
                        style=day_style
                    ))
            keyboard.append(row)

        keyboard.append(
            [
                InlineKeyboardButton(
                    text=BotButton.CONFIRM_AND_RETURN,
                    callback_data=BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER
                ),
                InlineKeyboardButton(
                    text=BotButton.CANCEL_TASK,
                    callback_data=BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL
                )
            ]
        )
        markup = InlineKeyboardMarkup(keyboard)
        # Attach the task identity only when chat_id is provided, so other uses of this calendar are unaffected.
        if chat_id is not None:
            markup = attach_task(markup, chat_id)
        try:
            await self.callback_query.message.edit_reply_markup(markup)
        except MessageNotModified:
            pass

    async def year_keyboard(
            self,
            dtype: Union[CalenderKeyboard, str],
            year: int,
            month: int,
            selected_year: int,
            chat_id=None
    ):
        # Center the year keyboard on year and show 12 years (six earlier and five later); the arrow buttons page through 12 years at a time.
        # selected_year is the currently selected year; paging changes only the displayed range, not the selection.
        keyboard: list = []
        start_year: int = year - 6
        end_year: int = start_year + 11
        if dtype == CalenderKeyboard.START_TIME_BUTTON:
            _dtype = 'start'
        elif dtype == CalenderKeyboard.END_TIME_BUTTON:
            _dtype = 'end'
        else:
            return None
        nav_row = [
            InlineKeyboardButton('◀️', callback_data=f'select_year_{_dtype}_{year - 12}_{month}_{selected_year}'),
            InlineKeyboardButton(f'{start_year}-{end_year}', callback_data=BotCallbackText.NULL),
            InlineKeyboardButton('▶️', callback_data=f'select_year_{_dtype}_{year + 12}_{month}_{selected_year}')
        ]
        keyboard.append(nav_row)
        for row_start in range(start_year, end_year + 1, 4):
            row = []
            for _year in range(row_start, row_start + 4):
                # Mark the selected year with a green button to distinguish it from the others.
                year_style = pyrogram.enums.ButtonStyle.SUCCESS if _year == selected_year else pyrogram.enums.ButtonStyle.DEFAULT
                row.append(InlineKeyboardButton(
                    text=str(_year),
                    callback_data=f'set_year_{_dtype}_{_year}_{month}',
                    style=year_style
                ))
            keyboard.append(row)
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=BotButton.RETURN,
                    # Return to the selected year; paging does not change the selection.
                    callback_data=f'set_year_{_dtype}_{selected_year}_{month}'
                ),
                InlineKeyboardButton(
                    text=BotButton.CANCEL_TASK,
                    callback_data=BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL
                )
            ]
        )
        markup = InlineKeyboardMarkup(keyboard)
        # Attach the task identity only when chat_id is provided, so other uses of this calendar are unaffected.
        if chat_id is not None:
            markup = attach_task(markup, chat_id)
        try:
            await self.callback_query.message.edit_reply_markup(markup)
        except MessageNotModified:
            pass

    @staticmethod
    def time_keyboard(
            dtype: Union[CalenderKeyboard, str],
            date: str,
            adjust_step: Optional[int] = 1
    ):
        dt = datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S')
        _dtype = dtype if isinstance(dtype, str) else 'start' if dtype == CalenderKeyboard.START_TIME_BUTTON else 'end'
        hour, minute, second = 'hour', 'minute', 'second'

        def _get_updated_time(field: str, delta: int) -> str:
            new_dt = dt.replace(
                hour=(dt.hour + delta) % 24 if field == hour else dt.hour,
                minute=(dt.minute + delta) % 60 if field == minute else dt.minute,
                second=(dt.second + delta) % 60 if field == second else dt.second
            )
            return new_dt.strftime('%Y-%m-%d %H:%M:%S')

        time_keyboard = [
            [
                InlineKeyboardButton(
                    text=f'Step: {adjust_step}',
                    callback_data=f'adjust_step_{dtype}_{adjust_step}'
                )
            ],
            [
                InlineKeyboardButton(
                    text='◀️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(hour, -adjust_step)}'
                ),
                InlineKeyboardButton(
                    text='Hr', callback_data=BotCallbackText.NULL
                ),
                InlineKeyboardButton(
                    text='▶️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(hour, adjust_step)}'
                )
            ],
            [
                InlineKeyboardButton(
                    text='◀️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(minute, -adjust_step)}'
                ),
                InlineKeyboardButton(
                    text='Min', callback_data=BotCallbackText.NULL
                ),
                InlineKeyboardButton(
                    text='▶️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(minute, adjust_step)}'
                )
            ],
            [
                InlineKeyboardButton(
                    text='◀️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(second, -adjust_step)}'
                ),
                InlineKeyboardButton(
                    text='Sec', callback_data=BotCallbackText.NULL
                ),
                InlineKeyboardButton(
                    text='▶️',
                    callback_data=f'set_time_{_dtype}_{_get_updated_time(second, adjust_step)}'
                )
            ],
            [
                InlineKeyboardButton(
                    text=BotButton.CONFIRM_AND_RETURN,
                    callback_data=BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER
                ),
                InlineKeyboardButton(
                    text=BotButton.CANCEL_TASK,
                    callback_data=BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL
                )
            ]
        ]

        return InlineKeyboardMarkup(time_keyboard)

    @staticmethod
    def keyword_filter_button(
            adding_keywords: Optional[list] = None
    ):
        """Keyword-filter settings button."""
        if adding_keywords:
            keyword_buttons = [
                [
                    InlineKeyboardButton(
                        text=BotButton.INPUT_KEYWORD,
                        callback_data=BotCallbackText.NULL
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.CONFIRM_KEYWORD,
                        callback_data=BotCallbackText.CONFIRM_KEYWORD
                    ),
                    InlineKeyboardButton(
                        text=BotButton.CANCEL,
                        callback_data=BotCallbackText.CANCEL_KEYWORD_INPUT
                    )
                ]
            ]
        else:
            keyword_buttons = [
                [
                    InlineKeyboardButton(
                        text=BotButton.INPUT_KEYWORD,
                        callback_data=BotCallbackText.NULL
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=BotButton.RETURN,
                        callback_data=BotCallbackText.CANCEL_KEYWORD_INPUT
                    )
                ]
            ]
        return InlineKeyboardMarkup(keyword_buttons)


class CallbackData:
    def __init__(self, data: Union[dict, None] = None):
        self.data: Union[dict, None] = data


@dataclass
class CallbackContext:
    """Callback-processing context that groups objects needed by handlers, avoiding closure capture."""
    downloader: 'TelegramRestrictedMediaDownloader'  # noqa.
    client: pyrogram.Client
    query: CallbackQuery
    kb: KeyboardButton
    data: str


class CallbackHandler(ABC):
    """Base class for callback handlers; subclasses declare exact/prefixes match sets and implement handle."""
    exact: tuple = ()
    prefixes: tuple = ()

    def match(self, data: str) -> bool:
        return data in self.exact or data.startswith(self.prefixes)

    @abstractmethod
    async def handle(self, ctx: CallbackContext) -> None:
        ...


class NoticeHandler(CallbackHandler):
    exact = (BotCallbackText.NOTICE,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        try:
            downloader.gc.config[BotCallbackText.NOTICE] = not downloader.gc.config.get(BotCallbackText.NOTICE)
            downloader.gc.save_config(downloader.gc.config)
            n_s = 'enabled' if downloader.gc.config.get(BotCallbackText.NOTICE) else 'disabled'
            n_p = f'The startup notice has been {n_s}.'
            log.info(n_p)
            console.log(n_p, style='#FF4689')
            await kb.toggle_setting_button(global_config=downloader.gc.config, user_config=downloader.app.config)
        except Exception as e:
            await query.message.reply_text('Failed to update bot message notifications.\n(See the terminal for details.)')
            log.error(f'Failed to enable or disable bot message notifications, {_t(KeyWord.REASON)}: "{e}"')


class PayHandler(CallbackHandler):
    exact = (BotCallbackText.PAY,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        client = ctx.client
        query = ctx.query
        res = await downloader.send_pay_qr(
            client=client,
            chat_id=query.from_user.id,
            load_name='payment QR code'
        )
        MetaData.pay()
        if res:
            msg = '✅\nThe payment QR code has been sent to your terminal. Thank you for your support!'
        else:
            msg = '✅\nThe payment QR code has been sent to your terminal and this chat. Thank you for your support!'
        await query.message.reply_text(msg)


class BackHandler(CallbackHandler):
    exact = (BotCallbackText.BACK_HELP, BotCallbackText.BACK_TABLE)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        if ctx.data == BotCallbackText.BACK_HELP:
            meta = await downloader.help()
            await query.message.edit_text(
                rich_message=pyrogram.types.InputRichMessage(
                    markdown=meta.get('text'),
                    skip_entity_detection=True
                ),
                reply_markup=meta.get('keyboard')
            )
        elif ctx.data == BotCallbackText.BACK_TABLE:
            meta = await downloader.table()
            await query.message.edit_text(meta.get('text'))
            await query.message.edit_reply_markup(meta.get('keyboard'))


class TaskAssignHandler(CallbackHandler):
    exact = (BotCallbackText.DOWNLOAD, BotCallbackText.DOWNLOAD_UPLOAD)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        kb = ctx.kb
        query = ctx.query
        if not isinstance(downloader.cd.data, dict):
            return None
        meta = downloader.cd.data.copy()
        downloader.cd.data = None
        origin_link = meta.get('origin_link')
        target_link = meta.get('target_link')
        start_id = meta.get('start_id')
        end_id = meta.get('end_id')
        # Send feedback to the user who clicked (created) the task, using the message they clicked as the response carrier.
        feedback = query.message
        feedback.from_user = query.from_user
        feedback.text = f'/download {origin_link} {start_id} {end_id}'
        if ctx.data == BotCallbackText.DOWNLOAD:
            await downloader.get_download_link_from_bot(client=downloader.last_client, message=feedback)
        elif ctx.data == BotCallbackText.DOWNLOAD_UPLOAD:
            await downloader.get_download_link_from_bot(
                client=downloader.last_client,
                message=feedback,
                with_upload={
                    'link': target_link,
                    'file_name': None,
                    'with_delete': downloader.gc.upload_delete,
                    'send_as_media_group': True,
                    'owner': query.from_user.id
                }
            )
        await kb.task_assign_button()


class ListenInfoHandler(CallbackHandler):
    exact = (BotCallbackText.LOOKUP_LISTEN_INFO,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        # Edit the current message to show listener information instead of sending another message (also avoiding restrictions on messaging bot chats).
        try:
            await downloader.listen_info(
                client=downloader.bot,
                message=query.message,
                target=query.from_user.id,
                edit_message=query.message
            )
        except Exception as e:
            await query.message.reply_text('Failed to display listening information.\n(See the terminal for details.)')
            log.error(f'Failed to send the command to view listener information, {_t(KeyWord.REASON)}: "{e}"')


class LookupAuthInfoHandler(CallbackHandler):
    exact = (BotCallbackText.LOOKUP_AUTH_INFO,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        # Edit the current message to show the authorized-user list instead of sending another one.
        try:
            await downloader.show_authorized_users(
                client=downloader.bot,
                message=query.message,
                target=query.from_user.id,
                edit_message=query.message
            )
        except Exception as e:
            await query.message.reply_text('Failed to display the authorized-user list.\n(See the terminal for details.)')
            log.error(f'Failed to send the command to view authorized users, {_t(KeyWord.REASON)}: "{e}"')


class ViewAuthListHandler(CallbackHandler):
    exact = (BotCallbackText.VIEW_AUTH_LIST,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        # Edit the current message to show the authorized-user list instead of sending another one.
        try:
            await downloader.show_authorized_users(
                client=downloader.bot,
                message=query.message,
                target=query.from_user.id,
                edit_message=query.message
            )
        except Exception as e:
            await query.message.reply_text('Failed to display the authorized-user list.\n(See the terminal for details.)')
            log.error(f'Failed to send the command to view authorized users, {_t(KeyWord.REASON)}: "{e}"')


class AddAuthHandler(CallbackHandler):
    exact = (BotCallbackText.AUTH,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        # Only root can initiate authorization; reject other users immediately.
        if not downloader.root or query.from_user.id != downloader.root[0]:
            await query.answer('⛔ Only `root` can use this action.', show_alert=True)
            return None
        # Open input mode and prompt root for the user ID or @username to authorize, with an option to cancel.
        await query.message.edit_text(
            text='➕ Enter the user `ID` or `@username` to authorize:',
            reply_markup=KeyboardButton.single_button(
                text='🔙 Cancel',
                callback_data=BotCallbackText.CANCEL_AUTH_INPUT
            )
        )
        downloader.add_auth_mode_handler(
            chat_id=query.from_user.id,
            callback_query=query,
            enable=True
        )


class CancelAuthInputHandler(CallbackHandler):
    exact = (BotCallbackText.CANCEL_AUTH_INPUT,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        # Close add-authorized-user input mode; safe for any user because it is a no-op if no handler exists for them.
        downloader.add_auth_mode_handler(
            chat_id=query.from_user.id,
            callback_query=query,
            enable=False
        )
        try:
            await query.message.edit_text(
                text='🔐 Authorized user management',
                reply_markup=downloader.menu_keyboard('auth')
            )
        except MessageNotModified:
            pass


class ShutdownHandler(CallbackHandler):
    exact = (BotCallbackText.SHUTDOWN,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        try:
            downloader.app.config['is_shutdown'] = not downloader.app.config.get('is_shutdown')
            downloader.app.save_config(downloader.app.config)
            s_s = 'enabled' if downloader.app.config.get('is_shutdown') else 'disabled'
            s_p = f'Shutdown on exit has been {s_s}.'
            log.info(s_p)
            console.log(s_p, style='#FF4689')
            await kb.toggle_setting_button(global_config=downloader.gc.config, user_config=downloader.app.config)
        except Exception as e:
            await query.message.reply_text('Failed to update shutdown-on-exit.\n(See the terminal for details.)')
            log.error(f'Failed to enable or disable automatic shutdown, {_t(KeyWord.REASON)}: "{e}"')


class SettingsHandler(CallbackHandler):
    exact = (
        BotCallbackText.SETTING,
        BotCallbackText.EXPORT_TABLE,
        BotCallbackText.DOWNLOAD_SETTING,
        BotCallbackText.UPLOAD_SETTING,
        BotCallbackText.FORWARD_SETTING
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        kb = ctx.kb
        if ctx.data == BotCallbackText.SETTING:
            await kb.toggle_setting_button(global_config=downloader.gc.config, user_config=downloader.app.config)
        elif ctx.data == BotCallbackText.EXPORT_TABLE:
            await kb.toggle_table_button(config=downloader.gc.config)
        elif ctx.data == BotCallbackText.DOWNLOAD_SETTING:
            await kb.toggle_download_setting_button(user_config=downloader.app.config)
        elif ctx.data == BotCallbackText.UPLOAD_SETTING:
            await kb.toggle_upload_setting_button(global_config=downloader.gc.config)
        elif ctx.data == BotCallbackText.FORWARD_SETTING:
            await kb.toggle_forward_setting_button(global_config=downloader.gc.config)


class TableHandler(CallbackHandler):
    exact = (
        BotCallbackText.LINK_TABLE,
        BotCallbackText.COUNT_TABLE,
        BotCallbackText.UPLOAD_TABLE,
        BotCallbackText.TOGGLE_LINK_TABLE,
        BotCallbackText.TOGGLE_COUNT_TABLE,
        BotCallbackText.TOGGLE_UPLOAD_TABLE,
        BotCallbackText.EXPORT_LINK_TABLE,
        BotCallbackText.EXPORT_COUNT_TABLE,
        BotCallbackText.EXPORT_UPLOAD_TABLE
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        data = ctx.data
        if data in (BotCallbackText.LINK_TABLE, BotCallbackText.COUNT_TABLE, BotCallbackText.UPLOAD_TABLE):
            prompt_string = ''
            false_text = ''
            choice = ''
            res = None
            if data == BotCallbackText.LINK_TABLE:
                prompt_string = 'Link statistics'
                false_text = '🌫️ No links to include in the statistics.'
                choice = BotCallbackText.EXPORT_LINK_TABLE
                res = downloader.app.print_link_table(DownloadTask.TASKS)
            elif data == BotCallbackText.COUNT_TABLE:
                prompt_string = 'Count statistics'
                false_text = '🌫️ There are no downloads yet.'
                choice = BotCallbackText.EXPORT_COUNT_TABLE
                res = downloader.app.print_count_table()
            elif data == BotCallbackText.UPLOAD_TABLE:
                prompt_string = 'Upload statistics'
                false_text = '🌫️ There are no uploads yet.'
                choice = BotCallbackText.EXPORT_UPLOAD_TABLE
                res = downloader.app.print_upload_table(UploadTask.TASKS)
            if res:
                await downloader.send_rich_table(message=query.message, chunks=res)
                await kb.choice_export_table_button(choice=choice)
                return None
            elif res is False:
                await query.message.edit_text(false_text)
            else:
                await query.message.edit_text(
                    f'❌ Failed to print `{prompt_string}`.\n(See the terminal for details.)')
            await kb.back_table_button()
        elif data in (
                BotCallbackText.TOGGLE_LINK_TABLE,
                BotCallbackText.TOGGLE_COUNT_TABLE,
                BotCallbackText.TOGGLE_UPLOAD_TABLE
        ):
            if data == BotCallbackText.TOGGLE_LINK_TABLE:
                await self.__toggle_export_table(ctx, 'link')
            elif data == BotCallbackText.TOGGLE_COUNT_TABLE:
                await self.__toggle_export_table(ctx, 'count')
            elif data == BotCallbackText.TOGGLE_UPLOAD_TABLE:
                await self.__toggle_export_table(ctx, 'upload')
        elif data in (
                BotCallbackText.EXPORT_LINK_TABLE,
                BotCallbackText.EXPORT_COUNT_TABLE,
                BotCallbackText.EXPORT_UPLOAD_TABLE
        ):
            prompt_string = ''
            folder = ''
            res = False
            if data == BotCallbackText.EXPORT_LINK_TABLE:
                prompt_string = 'Link statistics'
                folder = 'DownloadRecordForm'
                res = downloader.app.print_link_table(link_tasks=DownloadTask.TASKS, export=True, only_export=True)
            elif data == BotCallbackText.EXPORT_COUNT_TABLE:
                prompt_string = 'Count statistics'
                folder = 'DownloadRecordForm'
                res = downloader.app.print_count_table(export=True, only_export=True)
            elif data == BotCallbackText.EXPORT_UPLOAD_TABLE:
                prompt_string = 'Upload statistics'
                folder = 'UploadRecordForm'
                res = downloader.app.print_upload_table(upload_tasks=UploadTask.TASKS, export=True, only_export=True)
            if res:
                folder = 'form' if is_docker() else folder
                await query.message.edit_text(
                    f'✅ `{prompt_string}` was printed in the terminal and exported as a table.\n(Check the `{folder}` folder in the TRMD directory.)')
            elif res is False:
                await query.message.edit_text('🌫️ There are no links to include in the statistics.')
            else:
                await query.message.edit_text(
                    f'❌ Failed to export `{prompt_string}`.\n(See the terminal for details.)')
            await kb.back_table_button()

    @staticmethod
    async def __toggle_export_table(ctx: CallbackContext, table_type: str) -> None:
        downloader = ctx.downloader
        kb = ctx.kb
        export_config = downloader.gc.config.get('export_table')
        export_config[table_type] = not export_config.get(table_type)
        if table_type == 'link':
            t_t = 'link statistics table'
        elif table_type == 'count':
            t_t = 'count statistics table'
        elif table_type == 'upload':
            t_t = 'upload statistics table'
        else:
            t_t = 'statistics table'
        s_t = 'enabled' if export_config.get(table_type) else 'disabled'
        t_p = f'Export {t_t} on exit is {s_t}.'
        console.log(t_p, style='#FF4689')
        log.info(t_p)
        downloader.gc.save_config(downloader.gc.config)
        await kb.toggle_table_button(config=downloader.gc.config, choice=table_type)


class UploadDownloadSettingHandler(CallbackHandler):
    exact = (BotCallbackText.UPLOAD_DOWNLOAD, BotCallbackText.UPLOAD_DOWNLOAD_DELETE)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        try:
            if ctx.data == BotCallbackText.UPLOAD_DOWNLOAD:
                self.__toggle_upload_param(downloader, 'download_upload')
            elif ctx.data == BotCallbackText.UPLOAD_DOWNLOAD_DELETE:
                self.__toggle_upload_param(downloader, 'delete')
            downloader.gc.save_config(downloader.gc.config)
            await kb.toggle_upload_setting_button(global_config=downloader.gc.config)
        except Exception as e:
            await query.message.reply_text('Failed to update upload settings.\n(See the terminal for details.)')
            log.error(f'Failed to update upload settings. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def __toggle_upload_param(downloader, param):
        current = downloader.gc.get_nesting_config(
            default_nesting=downloader.gc.default_upload_nesting, param='upload', nesting_param=param)
        downloader.gc.config.get('upload', downloader.gc.default_upload_nesting)[param] = not current
        u_s = 'disabled' if current else 'enabled'
        u_p = ''
        if param == 'delete':
            u_p = f'Download-and-upload for restricted forwarding, including deleting the local file after upload, is {u_s}.'
        elif param == 'download_upload':
            u_p = f'Download-and-upload for restricted forwarding is {u_s}.'
        console.log(u_p, style='#FF4689')
        log.info(u_p)


class DownloadTypeHandler(CallbackHandler):
    exact = (
        BotCallbackText.TOGGLE_DOWNLOAD_VIDEO,
        BotCallbackText.TOGGLE_DOWNLOAD_PHOTO,
        BotCallbackText.TOGGLE_DOWNLOAD_AUDIO,
        BotCallbackText.TOGGLE_DOWNLOAD_VOICE,
        BotCallbackText.TOGGLE_DOWNLOAD_ANIMATION,
        BotCallbackText.TOGGLE_DOWNLOAD_DOCUMENT,
        BotCallbackText.TOGGLE_DOWNLOAD_VIDEO_NOTE,
        BotCallbackText.TOGGLE_DOWNLOAD_LIVE_PHOTO
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        try:
            if ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_VIDEO:
                self.__toggle_download_type(downloader, 'video')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_PHOTO:
                self.__toggle_download_type(downloader, 'photo')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_AUDIO:
                self.__toggle_download_type(downloader, 'audio')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_VOICE:
                self.__toggle_download_type(downloader, 'voice')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_ANIMATION:
                self.__toggle_download_type(downloader, 'animation')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_DOCUMENT:
                self.__toggle_download_type(downloader, 'document')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_VIDEO_NOTE:
                self.__toggle_download_type(downloader, 'video_note')
            elif ctx.data == BotCallbackText.TOGGLE_DOWNLOAD_LIVE_PHOTO:
                self.__toggle_download_type(downloader, 'live_photo')
            downloader.app.config['download_type'] = downloader.app.download_type
            downloader.app.save_config(downloader.app.config)
            await kb.toggle_download_setting_button(downloader.app.config)
        except ValueError:
            await query.message.reply_text('⚠️ At least one download type must be selected.')
        except Exception as e:
            await query.message.reply_text('Failed to update download types.\n(See the terminal for details.)')
            log.error(f'Failed to update download types. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def __toggle_download_type(downloader, param):
        if param in downloader.app.download_type:
            if len(downloader.app.download_type) == 1:
                raise ValueError
            f_s = 'disabled'
            downloader.app.download_type.remove(param)
        else:
            f_s = 'enabled'
            downloader.app.download_type.append(param)
        f_p = f'{param} downloads {f_s}.'
        console.log(f_p, style='#FF4689')
        log.info(f_p)


class ForwardTypeHandler(CallbackHandler):
    exact = (
        BotCallbackText.TOGGLE_FORWARD_VIDEO,
        BotCallbackText.TOGGLE_FORWARD_PHOTO,
        BotCallbackText.TOGGLE_FORWARD_AUDIO,
        BotCallbackText.TOGGLE_FORWARD_VOICE,
        BotCallbackText.TOGGLE_FORWARD_ANIMATION,
        BotCallbackText.TOGGLE_FORWARD_DOCUMENT,
        BotCallbackText.TOGGLE_FORWARD_TEXT,
        BotCallbackText.TOGGLE_FORWARD_VIDEO_NOTE,
        BotCallbackText.TOGGLE_FORWARD_LIVE_PHOTO
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        try:
            if ctx.data == BotCallbackText.TOGGLE_FORWARD_VIDEO:
                self.__toggle_forward_type(downloader, 'video')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_PHOTO:
                self.__toggle_forward_type(downloader, 'photo')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_AUDIO:
                self.__toggle_forward_type(downloader, 'audio')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_VOICE:
                self.__toggle_forward_type(downloader, 'voice')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_ANIMATION:
                self.__toggle_forward_type(downloader, 'animation')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_DOCUMENT:
                self.__toggle_forward_type(downloader, 'document')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_TEXT:
                self.__toggle_forward_type(downloader, 'text')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_VIDEO_NOTE:
                self.__toggle_forward_type(downloader, 'video_note')
            elif ctx.data == BotCallbackText.TOGGLE_FORWARD_LIVE_PHOTO:
                self.__toggle_forward_type(downloader, 'live_photo')
            downloader.gc.save_config(downloader.gc.config)
            await kb.toggle_forward_setting_button(downloader.gc.config)
        except ValueError:
            await query.message.reply_text('⚠️ At least one forwarding type must be selected.')
        except Exception as e:
            await query.message.reply_text('Failed to update forwarding settings.\n(See the terminal for details.)')
            log.error(f'Failed to update forwarding settings. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def __toggle_forward_type(downloader, param):
        forward_type = downloader.gc.config.get('forward_type', downloader.gc.default_forward_type_nesting)
        status = downloader.gc.get_nesting_config(
            default_nesting=downloader.gc.default_forward_type_nesting, param='forward_type', nesting_param=param)
        if list(forward_type.values()).count(True) == 1 and status:
            raise ValueError
        forward_type[param] = not status
        f_s = 'disabled' if status else 'enabled'
        f_p = f'{param} forwarding {f_s}.'
        console.log(f_p, style='#FF4689')
        log.info(f_p)


class AuthUserHandler(CallbackHandler):
    prefixes = (BotCallbackText.REMOVE_AUTH_USER,)

    async def handle(self, ctx: CallbackContext) -> None:
        bot = ctx.downloader
        query = ctx.query
        uid = int(ctx.data.split('_')[-1])
        if uid not in bot.gc.authorized_users:
            await query.message.edit_text(
                text=f'User `{uid}` is no longer in the authorization list.',
                reply_markup=bot.menu_keyboard('auth'))
            return None
        # Hot-remove the user from the filter and configuration immediately, then persist the change.
        bot.gc.authorized_users.remove(uid)
        root_id = bot.root[0] if bot.root else None
        if uid != root_id and uid in bot.root:
            bot.root.remove(uid)
        bot.gc.config['authorized_users'] = bot.gc.authorized_users
        bot.gc.save_config(bot.gc.config)
        p = f'Removed authorized user: {uid}.'
        # Show the removal result in text and return to the authorized-user menu (add/remove, view, return).
        await query.message.edit_text(
            text=f'✅ Authorization removed for user `{uid}`.',
            reply_markup=bot.menu_keyboard('auth'))
        log.info(f'{p} Current authorized users: {bot.gc.authorized_users}')


class ListenRemoveHandler(CallbackHandler):
    exact = (BotCallbackText.REMOVE_LISTEN_FORWARD,)
    prefixes = (BotCallbackText.REMOVE_LISTEN_DOWNLOAD,)

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        data = ctx.data
        if data.startswith(BotCallbackText.REMOVE_LISTEN_DOWNLOAD):
            args = data.split()
            link = args[1]
            downloader.app.client.remove_handler(downloader.listen_download_chat.get(link))
            downloader.listen_download_chat.pop(link)
            downloader.listen_download_owner.pop(link, None)
            await query.message.edit_text(link)
            await query.message.edit_reply_markup(
                KeyboardButton.single_button(text=BotButton.ALREADY_REMOVE, callback_data=BotCallbackText.NULL))
            p = f'Removed download listener for channel link: "{link}".'
            console.log(p, style='#FF4689')
            log.info(f'{p} Current download listeners: {downloader.listen_download_chat}')
            return None
        if not isinstance(downloader.cd.data, dict):
            return None
        meta = downloader.cd.data.copy()
        downloader.cd.data = None
        link = meta.get('link')
        downloader.app.client.remove_handler(downloader.listen_forward_chat.get(link))
        downloader.listen_forward_chat.pop(link)
        downloader.listen_forward_owner.pop(link, None)
        m = link.split()
        joined = ' -> '.join(m)
        p = f'Removed forwarding listener for rule: "{joined}".'
        await query.message.edit_text(' ➡️ '.join(m))
        await query.message.edit_reply_markup(
            KeyboardButton.single_button(text=BotButton.ALREADY_REMOVE, callback_data=BotCallbackText.NULL))
        console.log(p, style='#FF4689')
        log.info(f'{p} Current forwarding listeners: {downloader.listen_forward_chat}')


class DownloadChatHandler(CallbackHandler):
    exact = (
        BotCallbackText.DOWNLOAD_CHAT_FILTER,
        BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER,
        BotCallbackText.DOWNLOAD_CHAT_DTYPE_FILTER,
        BotCallbackText.DOWNLOAD_CHAT_KEYWORD_FILTER,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_PHOTO,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_AUDIO,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VOICE,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_ANIMATION,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_DOCUMENT,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO_NOTE,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_LIVE_PHOTO,
        BotCallbackText.TOGGLE_DOWNLOAD_CHAT_COMMENT,
        BotCallbackText.DOWNLOAD_CHAT_ID,
        BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL,
        BotCallbackText.FILTER_START_DATE,
        BotCallbackText.FILTER_END_DATE,
        BotCallbackText.CONFIRM_KEYWORD,
        BotCallbackText.CANCEL_KEYWORD_INPUT
    )
    prefixes = (
        BotCallbackPrefix.TIME_INC,
        BotCallbackPrefix.TIME_DEC,
        BotCallbackPrefix.SET_TIME,
        BotCallbackPrefix.SET_SPECIFIC_TIME,
        BotCallbackPrefix.ADJUST_STEP,
        BotCallbackPrefix.SELECT_YEAR,
        BotCallbackPrefix.SET_YEAR,
        BotCallbackPrefix.DROP_KEYWORD,
        BotCallbackPrefix.IGNORE_KEYWORD
    )

    def match(self, data: str) -> bool:
        # Callback data has the form "{compressed callback data}|{channel ID}"; strip the task identity before matching.
        payload, _task = parse_task_callback(data)
        return (
                payload in self.exact
                or payload.startswith(self.prefixes)
                or payload == BotCallbackText.DOWNLOAD_CHAT_ID
        )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        kb = ctx.kb
        # Strip the attached task identity; callback data has the form "{compressed callback data}|{channel ID}".
        data, task = parse_task_callback(ctx.data)
        user_id = query.from_user.id
        # Callback data must include a task identity. If it is missing, this can only be an old button from before the upgrade; its task was cleared on restart, so ignore it.
        chat_id = resolve_chat_id(downloader.download_chat_filter, task)
        if chat_id is None or chat_id not in downloader.download_chat_filter:
            return None
        if data in (BotCallbackText.DOWNLOAD_CHAT_ID, BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL):
            downloader.adding_keywords.pop(chat_id, None)
            downloader.add_keyword_mode_handler(
                chat_id=user_id,
                task_chat_id=chat_id,
                callback_query=query,
                callback_prompt=partial(self.__filter_prompt, downloader, chat_id),
                enable=False
            )
            if data == BotCallbackText.DOWNLOAD_CHAT_ID:
                # When a task is executed, always log the download_chat configuration dictionary, whether or not keywords are used, to verify its filters.
                log.info(f'Running /download_chat with current filters: {downloader.download_chat_filter}.')
                # Clear the configuration only if dispatch succeeds (returns the matched links); on failure, retain it and the original menu for an easy retry.
                if await downloader.download_chat(chat_id=chat_id, callback_query=query) is not None:
                    self.__remove_chat_id(downloader, chat_id)
                    # Clean up only if the pointer refers to the task that just ended, to avoid clearing another task belonging to the same user.
                    if downloader.download_chat_active.get(user_id) == chat_id:
                        downloader.download_chat_active.pop(user_id, None)
            elif data == BotCallbackText.DOWNLOAD_CHAT_ID_CANCEL:
                self.__remove_chat_id(downloader, chat_id)
                # Clean up only if the pointer refers to the task that just ended, to avoid clearing another task belonging to the same user.
                if downloader.download_chat_active.get(user_id) == chat_id:
                    downloader.download_chat_active.pop(user_id, None)
                await query.message.edit_text(
                    text=query.message.text,
                    reply_markup=kb.single_button(
                        text=BotButton.TASK_CANCEL,
                        callback_data=BotCallbackText.NULL
                    )
                )
        elif data in (BotCallbackText.DOWNLOAD_CHAT_FILTER, BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER):
            if data == BotCallbackText.DOWNLOAD_CHAT_DATE_FILTER:
                start_time, end_time = self.__get_update_time(downloader, chat_id)
                if not await self.__verification_time(query, start_time, end_time):
                    return None
            try:
                await query.message.edit_text(
                    text=self.__filter_prompt(downloader, chat_id),
                    reply_markup=attach_task(
                        kb.download_chat_filter_button(
                            downloader.download_chat_filter[chat_id]['comment']
                        ) if data == BotCallbackText.DOWNLOAD_CHAT_FILTER else kb.filter_date_range_button(),
                        chat_id
                    )
                )
            except MessageNotModified:
                pass  # The menu did not change (for example, the same date was set again); this is a harmless no-op.
        elif data in (BotCallbackText.FILTER_START_DATE, BotCallbackText.FILTER_END_DATE):
            dtype = None
            p_s_d = ''
            if data == BotCallbackText.FILTER_START_DATE:
                dtype = CalenderKeyboard.START_TIME_BUTTON
                p_s_d = 'start'
            elif data == BotCallbackText.FILTER_END_DATE:
                dtype = CalenderKeyboard.END_TIME_BUTTON
                p_s_d = 'end'
            # If a date was already selected, jump to its year and month and mark that day in green.
            start_time, end_time = self.__get_update_time(downloader, chat_id)
            selected_time = start_time if data == BotCallbackText.FILTER_START_DATE else end_time
            selected_date = None
            year = datetime.datetime.now().year
            month = datetime.datetime.now().month
            if isinstance(selected_time, datetime.datetime):
                selected_date = selected_time.strftime('%Y-%m-%d %H:%M:%S')
                year = selected_time.year
                month = selected_time.month
            await query.message.edit_text(text=f'📅 Select the {p_s_d} date:\n{self.__filter_prompt(downloader, chat_id)}')
            await kb.calendar_keyboard(dtype=dtype, year=year, month=month, selected_date=selected_date,
                                       chat_id=chat_id)
        elif data.startswith('adjust_step_'):
            parts = data.split('_')
            dtype = parts[-2]
            current_step = int(parts[-1])
            step_sequence = [1, 2, 5, 10, 15, 20]
            current_index = step_sequence.index(current_step)
            next_index = (current_index + 1) % len(step_sequence)
            new_step = step_sequence[next_index]
            downloader.download_chat_filter[chat_id]['date_range']['adjust_step'] = new_step
            current_date = datetime.datetime.fromtimestamp(
                downloader.download_chat_filter[chat_id]['date_range'][f'{dtype}_date']
            ).strftime('%Y-%m-%d %H:%M:%S')
            await query.message.edit_reply_markup(
                reply_markup=attach_task(
                    kb.time_keyboard(
                        dtype=dtype,
                        date=current_date,
                        adjust_step=new_step
                    ),
                    chat_id
                )
            )
        elif data.startswith(('time_inc_', 'time_dec_')):
            parts = data.split('_')
            dtype = None
            if 'start' in data:
                dtype = CalenderKeyboard.START_TIME_BUTTON
            elif 'end' in data:
                dtype = CalenderKeyboard.END_TIME_BUTTON
            if 'month' in data:
                year = int(parts[-2])
                month = int(parts[-1])
                start_time, end_time = self.__get_update_time(downloader, chat_id)
                selected_time = start_time if dtype == CalenderKeyboard.START_TIME_BUTTON else end_time
                selected_date = selected_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(selected_time,
                                                                                          datetime.datetime) else None
                await kb.calendar_keyboard(year=year, month=month, dtype=dtype, selected_date=selected_date,
                                           chat_id=chat_id)
                log.info(f'Date changed to {year}-{month}.')
        elif data.startswith(BotCallbackPrefix.SELECT_YEAR):
            # Open the year-selection keyboard; callback data has the form "select_year_{start|end}_{page_center_year}_{current_month}_{selected_year}".
            parts = data.split('_')
            dtype = None
            if 'start' in data:
                dtype = CalenderKeyboard.START_TIME_BUTTON
            elif 'end' in data:
                dtype = CalenderKeyboard.END_TIME_BUTTON
            try:
                year = int(parts[-3])
                month = int(parts[-2])
                selected_year = int(parts[-1])
            except ValueError:
                # For older callback data without a selected-year parameter, use the page's center year as the selected year.
                year = int(parts[-2])
                month = int(parts[-1])
                selected_year = year
            await kb.year_keyboard(dtype=dtype, year=year, month=month, selected_year=selected_year, chat_id=chat_id)
            log.info(f'Opened year selector; selected date: {selected_year}-{month}.')
        elif data.startswith(BotCallbackPrefix.SET_YEAR):
            # Return to the calendar after selecting a year; callback data has the form "set_year_{start|end}_{selected_year}_{current_month}".
            parts = data.split('_')
            dtype = None
            if 'start' in data:
                dtype = CalenderKeyboard.START_TIME_BUTTON
            elif 'end' in data:
                dtype = CalenderKeyboard.END_TIME_BUTTON
            year = int(parts[-2])
            month = int(parts[-1])
            start_time, end_time = self.__get_update_time(downloader, chat_id)
            selected_time = start_time if dtype == CalenderKeyboard.START_TIME_BUTTON else end_time
            selected_date = selected_time.strftime('%Y-%m-%d %H:%M:%S') if isinstance(selected_time,
                                                                                      datetime.datetime) else None
            await kb.calendar_keyboard(year=year, month=month, dtype=dtype, selected_date=selected_date,
                                       chat_id=chat_id)
            log.info(f'Date changed to {year}-{month}.')
        elif data.startswith(('set_time_', 'set_specific_time_')):
            parts = data.split('_')
            date = parts[-1]
            dtype = parts[-2]
            date_type = ''
            p_s_d = ''
            timestamp = datetime.datetime.timestamp(datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S'))
            if 'start' in data:
                date_type = 'start_date'
                p_s_d = 'start'
            elif 'end' in data:
                date_type = 'end_date'
                p_s_d = 'end'
            downloader.download_chat_filter[chat_id]['date_range'][date_type] = timestamp
            await query.message.edit_text(
                text=f'📅 Select the {p_s_d} date:\n{self.__filter_prompt(downloader, chat_id)}',
                reply_markup=attach_task(
                    kb.time_keyboard(
                        dtype=dtype,
                        date=date,
                        adjust_step=downloader.download_chat_filter[chat_id]['date_range']['adjust_step']
                    ),
                    chat_id
                )
            )
            log.info(
                f'Date range set: start={self.__get_update_time(downloader, chat_id)[0]}, end={self.__get_update_time(downloader, chat_id)[1]}.')
        elif data.startswith(('drop_keyword_', 'ignore_keyword')):
            if data.startswith('drop_keyword_'):
                # Include only the keyword's list index in callback data to avoid exceeding the 64-byte limit with long keywords.
                keyword_list: list = downloader.adding_keywords.get(chat_id, [])
                try:
                    keyword_index: int = int(data.split('_')[-1])
                except ValueError:  # An old button contains the keyword text rather than its index; ignore it.
                    keyword_index = -1
                if 0 <= keyword_index < len(keyword_list):
                    keyword = keyword_list[keyword_index]
                    downloader.download_chat_filter.get(chat_id, {}).get('keyword', {}).pop(keyword, None)
                    keyword_list.remove(keyword)
            await query.message.edit_text(
                text=self.__filter_prompt(downloader, chat_id),
                reply_markup=attach_task(
                    KeyboardButton.keyword_filter_button(downloader.adding_keywords.get(chat_id, [])),
                    chat_id
                )
            )
        elif data in (
                BotCallbackText.DOWNLOAD_CHAT_DTYPE_FILTER,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_PHOTO,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_AUDIO,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VOICE,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_ANIMATION,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_DOCUMENT,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO_NOTE,
                BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_LIVE_PHOTO
        ):
            try:
                if data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'video')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_PHOTO:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'photo')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_AUDIO:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'audio')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VOICE:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'voice')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_ANIMATION:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'animation')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_DOCUMENT:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'document')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO_NOTE:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'video_note')
                elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_DTYPE_LIVE_PHOTO:
                    self.__toggle_download_chat_dtype(downloader, chat_id, 'live_photo')
                await query.message.edit_text(
                    text=self.__filter_prompt(downloader, chat_id),
                    reply_markup=attach_task(
                        kb.toggle_download_chat_type_filter_button(downloader.download_chat_filter[chat_id]),
                        chat_id
                    )
                )
            except ValueError:
                await query.message.reply_text('⚠️ At least one download type must be selected.')
            except Exception as e:
                await query.message.reply_text('Failed to update download types.\n(See the terminal for details.)')
                log.error(f'Failed to update download types. {_t(KeyWord.REASON)}: "{e}"', exc_info=True)
        elif data in (
                BotCallbackText.DOWNLOAD_CHAT_KEYWORD_FILTER,
                BotCallbackText.CONFIRM_KEYWORD,
                BotCallbackText.CANCEL_KEYWORD_INPUT
        ):
            if data == BotCallbackText.DOWNLOAD_CHAT_KEYWORD_FILTER:
                # Keep only one input mode per user; when switching from another task, show its owner to avoid writing keywords to the previous task by mistake.
                previous = downloader.keyword_handlers.get(user_id)
                switched: bool = previous is not None and previous[0] != chat_id
                panel_text: str = self.__filter_prompt(downloader, chat_id)
                if switched:
                    panel_text = f'{panel_text}\n⚠️ Keyword entry has switched to this task. Subsequent input will be added to this task.'
                try:
                    await query.message.edit_text(
                        text=panel_text,
                        reply_markup=attach_task(
                            kb.keyword_filter_button(downloader.adding_keywords.get(chat_id, [])),
                            chat_id
                        )
                    )
                except MessageNotModified:
                    pass
                downloader.add_keyword_mode_handler(
                    enable=True,
                    chat_id=user_id,
                    task_chat_id=chat_id,
                    callback_query=query,
                    callback_prompt=partial(self.__filter_prompt, downloader, chat_id)
                )
            elif data == BotCallbackText.CONFIRM_KEYWORD:
                downloader.add_keyword_mode_handler(
                    enable=False,
                    chat_id=user_id,
                    task_chat_id=chat_id,
                    callback_query=query,
                    callback_prompt=partial(self.__filter_prompt, downloader, chat_id)
                )
                await query.message.edit_text(
                    text=self.__filter_prompt(downloader, chat_id),
                    reply_markup=attach_task(
                        kb.download_chat_filter_button(downloader.download_chat_filter[chat_id]['comment']),
                        chat_id
                    )
                )
            elif data == BotCallbackText.CANCEL_KEYWORD_INPUT:
                downloader.adding_keywords.pop(chat_id, None)
                downloader.add_keyword_mode_handler(
                    enable=False,
                    chat_id=user_id,
                    task_chat_id=chat_id,
                    callback_query=query,
                    callback_prompt=partial(self.__filter_prompt, downloader, chat_id)
                )
                downloader.download_chat_filter[chat_id]['keyword'] = {}
                await query.message.edit_text(
                    text=self.__filter_prompt(downloader, chat_id),
                    reply_markup=attach_task(
                        kb.download_chat_filter_button(downloader.download_chat_filter[chat_id]['comment']),
                        chat_id
                    )
                )
        elif data == BotCallbackText.TOGGLE_DOWNLOAD_CHAT_COMMENT:
            status = downloader.download_chat_filter[chat_id]['comment']
            downloader.download_chat_filter[chat_id]['comment'] = not status
            await query.message.edit_text(
                text=self.__filter_prompt(downloader, chat_id),
                reply_markup=attach_task(
                    kb.download_chat_filter_button(downloader.download_chat_filter[chat_id]['comment']),
                    chat_id
                )
            )

    @staticmethod
    def __get_update_time(downloader, chat_id):
        start_timestamp = downloader.download_chat_filter[chat_id]['date_range']['start_date']
        end_timestamp = downloader.download_chat_filter[chat_id]['date_range']['end_date']
        start_time = datetime.datetime.fromtimestamp(start_timestamp) if start_timestamp else 'Undefined'
        end_time = datetime.datetime.fromtimestamp(end_timestamp) if end_timestamp else 'Undefined'
        return start_time, end_time

    @staticmethod
    def __get_format_dtype(downloader, chat_id):
        download_type = []
        for dtype, status in downloader.download_chat_filter[chat_id]['download_type'].items():
            if status:
                download_type.append(_t(dtype))
        return ','.join(download_type)

    @staticmethod
    def __get_format_keywords(downloader, chat_id):
        keywords = downloader.download_chat_filter[chat_id]['keyword']
        if not keywords:
            return 'Undefined'
        return ','.join(keywords.keys())

    @staticmethod
    def __get_format_comment_status(downloader, chat_id):
        status = downloader.download_chat_filter[chat_id]['comment']
        return 'On' if status else 'Off'

    @staticmethod
    def __remove_chat_id(downloader, chat_id):
        if chat_id in downloader.download_chat_filter:
            downloader.download_chat_filter.pop(chat_id)
            log.info(f'Removed "{chat_id}" from {downloader.download_chat_filter}.')

    def __filter_prompt(self, downloader, chat_id):
        start_time, end_time = self.__get_update_time(downloader, chat_id)
        return (
            f'💬 Download channel: `{chat_id}`\n'
            f'⏮️ Selected start date: {start_time}\n'
            f'⏭️ Selected end date: {end_time}\n'
            f'📝️ Selected download types: {self.__get_format_dtype(downloader, chat_id)}\n'
            f'🔑️ Matching keywords: {self.__get_format_keywords(downloader, chat_id)}\n'
            f'👥️ Include comments: {self.__get_format_comment_status(downloader, chat_id)}'
        )

    @staticmethod
    async def __verification_time(query, start_time, end_time) -> bool:
        if isinstance(start_time, datetime.datetime) and isinstance(end_time, datetime.datetime):
            if start_time > end_time:
                await query.message.reply_text(
                    text=f'❌ Failed to set the date.\n'
                         f'`Start date ({start_time})` > `end date ({end_time})`\n'
                )
                return False
            elif start_time == end_time:
                await query.message.reply_text(
                    text=f'❌ Failed to set the date.\n'
                         f'`Start date ({start_time})` = `end date ({end_time})`\n'
                )
                return False
        return True

    @staticmethod
    def __toggle_download_chat_dtype(downloader, chat_id, param):
        dtype = downloader.download_chat_filter[chat_id]['download_type']
        status = dtype[param]
        if list(dtype.values()).count(True) == 1 and status:
            raise ValueError
        dtype[param] = not status
        f_s = 'disabled' if status else 'enabled'
        f_p = f'{param} downloads for `/download_chat` {f_s}.'
        log.info(f'{f_p} Current `/download_chat` download type settings: {dtype}')


class CommandButtonHandler(CallbackHandler):
    exact = (
        BotCallbackText.COMMAND_DOWNLOAD,
        BotCallbackText.COMMAND_UPLOAD,
        BotCallbackText.COMMAND_UPLOAD_R,
        BotCallbackText.COMMAND_DOWNLOAD_CHAT,
        BotCallbackText.COMMAND_FORWARD,
        BotCallbackText.LISTEN_DOWNLOAD_BTN,
        BotCallbackText.LISTEN_FORWARD_BTN
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        data = ctx.data
        command_map = {
            BotCallbackText.COMMAND_DOWNLOAD: BotCommandText.DOWNLOAD[0],
            BotCallbackText.COMMAND_DOWNLOAD_CHAT: BotCommandText.DOWNLOAD_CHAT[0],
            BotCallbackText.COMMAND_UPLOAD: BotCommandText.UPLOAD[0],
            BotCallbackText.COMMAND_UPLOAD_R: BotCommandText.UPLOAD_R[0],
            BotCallbackText.COMMAND_FORWARD: BotCommandText.FORWARD[0],
            BotCallbackText.LISTEN_DOWNLOAD_BTN: BotCommandText.LISTEN_DOWNLOAD[0],
            BotCallbackText.LISTEN_FORWARD_BTN: BotCommandText.LISTEN_FORWARD[0]
        }
        command = command_map.get(data)
        if not command:
            return None
        # Reuse start_command_guide so button clicks behave like directly sending a command without arguments.
        await downloader.start_command_guide(message=query.message, command=command, callback_query=query)


class MenuButtonHandler(CallbackHandler):
    exact = (
        BotCallbackText.MENU_DOWNLOAD,
        BotCallbackText.MENU_LISTEN,
        BotCallbackText.MENU_UPLOAD,
        BotCallbackText.MENU_AUTH,
        BotCallbackText.MENU_BACK
    )

    async def handle(self, ctx: CallbackContext) -> None:
        downloader = ctx.downloader
        query = ctx.query
        data = ctx.data
        if data == BotCallbackText.MENU_DOWNLOAD:
            await query.edit_message_text(
                text=BotButton.DOWNLOAD_MENU_TITLE,
                reply_markup=downloader.menu_keyboard('download'))
            return None
        elif data == BotCallbackText.MENU_LISTEN:
            await query.edit_message_text(
                text=BotButton.LISTEN_MENU_TITLE,
                reply_markup=downloader.menu_keyboard('listen'))
            return None
        elif data == BotCallbackText.MENU_UPLOAD:
            await query.edit_message_text(
                text=BotButton.UPLOAD_MENU_TITLE,
                reply_markup=downloader.menu_keyboard('upload'))
            return None
        elif data == BotCallbackText.MENU_AUTH:
            await downloader.show_auth_menu(
                client=downloader.bot,
                message=query.message,
                edit_message=query.message
            )
            return None
        elif data == BotCallbackText.MENU_BACK:
            menu = await downloader.help(user_id=query.from_user.id)
            await query.edit_message_text(
                rich_message=pyrogram.types.InputRichMessage(
                    markdown=menu['text'],
                    skip_entity_detection=True
                ),
                reply_markup=menu['keyboard']
            )
            return None
        else:
            return None


CALLBACK_HANDLERS: tuple = (
    MenuButtonHandler(),
    NoticeHandler(),
    PayHandler(),
    BackHandler(),
    TaskAssignHandler(),
    ListenInfoHandler(),
    LookupAuthInfoHandler(),
    ViewAuthListHandler(),
    AddAuthHandler(),
    CancelAuthInputHandler(),
    ShutdownHandler(),
    SettingsHandler(),
    TableHandler(),
    UploadDownloadSettingHandler(),
    DownloadTypeHandler(),
    ForwardTypeHandler(),
    ListenRemoveHandler(),
    AuthUserHandler(),
    DownloadChatHandler(),
    CommandButtonHandler()
)


async def dispatch_callback_data(ctx: CallbackContext) -> None:
    """Dispatch callbacks in registry order; the first matching handler processes the callback."""
    for handler in CALLBACK_HANDLERS:
        if handler.match(ctx.data):
            await handler.handle(ctx)
            return None
