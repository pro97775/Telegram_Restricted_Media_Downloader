# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2023-11-13 20:34:13
# File:path_tool.py
import os
import re
import shutil
import struct
import hashlib
import datetime
import mimetypes
import unicodedata

from io import BytesIO
from typing import (
    List,
    Union,
    Optional
)

from pyrogram.file_id import (
    FileType,
    b64_decode,
    rle_decode,
    PHOTO_TYPES,
    WEB_LOCATION_FLAG,
    FILE_REFERENCE_FLAG
)

from module import log
from module.enums import Extension, KeyWord
from module.language import _t

_mimetypes = mimetypes.MimeTypes()


def split_path(path: str) -> dict:
    """Split a path into its directory and filename and return them in a dictionary."""
    directory, file_name = os.path.split(path)
    return {
        'directory': directory,
        'file_name': file_name
    }


def __is_exist(file_path: str) -> bool:
    """Check whether a file path exists."""
    return not os.path.isdir(file_path) and os.path.exists(file_path)


def compare_file_size(a_size: int, b_size: int) -> bool:
    """Check whether two file sizes match."""
    return a_size == b_size


def is_file_duplicate(save_directory: str, sever_file_size: int) -> bool:
    """Check whether the file is a duplicate."""
    return __is_exist(save_directory) and compare_file_size(os.path.getsize(save_directory), sever_file_size)


def validate_title(title: str) -> str:
    """Validate a title and sanitize it if necessary."""
    r_str = r"[/\\:*?\"<>|\n]"  # '/ \ : * ? " < > |'
    new_title = re.sub(r_str, "_", title)
    return new_title


def truncate_filename(path: str, limit: int = 230) -> str:
    # https://github.com/tangyoha/telegram_media_downloader/blob/a3a9c2bed89ea8fd4db0b6616f055dfa11208362/utils/format.py#L195
    """Truncate a filename to the maximum length.
    Parameters
    ----------
    path: str
        File path.

    limit: int
        Maximum filename length in UTF-8 bytes.

    Returns
    -------
    str
        The truncated filename if it exceeds the limit; otherwise, the original filename.
    """
    p, f = os.path.split(os.path.normpath(path))
    f, e = os.path.splitext(f)
    f_max = limit - len(e.encode('utf-8'))
    f = unicodedata.normalize('NFC', f)
    f_trunc = f.encode()[:f_max].decode('utf-8', errors='ignore')
    return os.path.join(p, f_trunc + e)


def gen_backup_config(old_path: str, absolute_backup_dir: str, error_config: bool = False) -> str:
    """Back up the configuration file."""

    try:
        os.makedirs(absolute_backup_dir, exist_ok=True)
    except PermissionError as e:
        log.error(f'Permission denied: could not create directory "{absolute_backup_dir}". {_t(KeyWord.REASON)}: "{e}"')
        raise SystemExit(1)
    except OSError as e:
        log.error(f'Could not create directory "{absolute_backup_dir}". {_t(KeyWord.REASON)}: "{e}"')
        raise SystemExit(1)

    time_format: str = '%Y-%m-%d_%H-%M-%S'
    error_flag: str = 'error_' if error_config else ''
    new_path: str = os.path.join(
        absolute_backup_dir,
        f'{error_flag}history_{datetime.datetime.now().strftime(time_format)}_config.yaml'
    )

    try:
        shutil.move(old_path, new_path)
        return new_path
    except FileNotFoundError as e:
        log.error(f'Source file "{old_path}" does not exist. {_t(KeyWord.REASON)}: "{e}"')
        raise SystemExit(1)
    except PermissionError as e:
        log.error(f'Permission denied: could not move "{old_path}" to "{new_path}". {_t(KeyWord.REASON)}: "{e}"')
        raise SystemExit(1)
    except Exception as e:
        log.error(f'Could not move "{old_path}" to "{new_path}". {_t(KeyWord.REASON)}: "{e}"')
        raise SystemExit(1)


