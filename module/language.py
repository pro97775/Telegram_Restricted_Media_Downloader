# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2025-03-01 01:15:00
# File:language.py
translations: dict = {
    'single': ['Single file'],
    'group': ['Grouped files'],
    'comment': ['Comment files'],
    'topic': ['Topic files'],
    'video': ['Video'],
    'photo': ['Photo'],
    'document': ['Document'],
    'audio': ['Audio'],
    'voice': ['Voice'],
    'animation': ['GIF'],
    'video_note': ['Video note'],
    'live_photo': ['Live photo'],
    'media': ['Media'],
    'pending': ['Queued'],
    'downloading': ['Downloading'],
    'uploading': ['Uploading'],
    'success': ['Succeeded'],
    'failure': ['Failed'],
    'sent': ['Sent'],
    'skip': ['Skipped'],
    'retry': ['Retrying'],
    'link': ['[Link]'],
    'link type': ['[Link type]'],
    'size': ['[Size]'],
    'status': ['[Status]'],
    'file': ['[File]'],
    'error size': ['[Incorrect size]'],
    'actual size': ['[Actual size]'],
    'already exist': ['[Already exists]'],
    'channel': ['[Channel]'],
    'message id': ['[Message ID]'],
    'type': ['[Type]'],
    're-download': ['[Re-download]'],
    're-upload': ['[Re-upload]'],
    'retry times': ['[Retry attempts]'],
    'current download task': ['[Active download tasks]'],
    'current upload task': ['[Active upload tasks]'],
    'reason': ['Reason'],
    'resume': ['[Resume]'],
    'download task': ['📥 Download task'],
    'upload task': ['📤 Upload task'],
    'download and upload task': ['📥📤 Download-and-upload task'],
    'forward success': ['Forwarded successfully'],
    'forward failure': ['Forwarding failed'],
    'skip forward': ['Forwarding skipped'],
    'upload file part': ['[Missing upload part]'],
    'IP': ['IP address'],
    'port': ['Port'],
    'username': ['Username'],
    'password': ['Password']
}


def _t(text: str):
    try:
        if text in translations:
            return translations[text][0]
        else:
            return text
    except Exception:  # noqa.
        return text
