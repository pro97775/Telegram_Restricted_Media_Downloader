# coding=UTF-8
# Author:Gentlesprite
# Software:PyCharm
# Time:2026-01-23 17:47:00
# File:parser.py
from argparse import (
    SUPPRESS,
    ArgumentParser
)

from module import (
    console,
    VERSION_SEMVER,
    SOFTWARE_SHORT_NAME
)
from module.enums import (
    Banner,
    WebMeta,
    GradientColor
)


class TelegramRestrictedMediaDownloaderArgumentParser(ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument(
            '-h', '--help',
            action='help',
            default=SUPPRESS,
            help='Show this help message'
        )
        self.add_argument(
            '-v', '--version',
            action='version',
            version=f'{SOFTWARE_SHORT_NAME} {VERSION_SEMVER}',
            default=SUPPRESS,
            help='Show version information'
        )
        self.add_argument(
            '-q', '--quiet',
            action='store_true',
            default=False,
            help='Skip the confirmation prompt to reconfigure settings'
        )
        self.add_argument(
            '-c', '--config',
            type=str,
            required=False,
            default='',
            help='Set the user configuration file path'
        )
        self.add_argument(
            '-s', '--session',
            type=str,
            required=False,
            default='',
            help='Set the session file path'
        )
        self.add_argument(
            '-t', '--temp',
            type=str,
            required=False,
            default='',
            help='Set the runtime cache path'
        )
        self.add_argument(
            '-p', '--port',
            type=int,
            nargs='?',
            metavar='PORT',
            const=WebMeta.DEFAULT_PORT,
            default=WebMeta.DEFAULT_PORT,
            help='Set the web dashboard port'
        )
        if '__compiled__' not in globals():
            self.add_argument(
                '--test',
                action='store_true',
                default=False,
                help=SUPPRESS
            )

    def print_help(self, file=None):
        console.print(
            GradientColor.gen_gradient_text(
                text=Banner.TRMD,
                gradient_color=GradientColor.generate_gradient(
                    start_color='#fa709a',
                    end_color='#fee140',
                    steps=10)),
            style='bold',
            highlight=False
        )
        super().print_help(file)


PARSE_ARGS = TelegramRestrictedMediaDownloaderArgumentParser(add_help=False).parse_args()
