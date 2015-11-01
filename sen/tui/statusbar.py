from concurrent.futures.thread import ThreadPoolExecutor
import logging
import threading
from collections import deque
from functools import partial
import time

import urwid
from sen.tui.constants import STATUS_BAR_REFRESH_SECONDS, CLEAR_NOTIF_BAR_MESSAGE_IN

logger = logging.getLogger(__name__)


class Footer:
    """
    wrapper class for all statusbar/notifbar related methods
    """

    def __init__(self, ui):
        self.ui = ui
        self.notif_bar = None
        self.status_bar = None
        self.prompt_active = False
        self.executor = ThreadPoolExecutor(max_workers=8)
        self.notifications = []
        # lock when managing notifications:
        #  * when accessing self.notifications
        #  * when accessing widgets
        # and most importantly, remember, locking is voodoo
        self.notifications_lock = threading.Lock()

    def reload_notif_bar(self):
        logger.debug("reload notif bar")
        bottom = []
        if self.notif_bar:
            bottom.append(self.notif_bar)
        bottom.append(self.status_bar)
        self.ui.set_footer(urwid.Pile(bottom))
        self.ui.refresh()

    def reload_footer(self):
        logger.debug("reload footer")
        bottom = []
        if self.notif_bar:
            bottom.append(self.notif_bar)
        self.status_bar = self.build_statusbar()
        bottom.append(self.status_bar)
        self.ui.set_footer(urwid.Pile(bottom))
        # do not refresh here b/c mainloop might not started

    def build_statusbar(self):
        """construct and return statusbar widget"""
        left_widgets = self.ui.current_buffer.build_status_bar()
        text_list = []
        for idx, buffer in enumerate(self.ui.buffers):
            #  #1 [I] fedora #2 [L]
            fmt = "#{idx} [{tag}] {name}"
            markup = fmt.format(idx=idx, tag=buffer.tag, name=buffer.display_name)
            text_list.append((
                "status_box_focus" if buffer == self.ui.current_buffer else "status_box",
                markup,
            ))
            text_list.append(" ")
        text_list = text_list[:-1]

        buffer_text = urwid.Text(text_list, align="right")
        columns = urwid.Columns(left_widgets + [buffer_text])
        return urwid.AttrMap(columns, "status")

    def prompt(self, prompt_text):
        """
        prompt for text input.
        """
        oldroot = self.widget
        oldfooter = self.mainframe.get_footer()

        # set up widgets
        leftpart = urwid.Text(prompt_text, align='left')
        editpart = urwid.Edit(multiline=True)

        # build promptwidget
        both = urwid.Columns(
            [
                ('fixed', len(prompt_text), leftpart),
                ('weight', 1, editpart),
            ])
        both = urwid.AttrMap(both, "main_list_dg")

        self.mainframe.set_footer(both)

        self.prompt_active = True

        self.mainframe.set_focus("footer")

        def edited(edit_widget, text_input):
            # FIXME: this function should be somewhere else
            logger.debug("%r %r", edit_widget, text_input)
            if text_input.endswith("\n"):
                # TODO: implement incsearch
                #   - match needs to be highlighted somehow, not with focus though
                self.prompt_active = False
                self.mainframe.set_footer(oldfooter)
                try:
                    self.current_buffer.find_next(text_input[:-1])
                except NotifyError as ex:
                    self.notify(str(ex), level="error")
                    logger.error(repr(ex))
                self.mainframe.set_focus("body")

        urwid.connect_signal(editpart, "change", edited)

    def notify_message(self, message=None, level="info", clear_if_dupl=True,
                        clear_in=CLEAR_NOTIF_BAR_MESSAGE_IN):
        """
        :param level: str, {info, error}

        opens notification popup.
        """
        with self.notifications_lock:
            if clear_if_dupl:
                if message in self.notifications:
                    # notification is already displayed
                    return
            self.notifications.append(message)
        logger.debug("display notification %r", message)
        widget = urwid.AttrMap(urwid.Text(message), "notif_{}".format(level))
        self.notify_widget(widget, message=message, clear_in=clear_in)

    def notify_widget(self, widget, message=None, clear_in=CLEAR_NOTIF_BAR_MESSAGE_IN):
        """
        :param level: str, {info, error}

        opens notification popup.
        """
        def clear_notification():
            time.sleep(clear_in)
            logger.debug("remove widget %r from notif bar", widget)
            with self.notifications_lock:
                if message:
                    self.notifications.remove(message)
                newpile = self.notif_bar.widget_list
                if widget in newpile:
                    newpile.remove(widget)
                if newpile:
                    self.notif_bar = urwid.Pile(newpile)
                else:
                    self.notif_bar = None
            self.reload_notif_bar()

        if not widget:
            return

        logger.debug("display notification widget %s", widget)

        widget_list = [widget]
        with self.notifications_lock:
            # stack errors, don't overwrite them
            if not self.notif_bar:
                self.notif_bar = urwid.Pile(widget_list)
            else:
                newpile = self.notif_bar.widget_list + widget_list
                self.notif_bar = urwid.Pile(newpile)

        self.reload_notif_bar()
        self.executor.submit(clear_notification)
