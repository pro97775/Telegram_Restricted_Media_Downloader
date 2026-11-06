# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2024-7-2 00:59:00
# File:enums.py
import os
import re
import sys
import time
import ipaddress
import platform

from functools import wraps
from dataclasses import dataclass
from typing import (
    Any,
    List,
    Union,
    Tuple,
    Optional,
    Callable
)

from module import (
    log,
    console
)
from module.language import _t


class LinkType:
    SINGLE: str = 'single'
    GROUP: str = 'group'
    COMMENT: str = 'comment'
    TOPIC: str = 'topic'


@dataclass
class Link:
    # https://github.com/tangyoha/telegram_media_downloader/blob/master/utils/format.py#L14
    group_id: Union[str, int, None] = None
    post_id: Optional[int] = None
    comment_id: Optional[int] = None
    topic_id: Optional[int] = None


class DownloadType:
    VIDEO: str = 'video'
    PHOTO: str = 'photo'
    DOCUMENT: str = 'document'
    AUDIO: str = 'audio'
    VOICE: str = 'voice'
    ANIMATION: str = 'animation'
    VIDEO_NOTE: str = 'video_note'
    LIVE_PHOTO: str = 'live_photo'

    PROXY_NOT_CONFIGURED = (
        '🛡 [#79FCD4]Proxy configuration[/#79FCD4][#FF79D4] instructions:[/#FF79D4]\n'
        '[link=https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/wiki]Open the troubleshooting wiki[/link]\n'
        '[#FCFF79]If the page is unavailable, consult issue 14 in the packaged[/#FCFF79] '
        '[#79E2FC]FAQ.pdf[/#79E2FC][#FCFF79].[/#FCFF79]'
    )
    SYSTEM_TIME_NOT_SYNCHRONIZED = (
        '🕒 [#FF7979]The system clock is not synchronized.[/#FF7979] '
        '[#79FCD4]See the troubleshooting discussion:[/#79FCD4]\n'
        'https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/issues/5#issuecomment-2580677184\n'
        '[#FCFF79]If unavailable, consult issue 4 in the packaged[/#FCFF79] '
        '[#79E2FC]FAQ.pdf[/#79E2FC][#FCFF79], then restart TRMD.[/#FCFF79]'
    )
    PROXY_CONFIG_TIP = (
        '❓ [#79FCD4]For proxy configuration help:[/#79FCD4]\n'
        '🌐 [link=https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/wiki]Open the troubleshooting wiki[/link]\n'
        '🛑 [#FCFF79]If unavailable, consult issue 14 in the packaged[/#FCFF79] '
        '[#79E2FC]FAQ.pdf[/#79E2FC][#FCFF79].[/#FCFF79]'
    )
    MULTI_SESSION_TIP = (
        '🔧 [#FF79D4]Choose one of the following options:[/#FF79D4]\n'
        '[#D4FC79]1. Close any extra application instances.[/#D4FC79]\n'
        '[#D4FC79]2. Run[/#D4FC79] "[#79FCD4]{exe} --session SESSION[/#79FCD4]" '
        '[#D4FC79]to retry with a different session location[/#D4FC79] '
        '([#FFB579]replace SESSION with the actual path[/#FFB579]).'
    )

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('_') and not callable(value):  # Exclude special methods and attributes.
                yield value


class DownloadStatus:
    PENDING = 'pending'
    DOWNLOADING = 'downloading'
    SUCCESS = 'success'
    FAILURE = 'failure'
    SKIP = 'skip'
    RETRY = 'retry'


class UploadStatus:
    PENDING = 'pending'
    UPLOADING = 'uploading'
    SUCCESS = 'success'
    FAILURE = 'failure'
    SENT = 'sent'


class NoticeType:
    DOWNLOAD: str = 'download'  # Download.
    UPLOAD: str = 'upload'  # Upload.
    FORWARD: str = 'forward'  # Forward.

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('_') and not callable(value):  # Exclude special methods and attributes.
                yield value


class CalenderKeyboard:
    START_TIME_BUTTON: str = 'start time button'
    END_TIME_BUTTON: str = 'end time button'


class SaveDirectoryPrefix:
    CHAT_ID: str = '%CHAT_ID%'
    CHAT_NAME: str = '%CHAT_NAME%'
    MIME_TYPE: str = '%MIME_TYPE%'
    MESSAGE_ID: str = '%MESSAGE_ID%'
    MESSAGE_ID_WITH_ENTITIES: str = '%MESSAGE_ID_WITH_ENTITIES%'

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('_') and not callable(value):  # Exclude special methods and attributes.
                yield value


class WebMeta:
    IP: str = 'IP'
    PORT: str = 'port'
    USERNAME: str = 'username'
    PASSWORD: str = 'password'
    COOKIE_NAME: str = 'TRMD_WEB_SESSION'
    DEFAULT_PORT: int = 2921


class KeyWord:
    LINK: str = 'link'
    LINK_TYPE: str = 'link type'
    SIZE: str = 'size'
    STATUS: str = 'status'
    FILE: str = 'file'
    ERROR_SIZE: str = 'error size'
    ACTUAL_SIZE: str = 'actual size'
    ALREADY_EXIST: str = 'already exist'
    CHANNEL: str = 'channel'
    MESSAGE_ID: str = 'message id'
    TYPE: str = 'type'
    RE_DOWNLOAD: str = 're-download'
    RE_UPLOAD: str = 're-upload'
    RETRY_TIMES: str = 'retry times'
    CURRENT_DOWNLOAD_TASK: str = 'current download task'
    CURRENT_UPLOAD_TASK: str = 'current upload task'
    REASON: str = 'reason'
    RESUME: str = 'resume'
    DOWNLOAD_TASK: str = 'download task'
    UPLOAD_TASK: str = 'upload task'
    DOWNLOAD_AND_UPLOAD_TASK: str = 'download and upload task'
    FORWARD_SUCCESS: str = 'forward success'
    FORWARD_FAILURE: str = 'forward failure'
    FORWARD_SKIP: str = 'skip forward'
    UPLOAD_FILE_PART: str = 'upload file part'


class ConnectionState:
    CONNECTED: str = 'connected'
    CONNECTING: str = 'connecting'


class WaitingKind:
    NONE: str = 'none'
    RECONNECT: str = 'reconnect'
    FLOOD: str = 'flood'


class Issues:
    PROXY_NOT_CONFIGURED = (
        '🛡️ [#79FCD4]For proxy configuration instructions, visit:[/#79FCD4]\n'
        '[link=https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/wiki#configuring-a-proxy-running-on-the-local-machine]Open the proxy setup guide[/link]\n'
        '[#FCFF79]If the page is unavailable, see[/#FCFF79] [#79E2FC]FAQ.pdf[/#79E2FC] '
        '[#FCFF79]in the packaged User Guide folder for Problem 14.[/#FCFF79]'
    )
    SYSTEM_TIME_NOT_SYNCHRONIZED = '🕒 [#FCFF79]Detected that the[/#FCFF79][#FF7979]system clock[/#FF7979][#FC79A5]is not synchronized[/#FC79A5][#79E2FC].[/#79E2FC][#79FCD4]For help,[/#79FCD4][#FF79D4]see:[/#FF79D4]\nhttps://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/issues/5#issuecomment-2580677184\n[#FCFF79]If the page is[/#FCFF79][#FF4689]unavailable[/#FF4689][#79FCD4],[/#79FCD4][#FCFF79]see[/#FCFF79][#FC79A5]the bundled[/#FC79A5][#79E2FC]User Guide[/#79E2FC][#79FCB5]for[/#79FCB5][#D479FC]Problem 4[/#D479FC][#FCE679], then restart TRMD.[/#FCE679]'
    DOCKER_HOST_IP_TIP = '🐳 In Docker, the IP address in the link is the container IP, not the host IP. Connect using the host IP and port.'
    PROXY_CONFIG_TIP = '❓ [#79FCD4]Questions about proxy configuration?[/#79FCD4][#FF79D4]See:[/#FF79D4]\n🌐 [link=https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/wiki#configuring-a-proxy-running-on-the-local-machine]https://github.com/Gentlesprite/Telegram_Restricted_Media_Downloader/wiki#configuring-a-proxy-running-on-the-local-machine[/link]\n🛑 [#FCFF79]If the page is[/#FCFF79][#FF4689]unavailable[/#FF4689][#79FCD4]:\n🔎 [/#79FCD4][#FCFF79]see[/#FCFF79][#FC79A5]the bundled[/#FC79A5][#79E2FC]User Guide[/#79E2FC][#79FCD4]folder and[/#79FCD4][#FFB579]FAQ.pdf[/#FFB579][#79FCB5]for[/#79FCB5][#D479FC]the solution to Problem 14[/#D479FC][#FCE679].[/#FCE679]'
    MULTI_SESSION_TIP = '🔧 [#FF79D4]Try one of these solutions:[/#FF79D4]\n[#D4FC79]1. Close any extra instances.[/#D4FC79]\n[#D4FC79]2. Specify a new session location with[/#D4FC79] "[#79FCD4]{exe} --session SESSION[/#79FCD4]"[#D4FC79] and try again.[/#D4FC79] ([#FFB579]Replace SESSION with the actual path.[/#FFB579])'

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('_') and not callable(value):  # Exclude special methods and attributes.
                yield value


