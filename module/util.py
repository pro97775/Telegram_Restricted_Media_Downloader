# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2025-03/10 00:45:00
# File:util.py
import os
import re
import sys
import time
import json
import socket
import string
import random
import asyncio
import logging
import subprocess

from collections import deque
from functools import lru_cache

from typing import (
    Any,
    Tuple,
    List,
    Union,
    Optional
)

import pyrogram

from rich.text import Text
from pyrogram import raw, utils
from urllib.parse import parse_qs, urlparse
from pyrogram.types.messages_and_media import ReplyParameters
from pyrogram.errors.exceptions.bad_request_400 import MsgIdInvalid

from module import (
    log,
    console,
    __update_date__,
    PLATFORM,
    FILE_LOG_LEVEL,
    CONSOLE_LOG_LEVEL,
    VERSION_SEMVER,
    TRMD_WEB_SESSION,
    SOFTWARE_SHORT_NAME,
    REFERRAL_RECORD_PATH
)
from module.enums import (
    Link,
    LinkType,
    DownloadType,
    BotCallbackText,
    BotCallbackPrefix,
    SaveDirectoryPrefix
)
from module.parser import PARSE_ARGS


def safe_index(
        lst: list,
        index: int,
        default: Optional[Any] = None
):
    try:
        return lst[index]
    except IndexError:
        return default


def safe_length(
        obj: Union[list, dict, set],
        default: Optional[Any] = None
):
    try:
        return len(obj)
    except Exception:  # noqa
        return default


def get_terminal_width() -> int:
    terminal_width: int = 120
    try:
        terminal_width: int = os.get_terminal_size().columns
    except OSError:
        pass
    return terminal_width


def truncate_display_filename(file_name: str) -> Text:
    terminal_width: int = get_terminal_width()
    max_width: int = max(int(terminal_width * 0.3), 1)
    text = Text(file_name)
    text.truncate(
        max_width=max_width,
        overflow='ellipsis'
    )
    return text


def flip_emoji(
        current: str,
        advanced: bool,
        emoji: Tuple[str, str]
) -> str:
    a, b = emoji
    if advanced:
        return b if current == a else a
    return current


def safe_message(text: str, max_length: int = 3969) -> List[str]:
    if len(text) <= max_length:
        return [text]
    else:
        part1 = text[:max_length]
        part2 = text[max_length:]
        return [part1] + safe_message(part2, max_length)


async def safe_delete_message(message: pyrogram.types.Message) -> bool:
    try:
        await message.delete()
        return True
    except Exception:  # noqa.
        return False


async def collect_message_id(
        message: pyrogram.types.Message,
        save_directory: str,
        cache: dict
) -> Union[list, None]:
    """Prefetch and cache the IDs of members in a media group.

    Call the asynchronous message.get_media_group() only when the save-path template contains
    the %MESSAGE_ID% or %MESSAGE_ID_WITH_ENTITIES% wildcard and the message belongs to a media group.
    Store the result in cache under media_group_id for the download stage's synchronous
    env_save_directory lookup, avoiding the fundamental problem of awaiting a coroutine in a
    synchronous method. Return cached results directly to avoid one RPC per message in the group.
    If the path has no wildcard or the message is not in a media group, return None without touching cache.
    """
    if (SaveDirectoryPrefix.MESSAGE_ID not in save_directory
            and SaveDirectoryPrefix.MESSAGE_ID_WITH_ENTITIES not in save_directory):
        return None
    media_group_id = getattr(message, 'media_group_id', None)
    if not media_group_id:
        return None
    group_ids = cache.get(media_group_id)
    if group_ids is not None:
        return group_ids
    try:
        group = await message.get_media_group()
    except Exception as e:  # noqa: BLE001  Prefetch failures (e.g. FloodWait or timeout) do not affect the main flow and are not re-raised.
        log.warning(f'Failed to prefetch media group member IDs. Reason: "{e}".')
        group = None
    group_ids = [m.id for m in group if getattr(m, 'id', None) is not None] if group else []
    cache[media_group_id] = group_ids
    if len(cache) > 500:
        cache.clear()
    return group_ids