def safe_delete(file_p_d: str) -> bool:
    """Delete a file or directory safely."""
    try:
        if os.path.isdir(file_p_d):
            shutil.rmtree(file_p_d)
            return True
        elif os.path.isfile(file_p_d):
            os.remove(file_p_d)
            return True
        else:
            log.warning(f'"{file_p_d}" is not a valid file or directory and cannot be deleted.')
            return False
    except FileNotFoundError:
        return True
    except PermissionError as e:
        log.error(f'Permission denied: could not delete "{file_p_d}". {_t(KeyWord.REASON)}: "{e}"')
        return False
    except Exception as e:
        log.error(f'Could not delete "{file_p_d}". {_t(KeyWord.REASON)}: "{e}"', exc_info=True)
        return False


def safe_scan_directory_file(
        directory: str
) -> List[str]:
    """List the filenames of files in a directory."""
    with os.scandir(directory) as entries:
        return [entry.name for entry in entries if entry.is_file()]


def safe_replace(origin_file: str, overwrite_file: str) -> dict:
    e_code = None
    if not os.path.isfile(origin_file):
        e_code = f'"{origin_file}" does not exist or is not a file.'
        return {'e_code': e_code}

    try:
        os.replace(origin_file, overwrite_file)
    except OSError as e:
        if 'Invalid cross-device link' in str(e):
            try:
                shutil.move(origin_file, overwrite_file)
            except Exception as e2:
                e_code = f'Could not move file. {_t(KeyWord.REASON)}: "{e2}"'
        else:
            e_code = f'Could not replace file. {_t(KeyWord.REASON)}: "{e}"'

    return {'e_code': e_code}


def move_to_save_directory(temp_file_path: str, save_directory: str) -> dict:
    """Move a file to the specified directory."""
    try:
        os.makedirs(save_directory, exist_ok=True)
        if os.path.isdir(save_directory):
            file_name: str = split_path(temp_file_path).get('file_name')
            if os.path.exists(os.path.join(save_directory, file_name)):
                return {'e_code': f'"{file_name}" already exists in the destination directory and cannot be moved. Resolve the conflict manually.'}
            shutil.move(temp_file_path, save_directory)
            log.info(f'Moved file to the destination directory: [{temp_file_path}] -> [{save_directory}]')
            return {'e_code': None}
        else:
            save_directory: str = os.path.join(os.getcwd(), 'downloads')
            os.makedirs(save_directory, exist_ok=True)
            shutil.move(temp_file_path, save_directory)
            log.info(f'Moved file to the destination directory: [{temp_file_path}] -> [{save_directory}]')
            return {'e_code': f'"{save_directory}" is not a directory. The file was saved to the default directory.'}
    except FileExistsError as e:
        return {'e_code': f'"{save_directory}" already exists and cannot be saved again. {_t(KeyWord.REASON)}: "{e}"'}
    except PermissionError as e:
        return {
            'e_code': f'No permission to access "{save_directory}". The file may be read-only, locked by another process, or not writable by the current user. {_t(KeyWord.REASON)}: "{e}"'}
    except Exception as e:
        return {'e_code': f'Unexpected error. {_t(KeyWord.REASON)}: "{e}"'}


def get_extension(file_id: str, mime_type: str, dot: bool = True) -> str:
    """Get a file's extension.
    For more extensions, see: https://www.iana.org/assignments/media-types/media-types.xhtml
    """

    if not file_id:
        if dot:
            return '.unknown'
        return 'unknown'

    file_type = __get_file_type(file_id)

    guessed_extension = __guess_extension(mime_type)

    if file_type in PHOTO_TYPES:
        extension = Extension.PHOTO.get(mime_type, 'jpg')
    elif file_type == FileType.VOICE:
        extension = guessed_extension or 'ogg'
    elif file_type in (FileType.VIDEO, FileType.ANIMATION, FileType.VIDEO_NOTE):
        extension = guessed_extension or Extension.VIDEO.get(mime_type, 'mp4')
    elif file_type == FileType.DOCUMENT:
        if 'video' in mime_type:
            extension = guessed_extension or Extension.VIDEO.get(mime_type, 'mp4')
        elif 'image' in mime_type:
            extension = guessed_extension or Extension.PHOTO.get(mime_type, 'jpg')  # v1.2.8: fix using the video mapping when resolving image formats.
        else:
            extension = guessed_extension or 'zip'
    elif file_type == FileType.STICKER:
        extension = guessed_extension or 'webp'
    elif file_type == FileType.AUDIO:
        extension = guessed_extension or 'mp3'
    else:
        extension = 'unknown'

    if dot:
        extension = '.' + extension
    return extension