class Extension:
    PHOTO = {
        'image/avif': 'avif',
        'image/bmp': 'bmp',
        'image/gif': 'gif',
        'image/ief': 'ief',
        'image/jpg': 'jpg',
        'image/jpeg': 'jpeg',
        'image/heic': 'heic',
        'image/heif': 'heif',
        'image/png': 'png',
        'image/svg+xml': 'svg',
        'image/tiff': 'tif',
        'image/vnd.microsoft.icon': 'ico',
        'image/x-cmu-raster': 'ras',
        'image/x-portable-anymap': 'pnm',
        'image/x-portable-bitmap': 'pbm',
        'image/x-portable-graymap': 'pgm',
        'image/x-portable-pixmap': 'ppm',
        'image/x-rgb': 'rgb',
        'image/x-xbitmap': 'xbm',
        'image/x-xpixmap': 'xpm',
        'image/x-xwindowdump': 'xwd'
    }
    VIDEO = {
        'video/mp4': 'mp4',
        'video/mpeg': 'mpg',
        'video/quicktime': 'qt',
        'video/webm': 'webm',
        'video/x-msvideo': 'avi',
        'video/x-sgi-movie': 'movie',
        'video/x-matroska': 'mkv'
    }
    REVERSE_PHOTO = {
        'avif': 'image/avif',
        'bmp': 'image/bmp',
        'gif': 'image/gif',
        'ief': 'image/ief',
        'jpg': 'image/jpg',
        'jpeg': 'image/jpeg',
        'heic': 'image/heic',
        'heif': 'image/heif',
        'png': 'image/png',
        'svg': 'image/svg+xml',
        'tif': 'image/tiff',
        'ico': 'image/vnd.microsoft.icon',
        'ras': 'image/x-cmu-raster',
        'pnm': 'image/x-portable-anymap',
        'pbm': 'image/x-portable-bitmap',
        'pgm': 'image/x-portable-graymap',
        'ppm': 'image/x-portable-pixmap',
        'rgb': 'image/x-rgb',
        'xbm': 'image/x-xbitmap',
        'xpm': 'image/x-xpixmap',
        'xwd': 'image/x-xwindowdump'
    }
    REVERSE_VIDEO = {
        'mp4': 'video/mp4',
        'mpg': 'video/mpeg',
        'qt': 'video/quicktime',
        'webm': 'video/webm',
        'avi': 'video/x-msvideo',
        'movie': 'video/x-sgi-movie',
        'mkv': 'video/x-matroska'
    }
    ALL_REVERSE = {
        'avif': 'image/avif',
        'bmp': 'image/bmp',
        'gif': 'image/gif',
        'ief': 'image/ief',
        'jpg': 'image/jpg',
        'jpeg': 'image/jpeg',
        'heic': 'image/heic',
        'heif': 'image/heif',
        'png': 'image/png',
        'svg': 'image/svg+xml',
        'tif': 'image/tiff',
        'ico': 'image/vnd.microsoft.icon',
        'ras': 'image/x-cmu-raster',
        'pnm': 'image/x-portable-anymap',
        'pbm': 'image/x-portable-bitmap',
        'pgm': 'image/x-portable-graymap',
        'ppm': 'image/x-portable-pixmap',
        'rgb': 'image/x-rgb',
        'xbm': 'image/x-xbitmap',
        'xpm': 'image/x-xpixmap',
        'xwd': 'image/x-xwindowdump',
        'video/mp4': 'mp4',
        'video/mpeg': 'mpg',
        'video/quicktime': 'qt',
        'video/webm': 'webm',
        'video/x-msvideo': 'avi',
        'video/x-sgi-movie': 'movie',
        'video/x-matroska': 'mkv'
    }


class GradientColor:
    # Gradient color source: https://photokit.com/colors/color-gradient/?lang=zh
    BLUE2PURPLE_14 = [
        '#0ebeff',
        '#21b4f9',
        '#33abf3',
        '#46a1ed',
        '#5898e8',
        '#6b8ee2',
        '#7d85dc',
        '#907bd6',
        '#a272d0',
        '#b568ca',
        '#c75fc5',
        '#da55bf',
        '#ec4cb9',
        '#ff42b3'
    ]
    GREEN2PINK_11 = [
        '#00ff40',
        '#14f54c',
        '#29eb58',
        '#3de064',
        '#52d670',
        '#66cc7c',
        '#7ac288',
        '#8fb894',
        '#a3ada0',
        '#b8a3ac',
        '#cc99b8'
    ]
    GREEN2BLUE_10 = [
        '#84fab0',
        '#85f6b8',
        '#86f1bf',
        '#88edc7',
        '#89e9ce',
        '#8ae4d6',
        '#8be0dd',
        '#8ddce5',
        '#8ed7ec',
        '#8fd3f4'
    ]
    YELLOW2GREEN_10 = [
        '#d4fc79',
        '#cdfa7d',
        '#c6f782',
        '#bff586',
        '#b8f28b',
        '#b2f08f',
        '#abed94',
        '#a4eb98',
        '#9de89d',
        '#96e6a1'
    ]
    ORANGE2YELLOW_15 = [
        '#f08a5d',
        '#f1915e',
        '#f1985f',
        '#f29f60',
        '#f3a660',
        '#f3ad61',
        '#f4b462',
        '#f5bc63',
        '#f5c364',
        '#f6ca65',
        '#f6d166',
        '#f7d866',
        '#f8df67',
        '#f8e668',
        '#f9ed69'
    ]
    NEW_LIFE = [
        '#43e97b',
        '#42eb85',
        '#41ed8f',
        '#3fee9a',
        '#3ef0a4',
        '#3df2ae',
        '#3cf4b8',
        '#3af5c3',
        '#39f7cd',
        '#38f9d7'
    ]
    RED_GRADIENT_15 = [
        '#ff0000',
        '#ff0011',
        '#ff0021',
        '#ff0032',
        '#ff0043',
        '#ff0053',
        '#ff0064',
        '#ff0075',
        '#ff0085',
        '#ff0096',
        '#ff1a9e',
        '#ff33a6',
        '#ff4db0',
        '#ff66b8',
        '#ff80c2'
    ]

    @staticmethod
    def __extend_gradient_colors(colors: list, target_length: int) -> list:
        extended_colors = colors[:]
        while len(extended_colors) < target_length:
            # Append the original list in reverse order, excluding its last item.
            extended_colors.extend(colors[-2::-1])
            # If it is still too short, append the remaining items in forward order.
            if len(extended_colors) < target_length:
                extended_colors.extend(colors[:-1])
        return extended_colors[:target_length]

    @staticmethod
    def gen_gradient_text(text: str, gradient_color: list) -> str:
        """Reverse and extend the gradient list when it is shorter than the text."""
        text_lst: list = [i for i in text]
        text_lst_len: int = len(text_lst)
        gradient_color_len: int = len(gradient_color)
        if text_lst_len > gradient_color_len:
            # Extend the color list to match the text length.
            gradient_color = GradientColor.__extend_gradient_colors(gradient_color, text_lst_len)
        result: str = ''
        for i in range(text_lst_len):
            result += f'[{gradient_color[i]}]{text_lst[i]}[/{gradient_color[i]}]'
        return result

    @staticmethod
    def __hex_to_rgb(hex_color: str) -> tuple:
        """Convert a hexadecimal color value to an RGB tuple."""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def __rgb_to_hex(r: int, g: int, b: int) -> str:
        """Convert an RGB tuple to a hexadecimal color value."""
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def generate_gradient(start_color: str, end_color: str, steps: int) -> list:
        """Generate a gradient list from the start and end colors."""
        steps = 2 if steps <= 1 else steps
        # Convert the start and end colors to RGB.
        start_rgb = GradientColor.__hex_to_rgb(start_color)
        end_rgb = GradientColor.__hex_to_rgb(end_color)
        # Build the gradient color list.
        gradient_color: list = []
        for i in range(steps):
            r = int(start_rgb[0] + (end_rgb[0] - start_rgb[0]) * i / (steps - 1))
            g = int(start_rgb[1] + (end_rgb[1] - start_rgb[1]) * i / (steps - 1))
            b = int(start_rgb[2] + (end_rgb[2] - start_rgb[2]) * i / (steps - 1))
            gradient_color.append(GradientColor.__rgb_to_hex(r, g, b))

        return gradient_color


