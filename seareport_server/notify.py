from __future__ import annotations

import functools
import logging
import shlex
import shutil
import subprocess
import traceback
import typing as T
import warnings

import decorator


logger = logging.getLogger(__name__)


NOTIFIER_CMDS = [
    """ntfy send '{msg}'""",
    """notify-send '{msg}'""",
    """osascript -e 'display notification "{msg}"' """,
]


@functools.lru_cache
def get_notification_program() -> str:
    for cmd in NOTIFIER_CMDS:
        binary = shlex.split(cmd)[0]
        if shutil.which(binary):
            return cmd
    return ""


def notify(msg: str, cmd: str | None = None) -> None:
    if cmd is None:
        cmd = get_notification_program()
    if cmd:
        cmd = cmd.format(msg=msg)
        print(cmd)
        logger.error(cmd)
        subprocess.run(shlex.split(cmd))
    else:
        warnings.warn("Couldn't find any known notification program...")  # holoviews shallows this one too...


# https://github.com/holoviz/holoviews/issues/5424
@decorator.decorator
def notify_exceptions(
    function: T.Callable[..., T.Any],
    *args: list[T.Any],
    **kwargs: dict[str, T.Any],
) -> T.Any:
    try:
        return function(*args, **kwargs)
    except Exception as exc:
        msg = f"{exc}\n{traceback.format_exc()}"
        print(msg)
        notify(msg)
        raise