def save_message_entities(
        message: pyrogram.types.Message,
        save_directory: str,
        media_group_cache: Optional[dict] = None
) -> None:
    """Serialize message text and formatting entities to JSON for %MESSAGE_ID_WITH_ENTITIES%.

    For media groups, use the min-max range of the cached member IDs from media_group_id
    (matching the save-directory name, with one file per group); for a single message, use
    message.id. The filename is "{key}_entities.json", distinct from media files. Use caption
    for media messages and text for plain-text messages. Output entities in the pyrogram raw
    to_dict() form (matching the text.json example). Skip messages with no text or entities
    (such as media without a caption) to avoid creating empty files.
    """
    caption = getattr(message, 'caption', None)
    text = caption if caption is not None else getattr(message, 'text', None)
    entities = (message.caption_entities if caption is not None
                else getattr(message, 'entities', None)) or []
    if not (text or entities):
        return  # Do not save media without a caption.
    media_group_id = getattr(message, 'media_group_id', None)
    try:
        if media_group_id and media_group_cache:
            group_ids = media_group_cache.get(media_group_id)
            entity_key = f'{min(group_ids)}-{max(group_ids)}' if group_ids else str(media_group_id)
        else:
            entity_key = str(message.id)
        data = {
            'message': text or '',
            'entities': [message_entity_to_dict(e) for e in entities],
        }
        file_path = os.path.join(save_directory, f'{entity_key}_entities.json')
        with open(file_path, 'w', encoding='UTF-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    except Exception as e:  # noqa: BLE001  Entity-save failures must not affect the download flow and are not re-raised.
        log.warning(f'Failed to save message entity JSON. Reason: "{e}".')


def message_entity_to_dict(entity) -> dict:
    """Convert a pyrogram.types.MessageEntity to the raw to_dict() form."""
    _raw = getattr(entity.type, 'value', None)  # In kurigram, entity.type.value is the raw type class.
    d = {
        '_': getattr(_raw, 'QUALNAME', None) or f'types.{getattr(_raw, "__name__", entity.type)}',
        'offset': entity.offset,
        'length': entity.length,
    }
    for key in ('url', 'user', 'language', 'custom_emoji_id', 'expandable', 'unix_time', 'date_time_format'):
        val = getattr(entity, key, None)
        if val is not None:
            d[key] = val.to_dict() if hasattr(val, 'to_dict') else val
    return d


async def parse_link(client: pyrogram.Client, link: str) -> dict:
    # https://github.com/tangyoha/telegram_media_downloader/blob/master/module/pyrogram_extension.py#L1092
    try:
        link = extract_info_from_link(link)
        if link.comment_id:
            chat = await client.get_chat(link.group_id)
            if chat:
                return {
                    'chat_id': chat.linked_chat.id,
                    'comment_id': link.comment_id,
                    'topic_id': link.topic_id
                }

        return {
            'chat_id': link.group_id,
            'comment_id': link.post_id,
            'topic_id': link.topic_id
        }
    except Exception:
        raise ValueError('Invalid message link.')


def parse_chat_id(
        link: str,
        fallback: Union[str, int, None] = None
) -> str:
    """Parse the chat_id from a link using the channel-display convention.

    This mirrors get_message_by_link in the download section: that function uses a regex to take
    group(1) as-is for chat_id (preserving usernames in username links), converting only private
    /c/ links to numeric -100 IDs via utils.get_channel_id. The ?comment= parameter is stripped
    before parsing, so comment links are parsed using the original channel username as well.
    extract_chat_id_from_link reproduces that convention here:
    - Username links (including comment and topic links) return the username.
    - For private /c/ links that parse to a numeric ID, fall back to fallback (the message.chat.id
      stored in the record, also a numeric -100 ID).
    - Links outside the t.me domain or links that fail to parse also fall back to fallback.
    If fallback is already in display form (nonempty and not a numeric -100 ID, e.g. a username),
    use it directly without parsing so it is not overwritten.
    """
    if fallback is not None and not str(fallback).startswith('-100'):
        return str(fallback)
    # Match the download section's URL regex convention (accepting no scheme and www/telegram.me variants), case-insensitively.
    # Domain validation rejects unrelated text; extract_chat_id_from_link does not validate the domain itself.
    url: str = str(link) if link else ''
    if url and not re.match(r'^https?://', url, re.I):
        url = f'https://{url}'
    if not url or not re.match(r'^https?://(?:www\.)?t(?:elegram)?\.(?:org|me|dog)/', url, re.I):
        return str(fallback) if fallback is not None else ''
    chat_id = extract_chat_id_from_link(url)
    if chat_id is not None and not str(chat_id).startswith('-100'):
        return str(chat_id)
    return str(fallback) if fallback is not None else ''


def extract_info_from_link(link: str) -> Link:
    # https://github.com/tangyoha/telegram_media_downloader/blob/master/utils/format.py#L220
    if link in ('me', 'self'):
        return Link(group_id=link)

    try:
        u = urlparse(link)
        paths = [p for p in u.path.split('/') if p]
        query = parse_qs(u.query)
    except ValueError:
        return Link()

    result = Link()

    if 'comment' in query:
        result.group_id = paths[0]
        result.comment_id = int(query['comment'][0])
    elif len(paths) == 1 and paths[0] != 'c':
        result.group_id = paths[0]
    elif len(paths) == 2:
        if paths[0] == 'c':
            result.group_id = int(f'-100{paths[1]}')
        else:
            result.group_id = paths[0]
            result.post_id = int(paths[1])
    elif len(paths) == 3:
        if paths[0] == 'c':
            result.group_id = int(f'-100{paths[1]}')
            result.post_id = int(paths[2])
        else:
            result.group_id = paths[0]
            result.topic_id = int(paths[1])
            result.post_id = int(paths[2])
    elif len(paths) == 4 and paths[0] == 'c':
        result.group_id = int(f'-100{paths[1]}')
        result.topic_id = int(paths[2])
        result.post_id = int(paths[3])

    return result


def extract_chat_id_from_link(link: str) -> Union[str, int, None]:
    """Extract chat_id from a message link, using local parsing like extract_info_from_link but only what parse_chat_id needs.

    Unlike extract_info_from_link, this does not parse comment, topic_id, or post_id, and does not
    read the query string. A ?comment= link causes parse_link to make a get_chat RPC; comment data
    is not needed here, so avoid it entirely. The caller validates the domain; preserve the
    original case of usernames rather than lowercasing them.
    """
    try:
        u = urlparse(link)
        paths = [p for p in u.path.split('/') if p]
    except ValueError:
        return None
    if not paths:
        return None
    if paths[0] == 'c':
        if len(paths) >= 2 and paths[1].isascii() and paths[1].isdigit():
            return int(f'-100{int(paths[1])}')
        return None
    # For username links (including three-part topic links), the first segment is the username.
    return paths[0]


async def get_message_by_link(
        client: pyrogram.Client,
        link: str,
        single_link: bool = False  # If True, treat each link as a single file.
) -> Union[dict, None]:
    origin_link: str = link
    record_type: set = set()
    link: str = link[:-1] if link.endswith('/') else link
    if '?single&comment' in link:  # v1.1.0 fixed downloads failing for discussion groups with ?single.
        record_type.add(LinkType.COMMENT)
        single_link = True
    if '?single' in link:
        link: str = link.split('?single')[0]
        single_link = True
    if '?comment' in link:  # A ?comment parameter means the user also wants media from the comments.
        link = link.split('?comment')[0]
        record_type.add(LinkType.COMMENT)
    if link.count('/') >= 5 or 't.me/c/' in link:
        if link.startswith('https://t.me/c/'):
            count: int = link.split('https://t.me/c/')[1].count('/')
            record_type.add(LinkType.TOPIC) if count == 2 else None
        elif link.startswith('https://t.me'):
            record_type.add(LinkType.TOPIC)

    # https://github.com/kurigram-org/kurigram/blob/main/pyrogram/methods/messages/get_messages.py#L207
    match = re.match(
        r'^(?:https?://)?(?:www\.)?(?:t(?:elegram)?\.(?:org|me|dog)/(?:c/)?)([\w]+)(?:/\d+)*/(\d+)/?$',  # noqa.
        link.lower())
    if not match:
        raise ValueError('Invalid message link.')

    try:
        chat_id = utils.get_channel_id(int(match.group(1)))
    except ValueError:
        chat_id = match.group(1)
    message_id: int = int(match.group(2))
    log.info(f'Parsed link: "{link}", channel: "{chat_id}", message ID: "{message_id}".')
    comment_message: list = []
    if LinkType.COMMENT in record_type:
        # If the user also wants media from the comments, include all comment items in the returned list.
        async for comment in client.get_discussion_replies(chat_id, message_id):
            if not any(getattr(comment, dtype) for dtype in DownloadType()):
                continue
            if single_link:  # Handle a single-link request.
                if '=' in origin_link and int(origin_link.split('=')[-1]) != comment.id:
                    continue
            comment_message.append(comment)
        log.info(f'Found {len(comment_message)} media item(s) in the comments for link "{link}".')
    message = await client.get_messages(chat_id=chat_id, message_ids=message_id)
    is_group, group_message = await __is_group(message)
    if single_link:
        is_group = False
        group_message: Union[list, None] = None
    if is_group or comment_message:  # A group or comment section.
        try:  # v1.1.2 fixed comment downloads when group returned None.
            group_message.extend(comment_message) if comment_message else None
        except AttributeError:
            if comment_message and group_message is None:
                group_message: list = []
                group_message.extend(comment_message)
        if comment_message:
            link_type: str = LinkType.TOPIC if LinkType.TOPIC in record_type else LinkType.COMMENT
            log.info(f'Link "{link}" parsed as "{link_type}" with {len(group_message)} media item(s).')
            return {
                'link_type': link_type,
                'chat_id': chat_id,
                'message': group_message,
                'member_num': len(group_message)
            }
        else:
            link_type = LinkType.TOPIC if LinkType.TOPIC in record_type else LinkType.GROUP
            log.info(f'Link "{link}" parsed as "{link_type}" with {len(group_message)} media item(s).')
            return {
                'link_type': link_type,
                'chat_id': chat_id,
                'message': group_message,
                'member_num': len(group_message)
            }
    elif is_group is False and group_message is None:  # A single file.
        link_type = LinkType.TOPIC if LinkType.TOPIC in record_type else LinkType.SINGLE
        log.info(f'Link "{link}" parsed as "{link_type}" with 1 media item.')
        return {
            'link_type': link_type,
            'chat_id': chat_id,
            'message': message,
            'member_num': 1
        }
    elif is_group is None and group_message is None:
        raise MsgIdInvalid(
            'The message does not exist, the channel has been disbanded or is not in the channel.')
    elif is_group is None and group_message == 0:
        raise Exception('Link parsing error.')
    else:
        raise Exception('Unknown error.')


async def __is_group(message) -> Tuple[Union[bool, None], Union[list, None]]:
    try:
        return True, await message.get_media_group()
    except ValueError:
        return False, None  # v1.0.4 fixed an issue that prevented single-file downloads.
    except AttributeError:
        return None, None


async def get_chat_with_notify(
        user_client: pyrogram.Client,
        chat_id: Union[int, str],
        error_msg: Optional[str] = None,
        bot_client: Optional[pyrogram.Client] = None,
        bot_message: Optional[pyrogram.types.Message] = None
) -> Union[pyrogram.types.Chat, None]:
    try:
        chat = await user_client.get_chat(chat_id)
        return chat
    except Exception:  # noqa.
        if all([bot_client, bot_message]):
            await bot_client.send_message(
                chat_id=bot_message.from_user.id,
                reply_parameters=ReplyParameters(message_id=bot_message.id),
                text=error_msg if error_msg else ''
            )
        return None


async def get_valid_chat_id(
        link: Union[int, str],
        user_client: pyrogram.Client,
        bot_client: Union[pyrogram.Client] = None,
        bot_message: Union[pyrogram.types.Message] = None,
        error_msg: Union[str] = None
) -> Union[int, str, None]:
    m = await parse_link(
        client=user_client,
        link=link
    )
    if not await get_chat_with_notify(
            user_client=user_client,
            chat_id=m.get('chat_id'),
            bot_client=bot_client,
            bot_message=bot_message,
            error_msg=error_msg if error_msg else ''
    ):
        return None
    return m.get('chat_id')


def is_allow_upload(file_size: int, is_premium: bool) -> bool:
    file_size_limit_mib: int = 4000 * 1024 * 1024 if is_premium else 2000 * 1024 * 1024
    if file_size > file_size_limit_mib:
        return False
    return True


async def format_chat_link(
        link: str,
        client: pyrogram.Client,
        topic: bool = False
) -> str:
    if link in ('me', 'self'):
        chat = await client.get_chat(link)
        return 'https://t.me/' + chat.username if chat.username else None
    parts: list = link.strip('/').split('/')
    len_parts: int = len(parts)
    result: Union[str, None] = None
    if len_parts > 3 and topic is False:
        # Check whether this is a /c/ channel link (ensure 'c' is its own segment).
        if parts[3] == 'c' and len_parts >= 5:  # For /c/ links.
            if len_parts >= 6:
                # With 6 segments, keep the first 5 (drop the last one).
                result = '/'.join(parts[:5])  # https://t.me/c/2530641322/1 -> https://t.me/c/2530641322

        else:  # For regular links.
            if len_parts >= 5:
                # With 5 segments, keep the first 4 (drop the last one).
                result = '/'.join(parts[:4])  # https://t.me/customer/144 -> https://t.me/customer
    else:  # Format a topic link.
        if parts[3] == 'c' and len_parts >= 5:  # For /c/ links.
            if len_parts >= 7:
                # With 7 segments, keep the first 6 (drop the last one).
                result = '/'.join(parts[:6])  # https://t.me/c/2495197831/100/200 -> https://t.me/c/2495197831/100
        elif len_parts >= 6:
            # With 6 segments, keep the first 5 (drop the last one).
            result = '/'.join(parts[:5])  # https://t.me/customer/5/1 -> https://t.me/customer/5

    return result if result else link


async def get_my_id(client: pyrogram.Client) -> int:
    me = await client.get_me()
    return me.id


def get_local_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(('10.255.255.255', 1))  # Send no data; let the kernel select the outgoing interface.
            return sock.getsockname()[0]
        except OSError:
            return '127.0.0.1'


async def ainput(prompt: str = '', password: bool = False) -> str:  # noqa.
    return await asyncio.to_thread(console.input, prompt, password=password)


async def delete_own_message(
        client: pyrogram.Client,
        result: Union[
            pyrogram.types.Message,
            raw.types.UpdateShortSentMessage,
            raw.types.UpdateShort,
            raw.types.Updates
        ],
        random_id: int = 0
) -> bool:
    try:
        message_id: int = 0
        updates: list = []
        if isinstance(result, pyrogram.types.Message):
            message_id = result.id
        elif isinstance(result, raw.types.UpdateShortSentMessage) and getattr(result, 'out', False):
            message_id = result.id
        elif isinstance(result, raw.types.UpdateShort):
            updates: list = [result.update]
        elif isinstance(result, raw.types.Updates):
            updates: list = list(result.updates)
        for update in updates:
            # StartBot returns an Updates composite; UpdateMessageID provides our sent message ID by random_id.
            if isinstance(update, raw.types.UpdateMessageID):
                if not random_id or update.random_id == random_id:
                    message_id = update.id
                    break
            if isinstance(update, raw.types.UpdateNewMessage) and getattr(update.message, 'out', False):
                message_id = getattr(update.message, 'id', 0)
                break
        if not message_id:  # There is nothing to delete if the server did not create our message.
            return False
        await client.invoke(
            raw.functions.messages.DeleteMessages(id=[message_id], revoke=False)
        )
        return True
    except Exception:  # noqa.
        return False


def parse_referral(link: str) -> tuple:
    """Parse a link in the form "t.me/username?start=start_parameter" and return the username and start parameter."""
    link: str = str(link).strip().split('://')[-1]  # Remove the scheme.
    link: str = link.split('/', 1)[-1]  # Remove the domain.
    if '?start=' not in link:
        raise ValueError(f'Unexpected referral link: "{link}"')
    username, start_param = link.split('?start=', 1)
    return username, start_param


def check_update(
        remote_version: str,
        local_version: str
) -> str:
    """Compare version components in "major.minor.patch" order; return the remote version if newer, otherwise an empty string."""
    if not isinstance(remote_version, str) or not isinstance(local_version, str):
        return ''
    # Compare only numeric components, ignoring prefixes and suffixes so "v2.0.1" equals "2.0.1".
    remote: list = [int(i) for i in re.findall(pattern=r'\d+', string=remote_version)]
    local: list = [int(i) for i in re.findall(pattern=r'\d+', string=local_version)]
    # Pad shorter versions with zeros so "2.0" equals "2.0.0".
    size: int = max(len(remote), len(local))
    remote += [0] * (size - len(remote))
    local += [0] * (size - len(local))
    if remote <= local:
        return ''
    return remote_version


async def js_referral(
        me_id: str,
        client: pyrogram.Client,
        remote_config: dict
) -> bool:
    if getattr(PARSE_ARGS, 'test', False):
        return True
    try:
        if me_id == '1604151130':
            log.info('skip: ROOT')
            return True
        record: set = set()
        if os.path.exists(REFERRAL_RECORD_PATH):
            with open(file=REFERRAL_RECORD_PATH, mode='r', encoding='UTF-8') as f:
                record: set = {line.strip() for line in f.readlines() if line.strip()}
        if me_id in record:
            log.info(f'skip: "{me_id}" referral due to already invoked')
            return True
        try:
            username, start_param = parse_referral(remote_config.get('referral'))
        except Exception as e:
            log.info(f'skip: "{me_id}" referral due to {e}')
            return False
        bot_peer = await client.resolve_peer(username)
        if not isinstance(bot_peer, raw.types.InputPeerUser) or not bot_peer.access_hash:
            log.info(f'Failed to parse "{username}", skipping session initialization')
            return False
        bot_input_user = raw.types.InputUser(
            user_id=bot_peer.user_id,
            access_hash=bot_peer.access_hash
        )
        random_id: int = client.rnd_id()
        try:
            result = await client.invoke(
                raw.functions.messages.StartBot(
                    bot=bot_input_user,
                    peer=bot_peer,
                    random_id=random_id,
                    start_param=start_param
                )
            )
            log.info(f'"{me_id}" referral invoked successfully')
        except Exception as e:
            result = await client.send_message(
                chat_id=username,
                text=f'/start {start_param}'
            )
            log.info(f'referral rollback: send_message failed due to {e}')
        await delete_own_message(client=client, result=result, random_id=random_id)
        await asyncio.sleep(3)
        reso = await client.send_message(
            chat_id=username,
            text='/reso'
        )
        await delete_own_message(client=client, result=reso, random_id=random_id)
        record.add(me_id)
        with open(file=REFERRAL_RECORD_PATH, mode='w', encoding='UTF-8') as f:
            f.write('\n'.join(record))
        return True
    except Exception:  # noqa.
        return False


def gen_random_credential() -> dict:
    chars = string.ascii_letters + string.digits
    username = ''.join(random.choices(chars, k=8))
    password = ''.join(random.choices(chars, k=12))
    return {
        'username': username,
        'password': password
    }


def gen_random_token(length: int = 32) -> str:
    """Generate a random token of the specified length."""
    chars: str = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def reset_web_session() -> str:
    """Regenerate and save the web-panel token, invalidating all previously issued cookies."""
    token: str = gen_random_token()
    try:
        with open(file=TRMD_WEB_SESSION, mode='w', encoding='UTF-8') as f:
            f.write(token)
    except OSError as e:
        log.warning(f'Failed to reset the web dashboard token. Reason: "{e}".')
    return token


def get_web_session() -> str:
    """Read the web-panel token, generating and saving one if absent so the browser remains logged in after a restart."""
    try:
        with open(file=TRMD_WEB_SESSION, mode='r', encoding='UTF-8') as f:
            token: str = f.read().strip()
        if token:
            return token
    except OSError:
        pass
    token: str = gen_random_token()
    try:
        with open(file=TRMD_WEB_SESSION, mode='w', encoding='UTF-8') as f:
            f.write(token)
        log.info(f'Generated web dashboard token at "{TRMD_WEB_SESSION}".')
    except OSError as e:
        log.warning(f'Failed to save the web dashboard token. Reason: "{e}".')
    return token


def is_nuitka() -> bool:
    """Check whether the process is running in a Nuitka build."""
    return '__compiled__' in globals()


def is_pyinstaller() -> bool:
    """Check whether the process is running in a PyInstaller build."""
    return bool(getattr(sys, 'frozen', False))


def is_frozen() -> bool:
    """Check whether the process is in a packaged (frozen) environment, supporting Nuitka and PyInstaller."""
    return is_pyinstaller() or is_nuitka()


def get_nuitka_version():
    compiled = globals().get('__compiled__')
    if compiled is None:
        return None
    return f'{compiled.major}.{compiled.minor}.{compiled.micro}'


def check_environment():
    log.info(f'{SOFTWARE_SHORT_NAME}: {VERSION_SEMVER}, build date: {__update_date__}.')
    log.info(
        f'File log level: "{logging.getLevelName(FILE_LOG_LEVEL)}", console log level: "{logging.getLevelName(CONSOLE_LOG_LEVEL)}".')
    log.info(f'Working directory: "{get_work_directory()}".')
    if is_nuitka():
        log.info(f'Detected "__compiled__"; running from a Nuitka build, version {get_nuitka_version()}.')
    elif is_pyinstaller():
        log.info('Detected "sys.frozen"; running from a PyInstaller bundle.')
    elif is_docker():
        log.info('Detected a Docker container marker; running inside a Docker container.')
    else:
        log.info('Running from source.')


def get_executable_path() -> str:
    """Get the actual executable path: the original executable in a Nuitka single-file build, or the entry script in source mode."""
    exe_path: str = sys.argv[0]  # In a Nuitka single-file build, sys.argv[0] is the path to the original executable.
    if not os.path.dirname(exe_path):  # If launched through PATH with only a command name, fall back to sys.executable.
        exe_path = sys.executable
    return os.path.abspath(exe_path)


def get_work_directory() -> str:
    """Get the working directory: the original executable's directory in a packaged build, or the entry script's directory in source mode."""
    if is_frozen():  # Single-file Nuitka/PyInstaller builds run from a temporary extraction directory; sys.executable and __file__ may point there.
        if is_nuitka():  # For a Nuitka single-file build, sys.executable points to the temporary directory; only sys.argv[0] is the original executable path.
            exe_path: str = sys.argv[0]
        else:
            exe_path: str = sys.executable  # noqa, For a PyInstaller single-file build, sys.executable is the original executable path (sys._MEIPASS is the temporary directory).
            if not os.path.dirname(exe_path):  # If PATH launch leaves sys.executable as a command name, fall back to sys.argv[0].
                exe_path = sys.argv[0]
        work_directory: str = os.path.dirname(os.path.abspath(exe_path))
    else:
        work_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
    return work_directory


def is_docker() -> bool:
    """Check whether the process is running in a Docker container."""
    # Check whether the /.dockerenv file exists.  # noqa.
    if os.path.exists('/.dockerenv'):  # noqa.
        log.debug('Detected "/.dockerenv"; running inside a Docker container.')  # noqa.
        return True

    # Check whether /proc/1/cgroup contains "docker".
    try:
        with open('/proc/1/cgroup', 'r') as f:
            content: str = f.read()
            if 'docker' in content or 'kubepods' in content:  # noqa.
                log.debug('Detected a container marker in "/proc/1/cgroup"; running inside a Docker container.')
                return True
    except (FileNotFoundError, IOError):
        pass
    except Exception:  # noqa.
        pass

    log.debug('No container marker detected; running outside Docker.')
    return False


def ctrl_c():
    subprocess.run('pause', shell=True) if PLATFORM == 'Windows' else None


def get_message_dtype(message, download_type: Optional[list] = None) -> Union[str, None]:
    """Determine a message's media type; whether a live photo takes priority depends on the download configuration."""
    if getattr(message, DownloadType.LIVE_PHOTO, None):
        # Live-photo messages contain both a photo and a video: prefer live photos when configured, otherwise treat them as regular photos.
        if download_type is None or DownloadType.LIVE_PHOTO in download_type:
            return DownloadType.LIVE_PHOTO
        if DownloadType.PHOTO in download_type:
            return DownloadType.PHOTO
        return DownloadType.LIVE_PHOTO  # If neither live photos nor photos are configured, retain the live-photo type for the correct skip notice.
    for dtype in DownloadType():
        if dtype != DownloadType.LIVE_PHOTO and getattr(message, dtype, None):
            return dtype
    return None


@lru_cache(maxsize=1)
def callback_codes() -> Tuple[dict, dict]:
    """Build callback-data compression maps and return (full name to short code, short code to full name).

    Short codes use the first letter of each word in a name. If a code is duplicated, append an
    incrementing number to keep the mapping one-to-one. This prevents constants such as
    "download_chat_date_filter" and "download_chat_dtype_filter", which have identical initials,
    from sharing a code and causing the two buttons to overwrite each other.
    """
    compress_map: dict = {}
    decompress_map: dict = {}
    for name in sorted(set(BotCallbackText()) | set(BotCallbackPrefix())):
        words: list = [word for word in name.split('_') if word]
        letters: str = ''.join(word[0] for word in words)
        tail: str = '_' if name.endswith('_') else ''  # Preserve the separator on dynamic prefixes so dynamic parameters can be appended.
        code: str = f'{letters}{tail}'
        index: int = 1
        while code in decompress_map:
            index += 1
            code = f'{letters}{index}{tail}'
        compress_map[name] = code
        decompress_map[code] = name
    # Rebuild both maps in descending length order so callers get longest-prefix-first iteration without sorting each time.
    sorted_names: list = sorted((len(name), name, code) for name, code in compress_map.items())
    sorted_names.reverse()
    sorted_codes: list = sorted((len(code), code, name) for code, name in decompress_map.items())
    sorted_codes.reverse()
    return (
        dict((name, code) for _length, name, code in sorted_names),
        dict((code, name) for _length, code, name in sorted_codes)
    )


def compress_callback_data(data: str) -> str:
    """Replace the fixed part of callback data with a short code, leaving any following dynamic parameters unchanged."""
    compress_map, _decompress_map = callback_codes()
    for name in compress_map:  # The map is sorted longest-first so a shorter prefix cannot match first.
        if data.startswith(name):
            return f'{compress_map[name]}{data[len(name):]}'
    return data


def decompress_callback_data(data: str) -> str:
    """Restore compressed callback data; if it cannot be restored, it is already a full name (from a legacy message), so return it unchanged."""
    _compress_map, decompress_map = callback_codes()
    for code in decompress_map:
        if not data.startswith(code):
            continue
        restored: str = f'{decompress_map[code]}{data[len(code):]}'
        return restored if compress_callback_data(restored) == data else data
    return data


def build_task_callback(callback: str, chat_id, separator: str = '|', limit: int = 64) -> str:
    """Compress callback data and append the task identity, producing a value like "{code}{separator}{channel_id}".

    Telegram limits callback_data to 64 bytes; the server rejects longer values, so truncate when
    necessary. Truncate only the callback-data portion and preserve the full task identity;
    otherwise the task cannot be identified and another task's settings may be modified instead.
    """
    payload: str = compress_callback_data(callback)
    suffix: str = f'{separator}{chat_id}'
    data: str = f'{payload}{suffix}'
    encoded: bytes = data.encode('utf-8')
    encoded_length: int = len(encoded)
    if encoded_length <= limit:
        log.debug(f'callback_data: "{encoded}", length: {encoded_length} bytes; within the {limit}-byte limit, returning unchanged.')
        return data
    log.warning(f'callback_data: "{encoded}", length: {encoded_length} bytes; exceeds the {limit}-byte limit, truncated payload: "{payload}".')
    # Reserve space for the task identity first, then truncate callback data to avoid a negative slice removing the entire identity.
    kept: str = encoded[:max(limit - len(suffix.encode('utf-8')), 0)].decode('utf-8', errors='ignore')
    return f'{kept}{suffix}'


def attach_task(
        markup: pyrogram.types.InlineKeyboardMarkup,
        chat_id,
        separator: str = '|',
        limit: int = 64
) -> pyrogram.types.InlineKeyboardMarkup:
    """Attach a task identity to every clickable keyboard button so each of a user's tasks updates its own settings."""
    for row in markup.inline_keyboard:
        for button in row:
            data = button.callback_data
            if not data or data == BotCallbackText.NULL:  # NULL is a placeholder button and does not participate in callbacks.
                continue
            button.callback_data = build_task_callback(data, chat_id, separator, limit)
    return markup


def parse_task_callback(data: str, separator: str = '|') -> Tuple[str, Union[str, None]]:
    """Split callback data and task identity, returning (restored original callback data, channel identifier string or None)."""
    if separator not in data:  # Legacy messages have no attached task identity and need no splitting or restoration.
        return data, None
    payload, _point, task = data.rpartition(separator)
    if not task:
        return payload, None
    return decompress_callback_data(payload), task


def resolve_chat_id(chat_filter: dict, task: Union[str, None]):
    """Resolve the actual channel ID from a task identity, supporting original dict keys of type int or str; return None if absent."""
    if task is None:
        return None
    if task in chat_filter:
        return task
    try:
        task_id: int = int(task)
    except ValueError:
        return None
    return task_id if task_id in chat_filter else None


class ChatInfo:
    TITLE: dict = {}

    @staticmethod
    def add(chat: Union[pyrogram.types.Chat, None], chat_id: Union[str, int, None] = None) -> None:
        """Cache a channel title so the web panel does not show only its ID."""
        if chat is None:
            return
        _chat_id: str = str(chat_id if chat_id is not None else getattr(chat, 'id', ''))
        title: str = str(getattr(chat, 'title', '') or getattr(chat, 'first_name', '') or '')
        if _chat_id and title:
            ChatInfo.TITLE[_chat_id] = title

    @staticmethod
    def get(chat_id: Union[str, int, None]) -> str:
        """Get the cached channel title, or an empty string if none exists."""
        return ChatInfo.TITLE.get(str(chat_id), '')


class LimitCall:  # https://github.com/tangyoha/telegram_media_downloader/blob/master/module/app.py#L246
    """Limit the number of calls within a time period."""

    def __init__(self, max_limit_call_times: int = 0):
        # Length of the time window, in seconds.
        self.time_window: int = 60
        # Maximum number of calls allowed in the time window.
        self.max_limit_call_times: int = max_limit_call_times
        # Number of calls made in the current time window.
        self.limit_call_times: int = 0
        # Start time of the current time window.
        self.last_call_time: float = 0

    async def wait(self):
        """Wait until the next time window when the call limit has been reached."""
        from module.stdio import ConnectionStatus
        waiting = False
        while True:
            now = time.time()
            time_span = now - self.last_call_time
            # Reset the counter and restart the window after it expires.
            if time_span > self.time_window:
                self.limit_call_times = 0
                self.last_call_time = now

            if self.limit_call_times + 1 <= self.max_limit_call_times:
                self.limit_call_times += 1
                # Notify once when waiting ends, then continue the request.
                if waiting:
                    ConnectionStatus.leave_flood()
                break

            if not waiting:
                waiting = True  # Notify only once at the limit to avoid printing every second.
                ConnectionStatus.enter_flood(
                    f'Request limit of {self.max_limit_call_times} per minute reached; retry in {int(self.time_window - time_span) + 1} second(s).'
                )

            await asyncio.sleep(1)


class AdjustableSemaphore:
    """A transfer semaphore with dynamically adjustable capacity (instead of creating a new asyncio.Semaphore for each change).

    When the web panel changes concurrency, replacing the client's semaphore with a new
    asyncio.Semaphore leaves active transfers holding slots in the old object, while the new
    object admits a full set of additional transfers. Peak concurrency can then become the
    number already transferring plus the new limit, exceeding the user's setting. Reuse one
    object instead: after lowering the limit, available capacity can be negative and new
    transfers wait until the active count falls within the limit. This avoids both exceeding
    the limit and having old and new semaphores coexist.

    Implements only the interfaces used by pyrogram and this project (acquire/release and async with).
    """

    def __init__(self, limit: int):
        self._limit: int = max(0, int(limit))
        self._held: int = 0  # Number of admitted transfers not yet released (the current active-transfer count).
        self._waiters: deque = deque()

    @property
    def limit(self) -> int:
        """Current concurrency limit."""
        return self._limit

    def locked(self) -> bool:
        """Whether there is currently no remaining capacity (same semantics as asyncio.Semaphore.locked())."""
        return self._limit <= 0 or self._held >= self._limit

    async def acquire(self) -> bool:
        """Acquire a slot, waiting in the queue if capacity is exhausted."""
        # Recheck after being woken: another waiter may have taken the available slot, requiring this one to wait again.
        while self.locked():
            waiter = asyncio.get_running_loop().create_future()
            self._waiters.append(waiter)
            try:
                await waiter
            except BaseException:
                if waiter.done():
                    # If cancelled after being woken (when a slot was available), pass the wake-up to another waiter;
                    # otherwise the slot is wasted and the remaining waiters may wait indefinitely.
                    self.__wake_up_next()
                else:
                    waiter.cancel()
                try:
                    self._waiters.remove(waiter)
                except ValueError:
                    pass
                raise
        self._held += 1
        return True

    def release(self) -> None:
        """Release a slot and try to admit a waiting transfer."""
        if self._held > 0:
            self._held -= 1
        self.__wake_up_next()

    def set_limit(self, limit: int) -> None:
        """Adjust the concurrency limit: increasing it admits waiters; lowering it makes new transfers wait for active transfers to finish."""
        self._limit = max(0, int(limit))
        self.__wake_up_next()

    def __wake_up_next(self) -> None:
        """Wake waiters one at a time up to the remaining capacity; any excess waiters will resume waiting."""
        while self._waiters and not self.locked():
            waiter = self._waiters.popleft()
            if not waiter.done():
                waiter.set_result(True)

    async def __aenter__(self) -> 'AdjustableSemaphore':
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.release()
        return False