class Banner:
    A = r'''
       ______           __  __                     _ __          
      / ____/__  ____  / /_/ /__  _________  _____(_) /____      
     / / __/ _ \/ __ \/ __/ / _ \/ ___/ __ \/ ___/ / __/ _ \     
    / /_/ /  __/ / / / /_/ /  __(__  ) /_/ / /  / / /_/  __/     
    \____/\___/_/ /_/\__/_/\___/____/ .___/_/  /_/\__/\___/      
                                   /_/                           
        '''
    B = r'''
    ╔═╗┌─┐┌┐┌┌┬┐┬  ┌─┐┌─┐┌─┐┬─┐┬┌┬┐┌─┐  
    ║ ╦├┤ │││ │ │  ├┤ └─┐├─┘├┬┘│ │ ├┤   
    ╚═╝└─┘┘└┘ ┴ ┴─┘└─┘└─┘┴  ┴└─┴ ┴ └─┘  
        '''
    C = r'''
     ██████╗ ███████╗███╗   ██╗████████╗██╗     ███████╗███████╗██████╗ ██████╗ ██╗████████╗███████╗    
    ██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝██║     ██╔════╝██╔════╝██╔══██╗██╔══██╗██║╚══██╔══╝██╔════╝    
    ██║  ███╗█████╗  ██╔██╗ ██║   ██║   ██║     █████╗  ███████╗██████╔╝██████╔╝██║   ██║   █████╗      
    ██║   ██║██╔══╝  ██║╚██╗██║   ██║   ██║     ██╔══╝  ╚════██║██╔═══╝ ██╔══██╗██║   ██║   ██╔══╝      
    ╚██████╔╝███████╗██║ ╚████║   ██║   ███████╗███████╗███████║██║     ██║  ██║██║   ██║   ███████╗    
     ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   ╚══════╝╚══════╝╚══════╝╚═╝     ╚═╝  ╚═╝╚═╝   ╚═╝   ╚══════╝           
            '''
    D = r'''                                                                          
                                            ,,                                       ,,                    
      .g8"""bgd                      mm   `7MM                                       db   mm               
    .dP'     `M                      MM     MM                                            MM               
    dM'       `   .gP"Ya `7MMpMMMb.mmMMmm   MM  .gP"Ya  ,pP"Ybd `7MMpdMAo.`7Mb,od8 `7MM mmMMmm .gP"Ya      
    MM           ,M'   Yb  MM    MM  MM     MM ,M'   Yb 8I   `"   MM   `Wb  MM' "'   MM   MM  ,M'   Yb     
    MM.    `7MMF'8M""""""  MM    MM  MM     MM 8M"""""" `YMMMa.   MM    M8  MM       MM   MM  8M""""""     
    `Mb.     MM  YM.    ,  MM    MM  MM     MM YM.    , L.   I8   MM   ,AP  MM       MM   MM  YM.    ,     
      `"bmmmdPY   `Mbmmd'.JMML  JMML.`Mbmo.JMML.`Mbmmd' M9mmmP'   MMbmmd' .JMML.   .JMML. `Mbmo`Mbmmd'     
                                                                  MM                                       
                                                                .JMML.                                     
        '''
    TRMD = r'''
    ████████╗██████╗ ███╗   ███╗██████╗ 
    ╚══██╔══╝██╔══██╗████╗ ████║██╔══██╗
       ██║   ██████╔╝██╔████╔██║██║  ██║
       ██║   ██╔══██╗██║╚██╔╝██║██║  ██║
       ██║   ██║  ██║██║ ╚═╝ ██║██████╔╝
       ╚═╝   ╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝
    '''


class Validator:

    @staticmethod
    def is_contain_chinese(text: str) -> bool:
        for ch in text:
            if u'\u4e00' <= ch <= u'\u9fff':
                log.warning('If downloads fail, try again using a path without Chinese characters.')
                return True
        return False

    @staticmethod
    def is_valid_api_id(api_id: str, valid_length: int = 32) -> bool:
        try:
            if len(api_id) < valid_length:
                if api_id.isdigit():
                    return True
                else:
                    log.warning(f'Invalid input: "{api_id}" is not numeric. Please try again.')
                    return False
            else:
                log.warning(f'Invalid API ID: "{api_id}" may be an API hash. Enter the correct API ID.')
                return False
        except (AttributeError, TypeError):
            log.error('When editing config.yaml manually, api_id must be enclosed in quotes.')
            return False

    @staticmethod
    def is_valid_api_hash(api_hash: str, valid_length: int = 32) -> bool:
        return len(str(api_hash)) == valid_length

    @staticmethod
    def is_valid_bot_token(bot_token: str, valid_format: str = ':') -> bool:
        if valid_format in bot_token:
            p = bot_token.split(valid_format)
            if len(p) == 2 and all(p):
                return True
        return False

    @staticmethod
    def is_valid_links_file(file_path: str, valid_format: str = '.txt') -> bool:
        file_path = os.path.normpath(file_path)
        return os.path.isfile(file_path) and file_path.endswith(valid_format)

    @staticmethod
    def is_valid_save_directory(save_directory: str) -> bool:
        for placeholder in SaveDirectoryPrefix():
            if placeholder in save_directory:
                save_directory = save_directory.replace(placeholder, '')
        save_directory = os.path.normpath(save_directory)
        if not os.path.exists(save_directory):
            while True:
                try:
                    question = console.input(f'Directory "{save_directory}" does not exist. Create it? - "y|n" (default: y):').strip().lower()
                    if question in ('y', ''):
                        os.makedirs(save_directory, exist_ok=True)
                        console.log(f'Created directory: "{save_directory}"')
                        break
                    elif question == 'n':
                        break
                    else:
                        log.warning(f'Unexpected input: "{question}". Valid options: "y|n".')
                except Exception as e:
                    log.error(f'Unexpected error. Reason: "{e}"')
                    break
        return os.path.isdir(save_directory)

    @staticmethod
    def is_valid_number(max_tasks: int) -> bool:
        try:
            return int(max_tasks) > 0
        except ValueError:
            return False
        except Exception as e:
            log.error(f'Unexpected error. Reason: "{e}"')
            return False

    @staticmethod
    def is_valid_enable_proxy(enable_proxy: Union[str, bool]) -> bool:
        if enable_proxy in ('y', 'n'):
            return True
        return False

    @staticmethod
    def is_valid_scheme(scheme: str, valid_format: list) -> bool:
        return scheme in valid_format

    @staticmethod
    def is_valid_hostname(hostname: str) -> bool:
        return isinstance(ipaddress.ip_address(hostname), ipaddress.IPv4Address)

    @staticmethod
    def is_valid_port(port: int) -> bool:
        try:
            return 0 < int(port) <= 65535
        except ValueError:  # Handle a string that is not an integer.
            return False
        except TypeError:  # Handle an input that is not numeric.
            return False
        except Exception as e:
            log.error(f'Unexpected error. Reason: "{e}"')
            return False

    @staticmethod
    def is_valid_download_type(dtype: list) -> bool:
        try:
            if isinstance(dtype, list):
                support_dtype: list = [_ for _ in DownloadType()]
                valid_dtype = []
                for i in dtype:
                    if i in support_dtype:
                        valid_dtype.append(i)
                    else:
                        log.warning(f'"{i}" is not a supported download type and was removed.')
                dtype[:] = valid_dtype
                return bool(dtype)
            return False
        except Exception as e:
            log.error(f'Unexpected error. Reason: "{e}"')
            return False