def __guess_extension(mime_type: str) -> Optional[str]:
    """Guess the file extension from the MIME type, if one is available."""
    extension = _mimetypes.guess_extension(mime_type, strict=True)
    return extension[1:] if extension and extension.startswith('.') else extension


def __get_file_type(file_id: str) -> FileType:
    """Get the file type."""
    decoded = rle_decode(b64_decode(file_id))

    # File id versioning. Major versions lower than 4 don't have a minor version
    major = decoded[-1]

    if major < 4:
        buffer = BytesIO(decoded[:-1])
    else:
        buffer = BytesIO(decoded[:-2])

    file_type, _ = struct.unpack('<ii', buffer.read(8))

    file_type &= ~WEB_LOCATION_FLAG
    file_type &= ~FILE_REFERENCE_FLAG

    try:
        file_type = FileType(file_type)
    except ValueError as exc:
        raise ValueError(f'File ID "{file_id}" has unknown file type "{file_type}".') from exc
    return file_type


def get_file_size(file_path: str, temp_ext: str = '.temp') -> int:
    """Get a file's size, also checking for a temporary suffix."""
    if os.path.exists(file_path):
        return os.path.getsize(file_path)
    elif os.path.exists(file_path + temp_ext):
        return os.path.getsize(file_path + temp_ext)
    else:
        return 0


def get_mime_from_extension(file_path: str) -> str:
    ext = file_path.split('.')[-1].lower()
    return Extension.ALL_REVERSE.get(ext, 'application/octet-stream')


def extract_full_extension(filename: Union[str, None]):
    """
    Extract the full file extension, including compound extensions.
    """
    if not filename or not isinstance(filename, str):
        return None

    filename = filename.strip()
    if not filename:
        return None

    multi_ext_patterns = [
        r'\.(7z|rar|zip|r\d+|z\d+|s\d+|t\d+)\.\d+$',  # Split archive formats.
        r'\.(tar|zip|7z|rar)(\.(gz|bz2|xz|zip|7z|rar))+$',  # Compound archive formats.
        r'\.(tar\.(gz|bz2|xz)|[a-z0-9]+\.\d+)$'  # Common compound extensions.
    ]

    for pattern in multi_ext_patterns:
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            full_ext = match.group(0).lstrip('.')
            return full_ext

    # For regular files, return the final extension.
    base_ext = os.path.splitext(filename)[-1]
    if base_ext:
        return base_ext.lstrip('.')

    return None


def is_compressed_file(filename: Union[str, None]) -> bool:
    """
    Check whether a file is an archive.
    """
    if not filename:
        return False

    # Archive filename patterns.
    compressed_patterns = [
        # Single-extension archive formats.
        r'\.(7z|rar|zip|tar|gz|bz2|xz|arj|cab|lzh|lzma|tgz|tbz2|txz|z|Z)$',
        # Compound-extension archive formats.
        r'\.(tar\.(gz|bz2|xz)|7z\.\d+|rar\.\d+|zip\.\d+)$',
        # Legacy split archive formats.
        r'\.(r\d+|z\d+|s\d+|t\d+)$'
    ]

    for pattern in compressed_patterns:
        if re.search(pattern, filename, re.IGNORECASE):
            return True

    return False


def calc_sha256(file_path, chunk_size=8192) -> Union[str, None]:
    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except PermissionError as e:
        log.error(f'Permission denied: could not calculate the file SHA-256. {_t(KeyWord.REASON)}: "{e}"')
    except Exception as e:
        log.exception(f'Could not calculate the file SHA-256. {_t(KeyWord.REASON)}: "{e}"')
