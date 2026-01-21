import html


class TerminalCell:
    __slots__ = ("ch", "fg", "bg", "bold")

    def __init__(self, ch=" ", fg=None, bg=None, bold=False):
        self.ch = ch
        self.fg = fg
        self.bg = bg
        self.bold = bold

    def style_key(self):
        return (self.fg, self.bg, self.bold)


class TerminalEmulator:
    def __init__(self, rows=24, cols=80, default_fg="#f0f0f0", default_bg="#2b2b2b"):
        self.rows = rows
        self.cols = cols
        self.default_fg = default_fg
        self.default_bg = default_bg
        self.reset()

    def reset(self):
        self.cursor_row = 0
        self.cursor_col = 0
        self.saved_cursor = (0, 0)
        self.cur_fg = self.default_fg
        self.cur_bg = self.default_bg
        self.cur_bold = False
        self._esc_state = None
        self._csi_buf = ""
        self._screen = [self._blank_line() for _ in range(self.rows)]
        self._alt_screen = None

    def resize(self, rows, cols):
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        if rows == self.rows and cols == self.cols:
            return
        new_screen = [self._blank_line(cols) for _ in range(rows)]
        for r in range(min(self.rows, rows)):
            old_line = self._screen[r]
            new_line = new_screen[r]
            for c in range(min(self.cols, cols)):
                new_line[c] = old_line[c]
        self.rows = rows
        self.cols = cols
        self._screen = new_screen
        self.cursor_row = min(self.cursor_row, self.rows - 1)
        self.cursor_col = min(self.cursor_col, self.cols - 1)

    def feed(self, data):
        for ch in data:
            if self._esc_state == "esc":
                if ch == "[":
                    self._esc_state = "csi"
                    self._csi_buf = ""
                else:
                    self._esc_state = None
                continue

            if self._esc_state == "csi":
                if ch.isalpha() or ch in "@":
                    self._handle_csi(self._csi_buf, ch)
                    self._esc_state = None
                    self._csi_buf = ""
                else:
                    self._csi_buf += ch
                continue

            if ch == "\x1b":
                self._esc_state = "esc"
                continue

            if ch == "\r":
                self.cursor_col = 0
            elif ch == "\n":
                self._newline()
            elif ch == "\b":
                self.cursor_col = max(0, self.cursor_col - 1)
            elif ch == "\t":
                next_tab = (self.cursor_col // 8 + 1) * 8
                self.cursor_col = min(self.cols - 1, next_tab)
            elif ch == "\x07":
                continue
            else:
                self._put_char(ch)

    def render_html(self):
        lines = []
        for line in self._screen:
            out = []
            last_style = None
            for cell in line:
                style = cell.style_key()
                if style != last_style:
                    if last_style is not None:
                        out.append("</span>")
                    if style != (self.default_fg, self.default_bg, False):
                        fg, bg, bold = style
                        style_parts = []
                        if fg:
                            style_parts.append(f"color:{fg}")
                        if bg:
                            style_parts.append(f"background-color:{bg}")
                        if bold:
                            style_parts.append("font-weight:bold")
                        out.append(f"<span style=\"{'; '.join(style_parts)}\">")
                    last_style = style
                out.append(html.escape(cell.ch))
            if last_style is not None:
                out.append("</span>")
            lines.append("".join(out))
        body = "\n".join(lines)
        return (
            "<pre style=\"margin:0; white-space:pre; font-family:Monospace; "
            f"background-color:{self.default_bg}; color:{self.default_fg};\">"
            f"{body}</pre>"
        )

    def _blank_line(self, cols=None):
        cols = self.cols if cols is None else cols
        return [TerminalCell(" ", self.default_fg, self.default_bg, False) for _ in range(cols)]

    def _newline(self):
        if self.cursor_row == self.rows - 1:
            self._screen.pop(0)
            self._screen.append(self._blank_line())
        else:
            self.cursor_row += 1
        self.cursor_col = 0

    def _put_char(self, ch):
        if self.cursor_col >= self.cols:
            self._newline()
        cell = self._screen[self.cursor_row][self.cursor_col]
        cell.ch = ch
        cell.fg = self.cur_fg
        cell.bg = self.cur_bg
        cell.bold = self.cur_bold
        self.cursor_col += 1

    def _handle_csi(self, buf, final):
        if buf.startswith("?"):
            self._handle_private_csi(buf[1:], final)
            return
        params = [p for p in buf.split(";") if p != ""]
        vals = [int(p) if p.isdigit() else 0 for p in params] if params else [0]

        if final in ("H", "f"):
            row = (vals[0] - 1) if len(vals) >= 1 and vals[0] else 0
            col = (vals[1] - 1) if len(vals) >= 2 and vals[1] else 0
            self.cursor_row = max(0, min(self.rows - 1, row))
            self.cursor_col = max(0, min(self.cols - 1, col))
            return

        if final == "A":
            self.cursor_row = max(0, self.cursor_row - (vals[0] or 1))
            return

        if final == "B":
            self.cursor_row = min(self.rows - 1, self.cursor_row + (vals[0] or 1))
            return

        if final == "C":
            self.cursor_col = min(self.cols - 1, self.cursor_col + (vals[0] or 1))
            return

        if final == "D":
            self.cursor_col = max(0, self.cursor_col - (vals[0] or 1))
            return

        if final == "J":
            mode = vals[0] if vals else 0
            if mode in (2, 3):
                self._screen = [self._blank_line() for _ in range(self.rows)]
                self.cursor_row = 0
                self.cursor_col = 0
            elif mode == 0:
                self._clear_from_cursor()
            elif mode == 1:
                self._clear_to_cursor()
            return

        if final == "K":
            mode = vals[0] if vals else 0
            if mode == 0:
                self._clear_line_from_cursor()
            elif mode == 1:
                self._clear_line_to_cursor()
            elif mode == 2:
                self._screen[self.cursor_row] = self._blank_line()
            return

        if final == "m":
            self._handle_sgr(vals)
            return

        if final == "s":
            self.saved_cursor = (self.cursor_row, self.cursor_col)
            return

        if final == "u":
            self.cursor_row, self.cursor_col = self.saved_cursor
            return

    def _clear_from_cursor(self):
        self._clear_line_from_cursor()
        for r in range(self.cursor_row + 1, self.rows):
            self._screen[r] = self._blank_line()

    def _clear_to_cursor(self):
        for r in range(0, self.cursor_row):
            self._screen[r] = self._blank_line()
        self._clear_line_to_cursor()

    def _clear_line_from_cursor(self):
        line = self._screen[self.cursor_row]
        for c in range(self.cursor_col, self.cols):
            line[c] = TerminalCell(" ", self.default_fg, self.default_bg, False)

    def _clear_line_to_cursor(self):
        line = self._screen[self.cursor_row]
        for c in range(0, self.cursor_col + 1):
            line[c] = TerminalCell(" ", self.default_fg, self.default_bg, False)

    def _handle_sgr(self, vals):
        if not vals:
            vals = [0]
        for code in vals:
            if code == 0:
                self.cur_fg = self.default_fg
                self.cur_bg = self.default_bg
                self.cur_bold = False
            elif code == 1:
                self.cur_bold = True
            elif 30 <= code <= 37:
                self.cur_fg = _ansi_color(code - 30, bright=False)
            elif 90 <= code <= 97:
                self.cur_fg = _ansi_color(code - 90, bright=True)
            elif 40 <= code <= 47:
                self.cur_bg = _ansi_color(code - 40, bright=False)
            elif 100 <= code <= 107:
                self.cur_bg = _ansi_color(code - 100, bright=True)

    def _handle_private_csi(self, buf, final):
        params = [p for p in buf.split(";") if p != ""]
        vals = [int(p) if p.isdigit() else 0 for p in params] if params else [0]

        if final not in ("h", "l"):
            return

        if 1049 in vals or 47 in vals or 1047 in vals:
            if final == "h":
                if self._alt_screen is None:
                    self._alt_screen = self._screen
                    self._screen = [self._blank_line() for _ in range(self.rows)]
                    self.saved_cursor = (self.cursor_row, self.cursor_col)
                    self.cursor_row = 0
                    self.cursor_col = 0
            else:
                if self._alt_screen is not None:
                    self._screen = self._alt_screen
                    self._alt_screen = None
                    self.cursor_row, self.cursor_col = self.saved_cursor


def _ansi_color(index, bright=False):
    base = ["#000000", "#aa0000", "#00aa00", "#aa5500", "#0000aa", "#aa00aa", "#00aaaa", "#aaaaaa"]
    bright_base = ["#555555", "#ff5555", "#55ff55", "#ffff55", "#5555ff", "#ff55ff", "#55ffff", "#ffffff"]
    return bright_base[index] if bright else base[index]