class ProcessConfig:
    PROXY_AUTO_FILL = False

    @staticmethod
    def __parse_proxy_url(proxy_url: str) -> Optional[dict]:
        """Parse a proxy URL string."""
        try:
            if not proxy_url:
                return None

            # Match proxy URLs in the following formats:
            # - http://username:password@host:port
            # - https://host:port
            # - socks4://host:port
            # - socks5://host:port
            # - host:port (without a scheme)
            # - URLs ending with /, such as http://127.0.0.1:10808/
            pattern = r'^(?:(https?|socks[45][ah]?)://)?(?:[^@]*@)?([^:]+):(\d+)/+$'
            match = re.match(pattern, proxy_url.lower())

            if not match:
                return None

            scheme = match.group(1)
            hostname = match.group(2)
            port = match.group(3)

            # Default to http when no scheme is provided.
            if not scheme:
                scheme = 'http'
            # Normalize socks4a and socks5h to socks4 and socks5.
            elif scheme in ('socks4a', 'socks5h'):
                scheme = scheme[:-1]

            # Validate the port number.
            try:
                port = int(port)
            except ValueError:
                return None

            if not (0 <= port <= 65535):
                return None

            return {
                'scheme': scheme,
                'hostname': hostname,
                'port': port
            }
        except Exception:  # noqa.
            return None

    @staticmethod
    def format_proxy_prompt(proxy: dict) -> str:
        return proxy.get('scheme', '') + '://' + proxy.get('hostname', '') + ':' + str(proxy.get('port', ''))

    @staticmethod
    def get_unix_proxy() -> Optional[dict]:
        """Get Unix/Linux/macOS proxy settings from environment variables."""
        env_vars = ['http_proxy', 'HTTP_PROXY', 'https_proxy', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']

        for var in env_vars:
            proxy_url = os.environ.get(var)
            if proxy_url:
                proxy_info = ProcessConfig.__parse_proxy_url(proxy_url)
                if proxy_info:
                    return proxy_info

        return None

    @staticmethod
    def get_windows_proxy() -> Optional[dict]:
        """Get proxy settings from the Windows registry."""
        try:
            import winreg
            with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r'Software\Microsoft\Windows\CurrentVersion\Internet Settings'
            ) as key:
                proxy_enable, _ = winreg.QueryValueEx(key, 'ProxyEnable')
                if not proxy_enable:
                    return None

                proxy_server, _ = winreg.QueryValueEx(key, 'ProxyServer')
                if not proxy_server:
                    return None

                # Parse the proxy server string with a regular expression.
                # It may look like "http=127.0.0.1:7890;https=127.0.0.1:7890;socks=127.0.0.1:1080".
                # It may also be a single address, such as "127.0.0.1:7890".
                proxy_info = {}
                pattern = r'(\w+)=([^;]+)'
                matches = re.findall(pattern, proxy_server)

                if matches:
                    for proto, addr in matches:
                        proxy_info[proto.lower()] = addr
                else:
                    # Without a protocol prefix, the entire string is the proxy address.
                    proxy_info['http'] = proxy_server

                # Priority: http > https > socks.
                proxy_addr = proxy_info.get('http') or proxy_info.get('https') or proxy_info.get('socks')

                if not proxy_addr:
                    return None

                # Parse the address and port with a regular expression.
                addr_pattern = r'^([^:]+):(\d+)$'
                addr_match = re.match(addr_pattern, proxy_addr)

                if not addr_match:
                    return None

                hostname = addr_match.group(1)
                try:
                    port = int(addr_match.group(2))
                except ValueError:
                    return None

                # Determine the proxy scheme.
                scheme = 'http'
                if 'socks5' in proxy_server.lower():
                    scheme = 'socks5'
                elif 'socks4' in proxy_server.lower():
                    scheme = 'socks4'
                elif 'socks=' in proxy_server.lower():
                    # Default to socks5 when socks= is present without a version number.
                    scheme = 'socks5'

                if not (0 <= port <= 65535):
                    return None

                return {
                    'scheme': scheme,
                    'hostname': hostname,
                    'port': port
                }

        except (WindowsError, OSError, ValueError):
            return None

    @staticmethod
    def get_system_proxy(param_name: str):

        def decorator(func: Callable) -> Callable:
            @wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                # Try to get the system proxy (cross-platform).
                system_proxy = ProcessConfig.get_windows_proxy() if platform.system() == 'Windows' else ProcessConfig.get_unix_proxy()
                # Continue if the system proxy was retrieved and contains the requested parameter.
                if system_proxy and param_name in system_proxy:
                    question: str = GetStdioParams.UNDEFINED
                    if param_name == 'scheme' and ProcessConfig.PROXY_AUTO_FILL is False:
                        while True:
                            try:
                                question = console.input(
                                    f'System proxy detected: "{ProcessConfig.format_proxy_prompt(system_proxy)}". Use it? - "y|n" (default: y):').strip().lower()
                                if question in ('y', ''):
                                    ProcessConfig.PROXY_AUTO_FILL = True
                                    break
                                elif question == 'n':
                                    break
                                else:
                                    log.warning(f'Unexpected input: "{question}". Valid options: "y|n".')
                            except Exception as e:
                                log.error(f'Unexpected error. Reason: "{e}"')
                                break
                    if question in ('y', '') or ProcessConfig.PROXY_AUTO_FILL:
                        # Extract the requested parameter value.
                        value = system_proxy[param_name]
                        # Display a message appropriate to the parameter type.
                        if param_name == 'scheme':
                            console.print(
                                f'Proxy type automatically obtained from system settings: "{value}"',
                                style=ProcessConfig.stdio_style('scheme')
                            )
                            return {
                                'scheme': value,
                                'record_flag': True
                            }
                        elif param_name == 'hostname':
                            console.print(
                                f'Proxy host automatically obtained from system settings: "{value}"',
                                style=ProcessConfig.stdio_style('hostname')
                            )
                            return {
                                'hostname': value,
                                'record_flag': True
                            }
                        elif param_name == 'port':
                            console.print(
                                f'Proxy port automatically obtained from system settings: "{value}"',
                                style=ProcessConfig.stdio_style('port')
                            )
                            return {
                                'port': value,
                                'record_flag': True
                            }

                # If no system proxy was found or it is incomplete, call the original function.
                return func(*args, **kwargs)

            return wrapper

        return decorator

    @staticmethod
    def set_dtype(_dtype: list) -> list:
        record_dtype: list = []
        support_dtype: list = [_ for _ in DownloadType()]
        for i in _dtype:
            if i in support_dtype:
                record_dtype.append(i)
        return record_dtype

    @staticmethod
    def get_dtype(download_dtype: list) -> dict:
        """Get the requested download types."""
        meta: dict = {}
        support_dtype: list = [_ for _ in DownloadType()]
        for dtype in download_dtype:
            meta[dtype] = True if dtype in support_dtype else False
        return meta

    @staticmethod
    def stdio_style(key: str, color=None) -> str:
        """Choose a gradient color for interactive prompts."""
        if color is None:
            color = GradientColor.ORANGE2YELLOW_15
        _stdio_queue: dict = {
            'api_id': 0,
            'api_hash': 1,
            'bot_token': 2,
            'links': 3,
            'save_directory': 4,
            'max_download_task': 5,
            'max_retry_count': 6,
            'download_type': 7,
            'is_shutdown': 8,
            'enable_proxy': 9,
            'config_proxy': 10,
            'scheme': 11,
            'hostname': 12,
            'port': 13,
            'proxy_authentication': 14
        }
        return color[_stdio_queue.get(key)]

    @staticmethod
    def is_proxy_input(proxy_config: dict) -> bool:
        """Check whether the proxy configuration requires user input."""
        result: bool = False
        basic_truth_table: list = []
        advance_account_truth_table: list = []
        if proxy_config.get('enable_proxy') is False:  # The proxy is disabled or its configuration is invalid.
            return False
        for _ in proxy_config.items():
            if _[0] in ['scheme', 'port', 'hostname']:
                basic_truth_table.append(_[1])
            if _[0] in ['username', 'password']:
                advance_account_truth_table.append(_[1])
        if all(basic_truth_table) is False:  # noqa.
            console.print('Please configure the proxy.', style=ProcessConfig.stdio_style('config_proxy'))
            console.print(Issues.PROXY_CONFIG_TIP)
            result: bool = True
        if any(advance_account_truth_table) and all(advance_account_truth_table) is False:
            log.warning('The proxy username or password has not been entered.')
            result: bool = True
        return result

    @staticmethod
    def get_proxy_info(proxy_config: dict) -> dict:
        return {
            'scheme': proxy_config.get('scheme', 'Unknown'),
            'hostname': proxy_config.get('hostname', 'Unknown'),
            'port': proxy_config.get('port', 'Unknown')
        }


class GetStdioParams:
    UNDEFINED: str = 'None'

    @staticmethod
    def __timeout_input(
            prompt: str = '',
            error_prompt: Union[str, None] = None,
            default: str = '',
            timeout: int = 5
    ) -> str:
        """Use the default value on timeout across platforms; fall back to regular input if an error occurs."""

        def timeout_notice():
            console.print('\nInput timed out; the default value was selected.\n', style='#FF4689')

        if sys.platform == 'win32':
            try:
                import msvcrt
                console.print(prompt, end='')
                start_time: float = time.time()
                input_buffer: list = []
                last_second: int = timeout
                countdown_displayed: bool = False

                while True:
                    elapsed = time.time() - start_time
                    remaining = int(timeout - elapsed)

                    # Update the countdown display.
                    if remaining != last_second and remaining >= 0:
                        if countdown_displayed:
                            # Erase the previous countdown (one digit and one space).
                            print('\b \b\b \b', end='', flush=True)
                        # Show the new countdown only before input begins.
                        if not input_buffer and remaining >= 0:
                            console.print(f'{remaining} ', end='', style='dim')
                            countdown_displayed = True
                        last_second = remaining

                    if msvcrt.kbhit():  # Check for keyboard input.
                        # Clear the countdown display.
                        if countdown_displayed:
                            print('\b \b\b \b', end='', flush=True)
                            countdown_displayed = False

                        char = msvcrt.getwch()
                        if char == '\r':  # Enter ends input.
                            user_input = ''.join(input_buffer)
                            print('\n') if user_input in ('y', 'n', '') else None
                            return user_input.strip() or default
                        elif char in ('\x08', '\b'):  # Handle Backspace.
                            if input_buffer:
                                input_buffer.pop()
                                print('\b \b', end='', flush=True)  # Delete the last character from the console.
                        elif char in ('\x00', '\xe0'):  # Arrow keys.
                            _ = msvcrt.getwch()
                        else:
                            input_buffer.append(char)
                            console.print(char, end='')
                        last_second = -1  # Stop displaying the countdown once input begins.
                    elif elapsed > timeout:
                        timeout_notice()
                        return default
                    time.sleep(0.1)
            except Exception as e:
                log.exception(f'Could not set this automatically. Please set it manually. {_t(KeyWord.REASON)}: "{e}"')
                return console.input(error_prompt if error_prompt else prompt)
        else:
            import tty
            import select
            import termios

            console.print(prompt, end='')
            sys.stdout.flush()

            # Save the original terminal settings.
            old_settings = termios.tcgetattr(sys.stdin)
            elapsed = 0
            try:
                # Set the terminal to raw mode to read input one character at a time.
                tty.setraw(sys.stdin.fileno())

                start_time: float = time.time()
                input_buffer: list = []
                last_second: int = timeout
                countdown_displayed: bool = False
                while True:
                    elapsed = time.time() - start_time
                    remaining = int(timeout - elapsed)

                    # Update the countdown display.
                    if remaining != last_second and remaining >= 0:
                        if countdown_displayed:
                            # Erase the previous countdown (digits and a space).
                            backspace_count = len(str(last_second)) + 1
                            sys.stdout.write('\b \b' * backspace_count)
                            sys.stdout.flush()
                        # Show the new countdown only before input begins.
                        if not input_buffer and remaining >= 0:
                            console.print(f'{remaining} ', end='', style='dim')
                            sys.stdout.flush()
                            countdown_displayed = True
                        last_second = remaining

                    # Poll input with select, timing out after 0.1 seconds to refresh the countdown.
                    ready, _, _ = select.select([sys.stdin], [], [], 0.1)

                    if ready:
                        # Clear the countdown display.
                        if countdown_displayed:
                            backspace_count = len(str(remaining)) + 1
                            sys.stdout.write('\b \b' * backspace_count)
                            sys.stdout.flush()
                            countdown_displayed = False

                        # Read one character.
                        char = sys.stdin.read(1)

                        if char == '\r' or char == '\n':  # Enter ends input.
                            user_input = ''.join(input_buffer)
                            sys.stdout.write('\n')
                            sys.stdout.flush()
                            return user_input.strip() or default
                        elif char == '\x7f' or char == '\b':  # Handle Backspace/Delete.
                            if input_buffer:
                                input_buffer.pop()
                                sys.stdout.write('\b \b')
                                sys.stdout.flush()
                        elif char == '\x1b':  # Escape sequence (arrow keys, etc.).
                            # Read the next two characters.
                            _ = sys.stdin.read(2)
                        elif ord(char) >= 32:  # Printable character.
                            input_buffer.append(char)
                            sys.stdout.write(char)
                            sys.stdout.flush()
                        last_second = -1  # Stop displaying the countdown once input begins.

                    elif elapsed > timeout:
                        # Clear the countdown display.
                        if countdown_displayed:
                            backspace_count = len(str(remaining)) + 1
                            sys.stdout.write('\b \b' * backspace_count)
                            sys.stdout.flush()
                        return default
            except Exception as e:
                log.exception(f'Could not set this automatically. Please set it manually. {_t(KeyWord.REASON)}: "{e}"')
                return console.input(error_prompt if error_prompt else prompt)
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)  # Restore the terminal settings.
                timeout_notice() if elapsed > timeout else print()

    @staticmethod
    def get_is_ki_save_config(valid_format: str = 'y|n') -> dict:
        while True:
            is_save_config: str = console.input(
                f'At exit, save the settings entered so far? - "{valid_format}":').strip().lower()
            if is_save_config == 'y':
                return {'is_ki_save_config': True}
            elif is_save_config == 'n':
                return {'is_ki_save_config': False}
            else:
                log.warning(f'Unexpected input: "{is_save_config}". Valid options: "{valid_format}".')

    @staticmethod
    def get_is_re_config(valid_format: str = 'y|n') -> dict:
        prompt: str = f'An existing configuration was found. Reconfigure it? (A backup will be created.) - "{valid_format}"'
        timeout: int = 5
        while True:
            is_re_config: str = GetStdioParams.__timeout_input(
                prompt=f'{prompt}:',
                error_prompt=f'{prompt} (default: n):',
                default='n',
                timeout=timeout
            ).strip().lower()
            if is_re_config == 'y':
                return {'is_re_config': True}
            elif is_re_config in ('n', ''):
                return {'is_re_config': False}
            else:
                console.print('\n') if sys.platform == 'win32' else None
                log.warning(f'Unexpected input: "{is_re_config}". Valid options: "{valid_format}" (default: n).')

    @staticmethod
    def get_is_change_account(valid_format: str = 'y|n') -> dict:
        style: str = '#FF4689'
        while True:
            is_change_account = console.input(
                'Switch accounts? - "y|n" (default: n):').strip().lower()
            if is_change_account in ('n', ''):
                console.print('No account switch requested.', style=style)
                return {'is_change_account': False}
            elif is_change_account == 'y':
                console.print('Account switch requested.', style=style)
                return {'is_change_account': True}
            else:
                log.warning(f'Unexpected input: "{is_change_account}". Valid options: "{valid_format}".')

    @staticmethod
    def get_session_directory():
        style: str = '#FF4689'
        while True:
            session_directory = console.input(
                'Enter the session directory (it may be empty or contain an existing logged-in session):').strip()
            console.print(f'Session directory set to: {session_directory}.', style=style)
            return {'session_directory': session_directory}

    @staticmethod
    def get_api_id(last_record: str) -> dict:
        while True:
            api_id = console.input(
                f'Enter the API ID. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}":').strip()
            if api_id == '' and last_record is not None:
                api_id = last_record
            if Validator.is_valid_api_id(api_id):
                console.print(f'API ID set to: "{api_id}"', style=ProcessConfig.stdio_style('api_id'))
                return {
                    'api_id': api_id,
                    'record_flag': True
                }

    @staticmethod
    def get_api_hash(last_record: str, valid_length: int = 32) -> dict:
        while True:
            api_hash = console.input(
                f'Enter the API hash. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}":').strip().lower()
            if api_hash == '' and last_record is not None:
                api_hash = last_record
            if Validator.is_valid_api_hash(api_hash, valid_length):
                console.print(f'API hash set to: "{api_hash}"', style=ProcessConfig.stdio_style('api_hash'))
                return {
                    'api_hash': api_hash,
                    'record_flag': True
                }
            else:
                log.warning(f'Invalid input: "{api_hash}". Enter a {valid_length}-character value. Please try again.')

    @staticmethod
    def get_enable_bot(valid_format: str = 'y|n') -> dict:
        while True:
            enable_bot = console.input('Enable the bot? (A bot token is required.) - "y|n" (default: n):').strip().lower()
            if enable_bot in ('n', ''):
                console.print('Bot disabled.', style=ProcessConfig.stdio_style('bot_token'))
                return {'enable_bot': False}
            elif enable_bot == 'y':
                console.print('Configure the bot token.', style=ProcessConfig.stdio_style('bot_token'))
                return {'enable_bot': True}
            else:
                log.warning(f'Unexpected input: "{enable_bot}". Valid options: "{valid_format}".')

    @staticmethod
    def get_bot_token(last_record: str, valid_format: str = ':') -> dict:
        while True:
            bot_token = console.input(
                f'Enter the bot token for this account. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}":').strip()
            if bot_token == '' and last_record is not None:
                bot_token = last_record
            if Validator.is_valid_bot_token(bot_token, valid_format):
                console.print(f'Bot token set to: "{bot_token}"', style=ProcessConfig.stdio_style('bot_token'))
                return {
                    'bot_token': bot_token,
                    'record_flag': True
                }
            else:
                log.warning(f'Invalid input: "{bot_token}". The bot token must contain a colon (:). Please try again.')

    @staticmethod
    def get_links(last_record: str, valid_format: str = '.txt', enable_bot: bool = False) -> dict:
        # Prompt for the media links file and ensure that it exists.
        links_file_path = None
        while True:
            try:
                bot_notice = '(bot is configured; this step may be skipped)' if enable_bot else ''
                links_file_path = console.input(
                    f'Enter the full path to the media links file. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                    f'Format: "{valid_format}" {bot_notice}:').strip()
                if links_file_path == '':
                    if last_record is not None:
                        links_file_path = last_record
                    elif bot_notice:
                        links_file_path = os.path.join(os.getcwd(), 'links.txt')
                if links_file_path and not os.path.exists(links_file_path):
                    try:
                        with open(file=links_file_path, mode='w', encoding='UTF-8'):
                            pass
                    except Exception as e:
                        log.warning(f'Could not create file "{links_file_path}". Check file permissions. {_t(KeyWord.REASON)}: "{e}"')
                if Validator.is_valid_links_file(links_file_path, valid_format):
                    console.print(f'Links file set to: "{links_file_path}"', style=ProcessConfig.stdio_style('links'))
                    Validator.is_contain_chinese(links_file_path)
                    return {
                        'links': links_file_path,
                        'record_flag': True
                    }
                elif not os.path.normpath(links_file_path).lower().endswith('.txt'):
                    log.warning(f'Invalid input: "{links_file_path}". The file path must end with "{valid_format}". Please try again.')
                else:
                    log.warning(
                        f'Invalid input: "{links_file_path}". The file must exist (case-sensitive). Please try again.')
            except Exception as e:
                log.warning(
                    f'Invalid input: "{links_file_path}". The file path must end with "{valid_format}" and the file must exist. Please try again. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def get_save_directory(last_record) -> dict:
        # Prompt for the media save path and ensure it is a valid directory.
        while True:
            save_directory = console.input(
                f'Enter the media save directory. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}":').strip()
            if save_directory == '':
                if last_record is not None:
                    save_directory = last_record
                else:
                    save_directory = os.path.join(os.getcwd(), 'downloads')
                    log.warning('No previous value found; using the default directory.')
            if Validator.is_valid_save_directory(save_directory):
                console.print(f'Save directory set to: "{save_directory}"',
                              style=ProcessConfig.stdio_style('save_directory'))
                Validator.is_contain_chinese(save_directory)
                return {
                    'save_directory': save_directory,
                    'record_flag': True
                }
            elif os.path.isfile(save_directory):
                log.warning(f'Invalid input: "{save_directory}". The specified path is a file, not a directory. Please try again.')
            else:
                log.warning(f'Invalid input: "{save_directory}". The path is invalid or is not a directory. Please try again.')

    @staticmethod
    def get_max_download_task(last_record) -> dict:
        # Prompt for the maximum number of download tasks and validate the integer value.
        default_prompt: str = '(default: 3)' if last_record is None else ''
        while True:
            try:
                max_download_task = console.input(
                    f'Enter the maximum number of concurrent downloads. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                    f'. A value that is too high may cause network issues; the recommended value is {default_prompt}:').strip()
                if max_download_task == '' and last_record is not None:
                    max_download_task = last_record
                if max_download_task == '':
                    max_download_task = 3
                if Validator.is_valid_number(max_download_task):
                    console.print(f'Maximum concurrent downloads set to: "{max_download_task}"',
                                  style=ProcessConfig.stdio_style('max_download_task'))
                    return {
                        'max_download_task': int(max_download_task),
                        'record_flag': True
                    }
                else:
                    log.warning(f'Invalid input: "{max_download_task}". The task count must be a positive integer. Please try again.')
            except Exception as e:
                log.error(f'Unexpected error. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def get_max_retry_count(last_record) -> dict:
        default_prompt: str = '(default: 5)' if last_record is None else ''
        while True:
            try:
                max_retry_count = console.input(
                    f'Enter the maximum number of retries after a task fails. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}" {default_prompt}:').strip()
                if max_retry_count == '' and last_record is not None:
                    max_retry_count = last_record
                if max_retry_count == '':
                    max_retry_count = 5
                if Validator.is_valid_number(max_retry_count):
                    console.print(f'Maximum retry count set to: "{max_retry_count}"',
                                  style=ProcessConfig.stdio_style('max_retry_count'))
                    return {
                        'max_retry_count': int(max_retry_count),
                        'record_flag': True
                    }
                else:
                    log.warning(f'Invalid input: "{max_retry_count}". The maximum retry count must be a positive integer. Please try again.')
            except Exception as e:
                log.error(f'Unexpected error. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def get_download_type(last_record: Union[list, None]) -> dict:
        if isinstance(last_record, list):
            meta: dict = ProcessConfig.get_dtype(download_dtype=last_record)
            record: list = []
            for i in meta.items():
                dtype, _ = i
                if meta.get(dtype) is True:  # noqa.
                    record.append(dtype)
            last_record: str = ' '.join(record)
        default_prompt: str = '(defaults to all supported types)' if last_record is None else ''
        while True:
            download_type: Union[str, list] = console.input(
                f'Enter the media types to download (separate multiple types with spaces). Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                f'Valid types: "video photo document audio voice animation video_note live_photo" {default_prompt}:').strip()
            if download_type == '' and last_record is not None:
                download_type = last_record
            if download_type == '':
                download_type = [_ for _ in DownloadType()]
            download_type: list = list(set(download_type.split())) if isinstance(download_type, str) else download_type
            if Validator.is_valid_download_type(download_type):
                dtype = ' '.join(download_type) if download_type else [_ for _ in DownloadType()]
                console.print(
                    f'Download types set to: "{dtype}"',
                    style=ProcessConfig.stdio_style('download_type')
                )
                return {
                    'download_type': ProcessConfig.set_dtype(_dtype=download_type),
                    'record_flag': True
                }
            else:
                prompt: str = f'Invalid input: "{download_type}"' if download_type else 'Please enter the download types again'
                log.warning(f'{prompt}. Valid types: "video photo document" (separate multiple types with spaces).')

    @staticmethod
    def get_is_shutdown(last_record: str, valid_format: str = 'y|n') -> dict:
        _style: str = ProcessConfig.stdio_style('is_shutdown')
        if last_record:
            last_record: str = 'y'
        elif last_record is False:  # noqa.
            last_record: str = 'n'
        else:
            last_record = GetStdioParams.UNDEFINED
        t = 'Automatic shutdown after downloads enabled.'  # v1.3.0: fix an incorrect message for the is_shutdown setting.
        f = 'Automatic shutdown after downloads disabled.'
        default_prompt: str = '(default: n)' if last_record == GetStdioParams.UNDEFINED else ''
        while True:
            try:
                is_shutdown = console.input(
                    f'Automatically shut down after downloads finish? Previous value: "{last_record}" - "{valid_format}"'
                    f'{default_prompt}:').strip().lower()
                if is_shutdown == '' and last_record != GetStdioParams.UNDEFINED:
                    if last_record == 'y':
                        console.print(t, style=_style)
                        return {'is_shutdown': True, 'record_flag': True}
                    elif last_record == 'n':
                        console.print(f, style=_style)
                        return {'is_shutdown': False, 'record_flag': True}

                elif is_shutdown == 'y':
                    console.print(t, style=_style)
                    return {'is_shutdown': True, 'record_flag': True}
                elif is_shutdown in ('n', ''):
                    console.print(f, style=_style)
                    return {'is_shutdown': False, 'record_flag': True}
                else:
                    log.warning(f'Unexpected input: "{is_shutdown}". Valid options: "{valid_format}".')

            except Exception as e:
                log.error(f'Unexpected error. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def get_enable_proxy(last_record: Union[str, bool], valid_format: str = 'y|n') -> dict:
        if last_record:
            ep_notice: str = 'y' if last_record else 'n'
        else:
            ep_notice: str = GetStdioParams.UNDEFINED
        default_prompt: str = '(default: n)' if ep_notice == GetStdioParams.UNDEFINED else ''
        while True:  # Ask whether to enable the proxy.
            enable_proxy = console.input(
                f'Use a proxy? Previous value: "{ep_notice}"'
                f'Options: "{valid_format}" {default_prompt}:').strip().lower()
            if enable_proxy == '' and last_record is not None:
                if last_record is True:
                    enable_proxy = 'y'
                elif last_record is False:
                    enable_proxy = 'n'
            elif enable_proxy == '':
                enable_proxy = 'n'
            if Validator.is_valid_enable_proxy(enable_proxy):
                if enable_proxy == 'y':
                    console.print(f'Proxy usage set to: "{enable_proxy}"',
                                  style=ProcessConfig.stdio_style('enable_proxy'))
                    return {'enable_proxy': True, 'record_flag': True}
                elif enable_proxy == 'n':
                    console.print(f'Proxy usage set to: "{enable_proxy}"',
                                  style=ProcessConfig.stdio_style('enable_proxy'))
                    return {'enable_proxy': False, 'record_flag': True}
            else:
                log.error(f'Invalid input: "{enable_proxy}". Enter a valid option: "{valid_format}".')

    @staticmethod
    @ProcessConfig.get_system_proxy('scheme')
    def get_scheme(last_record: str, valid_format: list) -> dict:
        if valid_format is None:
            valid_format: list = ['http', 'socks4', 'socks5']
        fmt_valid_format = '|'.join(valid_format)
        while True:  # v1.3.0: fix an AttributeError when configuring the proxy scheme.
            scheme = console.input(
                f'Enter the proxy type. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                f'Valid types: "{fmt_valid_format}":').strip().lower()
            if scheme == '' and last_record is not None:
                scheme = last_record
            if Validator.is_valid_scheme(scheme, valid_format):
                console.print(f'Proxy type set to: "{scheme}"', style=ProcessConfig.stdio_style('scheme'))
                return {
                    'scheme': scheme,
                    'record_flag': True
                }
            else:
                log.warning(
                    f'Invalid input: "{scheme}". Enter a valid proxy type: "{fmt_valid_format}".')

    @staticmethod
    @ProcessConfig.get_system_proxy('hostname')
    def get_hostname(proxy_config: dict, last_record: str, valid_format: str = 'x.x.x.x'):
        hostname = None
        while True:
            scheme, _, __ = ProcessConfig.get_proxy_info(proxy_config).values()
            # Prompt for the proxy IP address.
            try:
                hostname = console.input(
                    f'Enter the IP address for the "{scheme}" proxy. Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                    f'Format: "{valid_format}":').strip()
                if hostname == '' and last_record is not None:
                    hostname = last_record
                if Validator.is_valid_hostname(hostname):
                    console.print(f'Proxy host set to: "{hostname}"', style=ProcessConfig.stdio_style('hostname'))
                    return {
                        'hostname': hostname,
                        'record_flag': True
                    }
            except ValueError:
                log.warning(
                    f'"{hostname}" is not a valid IP address. Enter a valid IPv4 address: "{valid_format}".')

    @staticmethod
    @ProcessConfig.get_system_proxy('port')
    def get_port(proxy_config: dict, last_record: str, valid_format: str = '0~65535'):
        port = None
        # Prompt for the proxy port.
        while True:
            try:  # hostname or scheme may be None.
                scheme, hostname, __ = ProcessConfig.get_proxy_info(proxy_config).values()
                port = console.input(
                    f'Enter the proxy port for IP "{hostname}" and type "{scheme}".'
                    f' Previous value: "{last_record if last_record else GetStdioParams.UNDEFINED}"'
                    f' Format: "{valid_format}":').strip()
                if port == '' and last_record is not None:
                    port = last_record
                if Validator.is_valid_port(port):
                    console.print(f'Proxy port set to: "{port}"', style=ProcessConfig.stdio_style('port'))
                    return {
                        'port': int(port),
                        'record_flag': True
                    }
                else:
                    log.warning(f'Invalid input: "{port}". The port must be in the range "{valid_format}".')
            except ValueError:
                log.warning(f'Invalid input: "{port}". Enter a valid integer in the range "{valid_format}".')
            except Exception as e:
                log.error(f'Unexpected error. {_t(KeyWord.REASON)}: "{e}"')

    @staticmethod
    def get_proxy_authentication():
        # Ask whether authentication is required.
        style = ProcessConfig.stdio_style('proxy_authentication')
        valid_format: str = 'y|n'
        while True:
            is_proxy = console.input(f'Does the proxy require authentication? - "{valid_format}" (default: n):').strip().lower()
            if is_proxy == 'y':
                username = console.input('Enter the username:').strip()
                password = console.input('Enter the password:').strip()
                console.print('Proxy authentication enabled.', style=style)
                return {'username': username, 'password': password, 'record_flag': True}
            elif is_proxy in ('n', ''):
                console.print('Proxy authentication disabled.', style=style)
                return {'username': None, 'password': None, 'record_flag': True}
            else:
                log.warning(f'Unexpected input: "{is_proxy}". Valid options: "{valid_format}".')


class BotCommandText:
    HELP: tuple = ('help', 'Show available commands.\n`/help`')
    DOWNLOAD: tuple = (
        'download', 'Create a download task. See the help menu for usage examples.\n`/download https://t.me/x/x start_id end_id`')
    TABLE: tuple = ('table', 'Show current download statistics in the terminal.\n`/table`')
    FORWARD: tuple = ('forward', 'Forward messages from a source channel to a destination channel within an ID range.\n`/forward https://t.me/A https://t.me/B 1 100`')
    EXIT: tuple = ('exit', 'Exit the application.\n`/exit`')
    LISTEN_DOWNLOAD: tuple = ('listen_download',
                              'Monitor the specified links for new messages and download them as they arrive.\n`/listen_download https://t.me/A https://t.me/B https://t.me/n`')
    LISTEN_FORWARD: tuple = (
        'listen_forward', 'Monitor a channel for new messages and forward them as they arrive.\n`/listen_forward source_channel destination_channel`')
    LISTEN_INFO: tuple = ('listen_info', 'View the listeners currently registered.\n`/listen_info`')
    UPLOAD: tuple = ('upload', 'Upload a local file to a specified channel.\n`/upload local_file destination_channel`')
    UPLOAD_R: tuple = ('upload_r', 'Recursively upload a folder, including its subfolders, to a specified channel.\n`/upload_r local_folder destination_channel`')
    DOWNLOAD_CHAT: tuple = ('download_chat',
                            'Download channel content that matches filters you configure.\n`/download_chat channel_link`')
    AUTH: tuple = ('auth',
                   'Add, remove, or list users authorized to use the bot. Accepts user IDs or @usernames.\n`/auth`, `/auth 1234567890`, or `/auth @username`')

    @staticmethod
    def with_description(text: tuple) -> str:
        return f'/{text[0]} - {text[1]}'

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('_') and not callable(value):  # Exclude special methods and attributes.
                yield value

    @staticmethod
    def commands() -> List[str]:
        return [_[0] for _ in BotCommandText()]

    @staticmethod
    def commands_with_prefix() -> List[str]:
        return [f'/{_}' for _ in BotCommandText.commands()]


class BotCallbackText:
    NULL: str = 'null'
    PAY: str = 'pay'
    LINK_TABLE: str = 'link_table'
    COUNT_TABLE: str = 'count_table'
    UPLOAD_TABLE: str = 'upload_table'
    BACK_HELP: str = 'back_help'
    BACK_TABLE: str = 'back_table'
    NOTICE: str = 'notice'
    DOWNLOAD: str = 'download'
    DOWNLOAD_UPLOAD: str = 'download_upload'
    REMOVE_LISTEN_DOWNLOAD: str = 'rld'
    REMOVE_LISTEN_FORWARD: str = 'rlf'
    REMOVE_AUTH_USER: str = 'remove_auth'
    LOOKUP_LISTEN_INFO: str = 'lookup_listen_info'
    LOOKUP_AUTH_INFO: str = 'lookup_auth_info'
    AUTH: str = 'auth'
    CANCEL_AUTH_INPUT: str = 'cancel_auth_input'
    EXPORT_LINK_TABLE: str = 'export_link_table'
    EXPORT_COUNT_TABLE: str = 'export_count_table'
    EXPORT_UPLOAD_TABLE: str = 'export_upload_table'
    TOGGLE_LINK_TABLE: str = 'toggle_link_table'
    TOGGLE_COUNT_TABLE: str = 'toggle_count_table'
    TOGGLE_UPLOAD_TABLE: str = 'toggle_upload_table'
    TOGGLE_FORWARD_VIDEO: str = 'toggle_forward_video'
    TOGGLE_FORWARD_PHOTO: str = 'toggle_forward_photo'
    TOGGLE_FORWARD_AUDIO: str = 'toggle_forward_audio'
    TOGGLE_FORWARD_VOICE: str = 'toggle_forward_voice'
    TOGGLE_FORWARD_ANIMATION: str = 'toggle_forward_animation'
    TOGGLE_FORWARD_DOCUMENT: str = 'toggle_forward_document'
    TOGGLE_FORWARD_TEXT: str = 'toggle_forward_text'
    TOGGLE_FORWARD_VIDEO_NOTE: str = 'toggle_forward_video_note'
    TOGGLE_FORWARD_LIVE_PHOTO: str = 'toggle_forward_live_photo'
    TOGGLE_DOWNLOAD_VIDEO: str = 'toggle_download_video'
    TOGGLE_DOWNLOAD_PHOTO: str = 'toggle_download_photo'
    TOGGLE_DOWNLOAD_AUDIO: str = 'toggle_download_audio'
    TOGGLE_DOWNLOAD_VOICE: str = 'toggle_download_voice'
    TOGGLE_DOWNLOAD_ANIMATION: str = 'toggle_download_animation'
    TOGGLE_DOWNLOAD_DOCUMENT: str = 'toggle_download_document'
    TOGGLE_DOWNLOAD_VIDEO_NOTE: str = 'toggle_download_video_note'
    TOGGLE_DOWNLOAD_LIVE_PHOTO: str = 'toggle_download_live_photo'
    EXPORT_TABLE: str = 'export_table'
    SHUTDOWN: str = 'shutdown'
    SETTING: str = 'setting'
    UPLOAD_SETTING: str = 'upload_setting'
    DOWNLOAD_SETTING: str = 'download_setting'
    FORWARD_SETTING: str = 'forward_setting'
    UPLOAD_DOWNLOAD: str = 'upload_download'
    UPLOAD_DOWNLOAD_DELETE: str = 'upload_download_delete'
    DOWNLOAD_CHAT_ID: str = 'download_chat_id'
    DOWNLOAD_CHAT_ID_CANCEL: str = 'download_chat_id_cancel'
    DOWNLOAD_CHAT_FILTER: str = 'download_chat_filter'
    DOWNLOAD_CHAT_DATE_FILTER: str = 'download_chat_date_filter'
    DOWNLOAD_CHAT_DTYPE_FILTER: str = 'download_chat_dtype_filter'
    DOWNLOAD_CHAT_KEYWORD_FILTER: str = 'download_chat_keyword_filter'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO: str = 'toggle_download_chat_video'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_PHOTO: str = 'toggle_download_chat_photo'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_AUDIO: str = 'toggle_download_chat_audio'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_VOICE: str = 'toggle_download_chat_voice'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_ANIMATION: str = 'toggle_download_chat_animation'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_DOCUMENT: str = 'toggle_download_chat_document'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_VIDEO_NOTE: str = 'toggle_download_chat_video_note'
    TOGGLE_DOWNLOAD_CHAT_DTYPE_LIVE_PHOTO: str = 'toggle_download_chat_live_photo'
    TOGGLE_DOWNLOAD_CHAT_COMMENT: str = 'toggle_download_chat_comment'
    CALENDAR_CONFIRM: str = 'calendar_confirm'
    FILTER_START_DATE: str = 'filter_start_date'
    FILTER_END_DATE: str = 'filter_end_date'
    DROP_KEYWORD: str = 'drop_keyword'
    IGNORE_KEYWORD: str = 'ignore_keyword'
    CONFIRM_KEYWORD: str = 'confirm_keyword'
    CANCEL_KEYWORD_INPUT: str = 'cancel_keyword_input'
    COMMAND_DOWNLOAD: str = 'cmd_download'
    COMMAND_UPLOAD: str = 'cmd_upload'
    COMMAND_UPLOAD_R: str = 'cmd_upload_r'
    COMMAND_DOWNLOAD_CHAT: str = 'cmd_download_chat'
    COMMAND_FORWARD: str = 'cmd_forward'
    MENU_DOWNLOAD: str = 'menu_download'
    MENU_LISTEN: str = 'menu_listen'
    MENU_UPLOAD: str = 'menu_upload'
    MENU_AUTH: str = 'menu_auth'
    VIEW_AUTH_LIST: str = 'view_auth_list'
    MENU_BACK: str = 'menu_back'
    LISTEN_DOWNLOAD_BTN: str = 'cmd_listen_download'
    LISTEN_FORWARD_BTN: str = 'cmd_listen_forward'

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('__') and not callable(value):  # Exclude special methods and attributes.
                yield value


class BotCallbackPrefix:
    """Fixed prefixes for callback data, followed by dynamic parameters (dates, years, keywords, etc.).

    Unlike BotCallbackText, these values are matched as prefixes and callback data includes additional parameters.
    Use these values when compressing callback data as well, so the two representations cannot drift apart.
    """
    TIME_INC: str = 'time_inc_'
    TIME_DEC: str = 'time_dec_'
    SET_TIME: str = 'set_time_'
    SET_SPECIFIC_TIME: str = 'set_specific_time_'
    ADJUST_STEP: str = 'adjust_step_'
    SELECT_YEAR: str = 'select_year_'
    SET_YEAR: str = 'set_year_'
    DROP_KEYWORD: str = 'drop_keyword_'
    IGNORE_KEYWORD: str = 'ignore_keyword'

    def __iter__(self):
        for key, value in vars(self.__class__).items():
            if not key.startswith('__') and not callable(value):  # Exclude special methods and attributes.
                yield value


class Emoji:
    SEARCH: Tuple[str, str] = ('🔎', '🔍')
    HOURGLASS: Tuple[str, str] = ('⏳', '⌛')


class BotStepKeyword:
    LINK = 'link'
    PATH = 'path'
    TARGET = 'target'
    ORIGIN = 'origin'
    START_ID = 'start_id'
    END_ID = 'end_id'


class BotStepText:
    DOWNLOAD_LINK: tuple = (BotStepKeyword.LINK, '⬇️ Send the link you want to download.')
    DOWNLOAD_CHAT_LINK: tuple = (BotStepKeyword.LINK, '💬 Send the channel link you want to download.')
    UPLOAD_PATH: tuple = (BotStepKeyword.PATH, '📤 Send the local file path to upload.')
    UPLOAD_TARGET: tuple = (BotStepKeyword.TARGET, '📤 Send the link of the destination channel.')
    UPLOAD_R_PATH: tuple = (BotStepKeyword.PATH, '📁 Send the local folder path to upload.')
    UPLOAD_R_TARGET: tuple = (BotStepKeyword.TARGET, '📁 Send the link of the destination channel.')
    FORWARD_ORIGIN: tuple = (BotStepKeyword.ORIGIN, '↗️ Send the source channel link.')
    FORWARD_TARGET: tuple = (BotStepKeyword.TARGET, '↗️ Send the link of the destination channel.')
    FORWARD_START_ID: tuple = (BotStepKeyword.START_ID, '↗️ Send the starting message ID (a number).')
    FORWARD_END_ID: tuple = (BotStepKeyword.END_ID, '↗️ Send the ending message ID (a number).')
    LISTEN_DOWNLOAD_ORIGIN: tuple = (BotStepKeyword.ORIGIN, '🕵️ Send the link of the channel to monitor for downloads.')
    LISTEN_FORWARD_ORIGIN: tuple = (BotStepKeyword.ORIGIN, '📲 Send the link of the channel to monitor.')
    LISTEN_FORWARD_TARGET: tuple = (BotStepKeyword.TARGET, '📲 Send the link of the destination channel.')


class BotMessage:
    RIGHT: str = '✅ Download tasks created for the following links:\n'
    INVALID: str = '🚫 The following invalid links were removed:\n'
    TASK_ASSIGN: str = '🌟 Task assigned.'
    TOO_MANY_MESSAGE: str = '⚠️ Message is too long; individual items will not be shown.'
    TOO_MANY_INVALID_DOWNLOAD_MESSAGE: str = '⚠️ {count} messages were skipped because they are invalid. Too many to list individually.'
    TOO_MANY_INVALID_FORWARD_MESSAGE: str = '⚠️ {count} messages were skipped because they do not exist. Too many to list individually.'


class BotButton:
    GITHUB: str = '📦GitHub'
    SUBSCRIBE_CHANNEL: str = '📌 Subscribe to channel'
    VIDEO_TUTORIAL: str = '🎬 Video tutorial'
    PROXY_SELLER: str = '🛒 Buy proxy'
    PAY: str = '💰 Support the developer'
    OPEN_NOTICE: str = '💬 Startup notice | Off ❌'
    CLOSE_NOTICE: str = '💬 Startup notice | On ✅'
    LINK_TABLE: str = '🔗 Link statistics'
    COUNT_TABLE: str = '➕ Count statistics'
    UPLOAD_TABLE: str = '📤 Upload statistics'
    HELP_PAGE: str = '🛎️ Help page'
    CLICK_VIEW: str = '🖱 Click to view'
    CLICK_DOWNLOAD: str = '🖱 Click to download'
    DOWNLOAD: str = '⬇️ Download'
    DOWNLOAD_UPLOAD: str = '↕️ Download and upload'
    TASK_ASSIGN: str = '🌟 Task assigned'
    RETRIEVE_MESSAGE: str = '🔎 Searching messages'
    RETRIEVE_COMMENT: str = '🔎 Searching comments'
    ASSIGNING_TASK: str = '🚛 Assigning task'
    DOWNLOAD_TASK_DOING: str = '⬇️ Download in progress'
    DOWNLOAD_TASK_DONE: str = '✅ Download complete'
    TASK_CANCEL: str = '🗑️ Task canceled'
    EXECUTE_TASK: str = '▶️ Run task'
    CANCEL_TASK: str = '⏹️ Cancel task'
    OK: str = '✅ Confirm'
    CANCEL: str = '❌ Cancel'
    DROP: str = '🗑️ Remove'
    REMOVE_AUTH: str = '🗑️ Remove authorization'
    IGNORE: str = '👁️‍🗨️ Ignore'
    RETURN: str = '🔙 Back'
    CONFIRM_AND_RETURN: str = '↩️ Confirm and go back'
    LOOKUP_LISTEN_INFO: str = '🔍 View listener details'
    LOOKUP_AUTH_INFO: str = '🔍 View authorized users'
    AUTH: str = '🔑 Add/remove authorized users'
    VIEW_AUTH_LIST: str = '👥 View authorized users'
    EXPORT_TABLE: str = '📊 Export table settings'
    RESELECT: str = '🔄 Select again'
    SETTING: str = '⚙️ Settings'
    MENU_DOWNLOAD: str = '📁 Download'
    MENU_LISTEN: str = '🕵️ Monitor'
    MENU_UPLOAD: str = '📤 Upload'
    DOWNLOAD_MENU_TITLE: str = '⬇️ Create a download task:'
    LISTEN_MENU_TITLE: str = '🕵️ Create a monitoring task:'
    UPLOAD_MENU_TITLE: str = '📤 Create an upload task:'
    AUTH_MENU: str = '🔐 Authorized users'
    LISTEN_DOWNLOAD_BTN: str = '🕵️ Monitor and download'
    LISTEN_FORWARD_BTN: str = '📲 Monitor and forward'
    OPEN_LINK_TABLE: str = '📊 Export link table | Off ❌'
    CLOSE_LINK_TABLE: str = '📊 Export link table | On ✅'
    OPEN_COUNT_TABLE: str = '📊 Export count table | Off ❌'
    CLOSE_COUNT_TABLE: str = '📊 Export count table | On ✅'
    OPEN_UPLOAD_TABLE: str = '📊 Export upload table | Off ❌'
    CLOSE_UPLOAD_TABLE: str = '📊 Export upload table | On ✅'
    OPEN_EXIT_SHUTDOWN: str = '⏻ Shut down after exit | Off ❌'
    CLOSE_EXIT_SHUTDOWN: str = '⏻ Shut down after exit | On ✅'
    ALREADY_REMOVE: str = '✅ Removed'
    UPLOAD_SETTING: str = '📤 Upload behavior settings'
    DOWNLOAD_SETTING: str = '📥 Download type settings'
    FORWARD_SETTING: str = '↗️ Forwarding type settings'
    OPEN_UPLOAD_DOWNLOAD: str = 'Upload after download | Off ❌'
    CLOSE_UPLOAD_DOWNLOAD: str = 'Upload after download | On ✅'
    OPEN_UPLOAD_DOWNLOAD_DELETE: str = 'Current | Keep local files 📚'
    CLOSE_UPLOAD_DOWNLOAD_DELETE: str = 'Current | Delete local files 🗑'
    VIDEO_ON: str = '🎬 Video ✅'
    PHOTO_ON: str = '🖼️ Photo ✅'
    AUDIO_ON: str = '🎵 Audio ✅'
    VOICE_ON: str = '🎤 Voice ✅'
    ANIMATION_ON: str = '🎨 GIF ✅'
    DOCUMENT_ON: str = '📄 Document ✅'
    TEXT_ON: str = '💬 Text messages ✅'
    VIDEO_NOTE_ON: str = '📹 Video notes ✅'
    LIVE_PHOTO_ON: str = '📸 Live photos ✅'
    VIDEO_OFF: str = '🎬 Video ❌'
    PHOTO_OFF: str = '🖼️ Photo ❌'
    AUDIO_OFF: str = '🎵 Audio ❌'
    VOICE_OFF: str = '🎤 Voice ❌'
    ANIMATION_OFF: str = '🎨 GIF ❌'
    DOCUMENT_OFF: str = '📄 Document ❌'
    TEXT_OFF: str = '💬 Text messages ❌'
    VIDEO_NOTE_OFF: str = '📹 Video notes ❌'
    LIVE_PHOTO_OFF: str = '📸 Live photos ❌'
    DATE_RANGE_SETTING: str = '📅 Set date range'
    SELECT_START_DATE: str = '⏮️ Select start date'
    SELECT_END_DATE: str = '⏭️ Select end date'
    INPUT_KEYWORD: str = '⌨️ Send me a keyword'
    DOWNLOAD_DTYPE_SETTING: str = '📝 Set download types'
    KEYWORD_FILTER_SETTING: str = '🔑 Set keyword filters'
    CONFIRM_KEYWORD: str = '✅ Confirm keywords'
    INCLUDE_COMMENT: str = '✅ Include comments'
    IGNORE_COMMENT: str = '❌ Exclude comments'
    CMD_DOWNLOAD: str = '⬇️ Download'
    CMD_UPLOAD: str = '📤 Upload'
    CMD_UPLOAD_R: str = '📁 Upload recursively'
    CMD_DOWNLOAD_CHAT: str = '💬 Download channel'
    CMD_FORWARD: str = '↗️ Forward'
