# LoRa Chat App - Version 2.5 (Final Color, Feature & API Parity)
import time, os, uos
import random
import network
import espnow
import machine
from hardware import Pin, I2C, MatrixKeyboard
import M5
from unit import LoRaE220433Unit
from M5 import Lcd, Power, Widgets
import gc

# 尝试导入SD卡相关库
try:
    from hardware import sdcard

    SDCARD_AVAILABLE = True
    print("DEBUG: SD card library imported successfully from hardware.")
except ImportError as e:
    SDCARD_AVAILABLE = False
    print(f"DEBUG: SD card library not available: {e}")

# --- 颜色定义 (RGB565) ---
COLOR_BLACK = 0x3d3939
COLOR_DARKGRAY = 0x2c2c2c
COLOR_MEDGRAY = 0x424242
COLOR_LIGHTGRAY = 0x545454
COLOR_GRAY = 0x808080  # 标准灰色
COLOR_DARKRED = 0x700505
COLOR_ORANGE = 0xc97b0b
COLOR_TEAL = 0x31b90d
COLOR_BLUEGRAY = 0x588aa8
COLOR_BLUE = 0x095fd3
COLOR_PURPLE = 0x930fd3
COLOR_YELLOW = 0xf4e007  # Standard TFT_YELLOW
COLOR_WHITE = 0xfafafa
COLOR_SILVER = 0xc1c4c5  # Standard TFT_SILVER
COLOR_GREEN = 0x07aa17  # Standard TFT_GREEN
COLOR_RED = 0xec0d0d  # Standard TFT_RED

# --- 颜色调色板 ---
BG_COLOR = COLOR_BLACK
UX_COLOR_DARK = COLOR_DARKGRAY
UX_COLOR_MED = COLOR_MEDGRAY
UX_COLOR_LIGHT = COLOR_LIGHTGRAY
UX_COLOR_ACCENT = COLOR_ORANGE
UX_COLOR_ACCENT2 = COLOR_YELLOW

# --- 布局常量 ---
W, H, M = 240, 135, 2
SX, SY, SW, SH = 0, 0, W, 20
TX, TY, TW, TH = 0, SY + SH, 16, H - (SY + SH)
WX, WY, WW, WH = TW, SY + SH, W - TW, H - (SY + SH)

# --- 其他常量 ---
MIN_USERNAME_LENGTH = 2
CONFIG_FILENAME = "/sd/LoRaChat/LoRaChat.conf"
LOG_FILENAME = "/sd/LoRaChat/lorachat_log.txt"
MAX_LOG_FILE_SIZE = 1024 * 100  # 100KB

# --- 图标数据 ---
transparencyColor = 0x0000
wrenchWidth, wrenchHeight = 10, 10
# 扳手图标数据 - 简化定义
wrenchData = [
    0, 0, 0, 0, 0, 1, 1, 1, 0, 0,
    0, 0, 0, 0, 1, 1, 1, 0, 0, 0,
    0, 0, 0, 1, 1, 1, 0, 0, 0, 1,
    0, 0, 0, 1, 1, 1, 0, 0, 1, 1,
    0, 0, 0, 0, 1, 1, 1, 1, 1, 1,
    0, 0, 0, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 0, 1, 1, 0, 0,
    0, 1, 1, 1, 0, 0, 0, 0, 0, 0,
    1, 1, 1, 0, 0, 0, 0, 0, 0, 0,
    1, 1, 0, 0, 0, 0, 0, 0, 0, 0
]
# 将0转换为透明色，1转换为绿色
for i in range(len(wrenchData)):
    wrenchData[i] = transparencyColor if wrenchData[i] == 0 else COLOR_GREEN
userWidth, userHeight = 10, 10
# 用户图标数据 - 简化定义
userData = [
    0, 0, 0, 0, 1, 1, 0, 0, 0, 0,
    0, 0, 0, 1, 1, 1, 1, 0, 0, 0,
    0, 0, 0, 1, 1, 1, 1, 0, 0, 0,
    0, 0, 0, 0, 1, 1, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 1, 1, 1, 1, 0, 0, 0,
    0, 0, 1, 1, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 1, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 1, 1, 1, 1, 1, 0, 0,
    0, 0, 1, 1, 1, 1, 1, 1, 0, 0
]
# 将0转换为透明色，1转换为绿色
for i in range(len(userData)):
    userData[i] = transparencyColor if userData[i] == 0 else COLOR_GREEN

logWidth, logHeight = 10, 10
# 日志图标数据 - 简化定义
logData = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 1, 0, 0, 0, 0, 0, 0, 1, 0,
    0, 1, 0, 0, 0, 0, 0, 0, 1, 0,
    0, 1, 0, 0, 0, 0, 0, 0, 1, 0,
    0, 1, 0, 0, 0, 0, 0, 0, 1, 0,
    0, 1, 1, 1, 1, 1, 1, 1, 1, 0,
    0, 0, 1, 1, 1, 1, 1, 1, 1, 1,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0
]
# 将0转换为透明色，1转换为绿色
for i in range(len(logData)):
    logData[i] = transparencyColor if logData[i] == 0 else COLOR_GREEN


class LoRaChatApp:
    def __init__(self):
        # 初始化硬件和画布引用
        self.kb = None
        self.lora = None
        self.espnow = None
        self.wifi_sta = None
        self.canvas_system_bar = None
        self.canvas_tab_bar = None
        self.canvas_main_window = None

        # 初始化交互状态
        self.active_tab_index = 0
        self.redraw_flags = 0b111
        self.last_update_time = time.ticks_ms()
        self.last_rx_time = time.ticks_ms()
        self.last_tx_time = time.ticks_ms()
        self.last_ping_time = time.ticks_ms()
        self.username = "u" + str(random.randint(100, 999))
        self.brightness = 70
        self.ping_mode = True
        self.repeat_mode = False
        self.espnow_mode = False
        self.active_setting_index = 0  # 与旧版本一致，使用active_setting_index
        self.chat_tabs = [{'messages': [], 'buffer': ""} for _ in range(3)]
        self.presences = []
        self.max_rssi = -1000
        self.battery_pct = 100
        self.nonce = 0  # 用于消息协议的Nonce

        # 日志系统状态
        self.sd_log_enabled = True
        self.sdcard_mounted = False
        self.log_page_index = 0
        self.log_total_pages = 1
        self.log_page_cache = []  # 用于缓存当前页的日志
        self.log_tab_active = False  # 标记日志标签页是否被激活

        # 设置保存状态
        self.sd_write_stage = 0  # 0: idle, 1: saving, 2: ok, 3: error
        self.sd_write_status_reset_time = 0

        # 初始化日志系统
        self.log_messages = []
        self.max_log_messages = 20  # 最大日志消息数

    def _draw_icon(self, canvas, x, y, width, height, data):
        for row in range(height):
            for col in range(width):
                idx = row * width + col
                color = data[idx]
                if color != transparencyColor:
                    canvas.drawPixel(x - width // 2 + col, y - height // 2 + row, color)

    def _draw_tx_indicator(self, x, y):
        txw, txa = 10, 3
        txx = x - txw // 2
        Lcd.drawLine(txx, y, txx + txw, y, COLOR_SILVER)
        Lcd.drawLine(txx, y, txx + txa, y - txa + 1, COLOR_SILVER)
        Lcd.drawLine(txx, y, txx + txa, y + txa - 1, COLOR_SILVER)

    def _draw_rx_indicator(self, x, y):
        rxw, rxa = 10, 3
        rxx = x - rxw // 2
        Lcd.drawLine(rxx, y, rxx + rxw, y, COLOR_SILVER)
        Lcd.drawLine(rxx + rxw, y, rxx + rxw - rxa, y - rxa + 1, COLOR_SILVER)
        Lcd.drawLine(rxx + rxw, y, rxx + rxw - rxa, y + rxa - 1, COLOR_SILVER)

    def _draw_rssi_indicator(self, x, y, rssi, altColor=False):
        bars = [(2, -90), (5, -80), (8, -70), (11, -60)]  # Adjusted for Wi-Fi RSSI
        if not self.espnow_mode:  # LoRa RSSI is much lower
            bars = [(2, -130), (5, -105), (8, -80), (11, -55)]
        barW, barSpace = 3, 2
        maxY = max(b[0] for b in bars)
        barY = y - maxY // 2
        Lcd.drawLine(x, barY, x, barY + maxY - 1, COLOR_SILVER)
        Lcd.drawTriangle(x - 3, barY, x + 3, barY, x, barY + 3, COLOR_SILVER)
        barX = x + 4
        color = UX_COLOR_ACCENT if altColor else UX_COLOR_ACCENT2
        for h, threshold in bars:
            if rssi > threshold:
                Lcd.fillRect(barX, barY + (maxY - h), barW, h, color)
            else:
                Lcd.drawRect(barX, barY + (maxY - h), barW, h, COLOR_SILVER)
            barX += barW + barSpace

    def _draw_battery_indicator(self, x, y, batteryPct):
        battw, batth = 24, 11
        ya = y - batth // 2
        chgw = (battw - 2) * batteryPct // 100

        # 修正：与C++版本保持一致，满电时显示青色，否则显示从红到绿的渐变
        if batteryPct >= 100:
            batColor = COLOR_TEAL
        else:
            r_8bit = int(((100 - batteryPct) / 100.0) * 255)
            g_8bit = int((batteryPct / 100.0) * 255)
            b_8bit = 0
            r_5bit = (r_8bit & 0b11111000) >> 3
            g_6bit = (g_8bit & 0b11111100) >> 2
            b_5bit = (b_8bit & 0b11111000) >> 3
            batColor = (r_5bit << 11) | (g_6bit << 5) | b_5bit

        Lcd.fillRoundRect(x, ya, battw, batth, 2, COLOR_SILVER)
        Lcd.fillRect(x - 2, y - 2, 2, 4, COLOR_SILVER)
        Lcd.fillRect(x + 1, ya + 1, battw - 2, batth - 2, COLOR_DARKGRAY)
        if chgw > 0:
            Lcd.fillRect(x + 1 + (battw - 2 - chgw), ya + 1, chgw, batth - 2, batColor)

    def draw_system_bar(self):
        # 完整的系统栏绘制，直接使用Lcd
        Lcd.fillRect(SX, SY, SW, SH, UX_COLOR_DARK)
        Lcd.setTextColor(COLOR_SILVER, UX_COLOR_DARK)
        Lcd.setFont(Widgets.FONTS.DejaVu12)
        y_pos = SY + (SH - 12) // 2

        # 绘制用户名
        Lcd.drawString(self.username, SX + 3 * M, y_pos)

        # 绘制标题
        title = "EspNowChat" if self.espnow_mode else "LoRaChat"
        title_width = Lcd.textWidth(title)
        Lcd.drawString(title, SX + (SW - title_width) // 2, y_pos)

        # 绘制信号强度指示器
        self._draw_rssi_indicator(SW - 70, SY + SH // 2, self.max_rssi)

        # 绘制电池指示器
        self._draw_battery_indicator(SW - 30, SY + SH // 2, self.battery_pct)

    def draw_tab_bar(self):
        # 简化的标签栏绘制，直接使用Lcd
        Lcd.fillRect(TX, TY, TW, TH, BG_COLOR)
        for i in range(6):
            tabh = (TH + 3 * M) // 6
            tabm = 5
            color = UX_COLOR_ACCENT if i == self.active_tab_index else UX_COLOR_DARK
            taby = TY + tabm + i * tabh - i * M

            # 绘制三角形和矩形
            Lcd.fillTriangle(TX + M, taby, TX + TW, taby, TX + TW, taby - tabm, color)
            Lcd.fillRect(TX + M, taby, TW - M, tabh - 2 * tabm, color)
            Lcd.fillTriangle(TX + M, taby + tabh - 2 * tabm, TX + TW, taby + tabh - 2 * tabm, TX + TW,
                             taby + tabh - tabm, color)

            # 绘制标签内容
            Lcd.setTextColor(COLOR_SILVER, color)
            Lcd.setFont(Widgets.FONTS.DejaVu9)
            center_x = TX + M + (TW - M) // 2
            center_y = taby + (tabh - 2 * tabm) // 2 - 4

            if 0 <= i <= 2:
                label = chr(ord('A') + i)
                label_width = Lcd.textWidth(label)
                Lcd.drawString(label, center_x - label_width // 2, center_y)
            elif i == 3:
                # 绘制用户图标
                for row in range(userHeight):
                    for col in range(userWidth):
                        idx = row * userWidth + col
                        color_pixel = userData[idx]
                        if color_pixel != transparencyColor:
                            Lcd.drawPixel(center_x - userWidth // 2 + col, center_y + 4 - userHeight // 2 + row,
                                          color_pixel)
            elif i == 4:
                # 绘制扳手图标
                for row in range(wrenchHeight):
                    for col in range(wrenchWidth):
                        idx = row * wrenchWidth + col
                        color_pixel = wrenchData[idx]
                        if color_pixel != transparencyColor:
                            Lcd.drawPixel(center_x - wrenchWidth // 2 + col, center_y + 4 - wrenchHeight // 2 + row,
                                          color_pixel)
            elif i == 5:
                # 绘制日志图标
                for row in range(logHeight):
                    for col in range(logWidth):
                        idx = row * logWidth + col
                        color_pixel = logData[idx]
                        if color_pixel != transparencyColor:
                            Lcd.drawPixel(center_x - logWidth // 2 + col, center_y + 4 - logHeight // 2 + row,
                                          color_pixel)

    def _draw_tab(self, index):
        self.canvas_tab_bar.setFont(Widgets.FONTS.DejaVu9)
        font_h = 9
        tabh = (TH + 3 * M) // 6  # 6个标签页的高度
        tabm = 5
        color = UX_COLOR_ACCENT if index == self.active_tab_index else UX_COLOR_DARK
        taby = tabm + index * tabh - index * M
        self.canvas_tab_bar.fillTriangle(M, taby, TW, taby, TW, taby - tabm, color)
        self.canvas_tab_bar.fillRect(M, taby, TW, tabh - 2 * tabm, color)
        self.canvas_tab_bar.fillTriangle(M, taby + tabh - 2 * tabm, TW, taby + tabh - 2 * tabm, TW, taby + tabh - tabm,
                                         color)
        self.canvas_tab_bar.setTextColor(COLOR_SILVER, color)
        center_x = M + (TW - M) // 2
        center_y = taby + (tabh - 2 * tabm) // 2 - font_h // 2
        if 0 <= index <= 2:
            label = chr(ord('A') + index)
            label_width = self.canvas_tab_bar.textWidth(label)
            self.canvas_tab_bar.drawString(label, center_x - label_width // 2, center_y)
        elif index == 3:
            self._draw_icon(self.canvas_tab_bar, center_x, center_y + 4, userWidth, userHeight, userData)
        elif index == 4:
            self._draw_icon(self.canvas_tab_bar, center_x, center_y + 4, wrenchWidth, wrenchHeight, wrenchData)
        elif index == 5:
            self._draw_icon(self.canvas_tab_bar, center_x, center_y + 4, logWidth, logHeight, logData)

    def _get_wrapped_lines(self, text, max_width_pixels):
        """
        实现基于单词的文本换行，返回一个行列表。
        """
        lines = []
        current_line = ""
        words = text.split(' ')

        if not words:
            return []

        Lcd.setFont(Widgets.FONTS.DejaVu9)  # 确保使用正确的字体计算宽度

        for word in words:
            # 如果单词本身就超长，则强制截断
            while Lcd.textWidth(word) > max_width_pixels:
                # 找到能容纳的最大部分
                for i in range(len(word), 0, -1):
                    if Lcd.textWidth(word[:i]) <= max_width_pixels:
                        lines.append(word[:i])
                        word = word[i:]
                        break

            if Lcd.textWidth(current_line + " " + word) <= max_width_pixels:
                current_line += (" " if current_line else "") + word
            else:
                lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        return lines

    def draw_main_window(self):
        # 直接使用Lcd绘制主窗口
        Lcd.fillRect(WX, WY, WW, WH, COLOR_BLACK)

        if 0 <= self.active_tab_index <= 2:
            self.draw_chat_window()
        elif self.active_tab_index == 3:
            self.draw_user_presence_window()
        elif self.active_tab_index == 4:
            self.draw_settings_window()
        elif self.active_tab_index == 5:
            self.draw_log_window()

    def draw_chat_window(self):
        # 直接使用Lcd绘制聊天窗口
        Lcd.setFont(Widgets.FONTS.DejaVu9)
        font_h = 9
        row_count = (WH - 3 * M) // (font_h + M) - 1
        buffer_h = WH - ((font_h + M) * row_count) - M
        buffer_y = WY + WH - buffer_h + 2 * M

        # 步骤 1: 先绘制历史消息
        messages = self.chat_tabs[self.active_tab_index]['messages']
        lines_drawn = 0
        for msg in reversed(messages):
            if lines_drawn >= row_count:
                break

            is_own = msg['username'] == ""
            text = msg['text'] if is_own else msg['username'] + ": " + msg['text']
            lines = self._get_wrapped_lines(text, WW - 4 * M)

            for line in reversed(lines):
                if lines_drawn >= row_count:
                    break
                cursor_y = WY + 2 * M + (row_count - lines_drawn - 1) * (font_h + M)
                if is_own:
                    # 修复：确保自己的消息是白色前景，并用主背景色填充背景
                    Lcd.setTextColor(COLOR_WHITE, BG_COLOR)
                    text_width = Lcd.textWidth(line)
                    Lcd.drawString(line, WX + WW - 2 * M - text_width, cursor_y)
                else:
                    # 仅在第一行高亮显示用户名
                    is_first_line_of_msg = (line == lines[0])
                    username_part = msg['username'] + ":"
                    if is_first_line_of_msg and line.startswith(username_part):
                        username_width = Lcd.textWidth(username_part)
                        Lcd.setTextColor(COLOR_YELLOW, COLOR_BLACK)
                        Lcd.drawString(username_part, WX + 2 * M, cursor_y)
                        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
                        Lcd.drawString(line[len(username_part):], WX + 2 * M + username_width, cursor_y)
                    else:
                        # 确保后续行也是白色前景，黑色背景，以保持视觉一致性
                        Lcd.setTextColor(COLOR_WHITE, BG_COLOR)
                        Lcd.drawString(line, WX + 2 * M + Lcd.textWidth("  "), cursor_y)  # 后续行缩进
                lines_drawn += 1

        # 步骤 2: 然后绘制输入框和输入文字
        Lcd.drawLine(WX + 10, buffer_y, WX + WW - 10, buffer_y, COLOR_GRAY)
        buffer_text = self.chat_tabs[self.active_tab_index]['buffer']
        display_buffer = buffer_text.replace(' ', ' ')
        if display_buffer:
            # 明确设置输入文字的颜色和背景
            Lcd.setTextColor(COLOR_WHITE, BG_COLOR)
            text_width = Lcd.textWidth(display_buffer)
            Lcd.drawString(display_buffer, WX + WW - 2 * M - text_width, buffer_y + (buffer_h - font_h) // 2)

    def draw_user_presence_window(self):
        # 直接使用Lcd绘制用户在线窗口，确保无背景色和一致的字体

        # 先清除整个窗口背景
        Lcd.fillRect(WX, WY, WW, WH, COLOR_BLACK)

        # 设置统一字体
        Lcd.setFont(Widgets.FONTS.DejaVu9)

        # 绘制标题 - 居中显示
        title = "Users Seen"
        title_width = Lcd.textWidth(title)
        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
        Lcd.drawString(title, WX + (WW - title_width) // 2, WY + 10)
        Lcd.drawLine(WX, WY + 25, WX + WW, WY + 25, COLOR_GRAY)

        # 绘制用户列表
        y_pos = WY + 35
        for p in self.presences:
            last_seen_sec = time.ticks_diff(time.ticks_ms(), p['last_seen']) // 1000
            text = "{0} RSSI: {1}, seen: {2}s".format(p['username'], p['rssi'], last_seen_sec)
            Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
            Lcd.drawString(text, WX + 10, y_pos)
            y_pos += 15

        # 如果没有用户在线，显示提示
        if not self.presences:
            no_users_text = "No users seen yet"
            no_users_width = Lcd.textWidth(no_users_text)
            Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
            Lcd.drawString(no_users_text, WX + (WW - no_users_width) // 2, WY + 50)

        # 重置文本颜色和字体为默认值
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)

    def draw_settings_window(self):
        # 直接使用Lcd绘制设置窗口，确保无背景色和一致的字体

        # 先清除整个窗口背景
        Lcd.fillRect(WX, WY, WW, WH, COLOR_BLACK)

        # 设置统一字体
        Lcd.setFont(Widgets.FONTS.DejaVu9)

        # 绘制标题 - 居中显示，并确保文本背景与窗口背景一致
        title = "Settings"
        title_width = Lcd.textWidth(title)
        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
        Lcd.drawString(title, WX + (WW - title_width) // 2, WY + 10)
        Lcd.drawLine(WX, WY + 25, WX + WW, WY + 25, COLOR_GRAY)

        # 检查并重置保存状态
        if self.sd_write_stage in [2, 3] and time.ticks_diff(time.ticks_ms(), self.sd_write_status_reset_time) > 0:
            self.sd_write_stage = 0

        # 根据保存状态决定显示文本
        save_status_text = "Press Enter"
        save_status_color = None
        if self.sd_write_stage == 1:  # Saving (虽然很快，但可以预留)
            save_status_text = "Saving..."
            save_status_color = COLOR_YELLOW
        elif self.sd_write_stage == 2:  # OK
            save_status_text = "OK!"
            save_status_color = COLOR_GREEN
        elif self.sd_write_stage == 3:  # Error
            save_status_text = "Error!"
            save_status_color = COLOR_RED

        # 绘制设置项，采用与旧版本相同的布局
        settings_map = [
            ("Username", self.username),
            ("Brightness", f"{self.brightness}%"),
            ("Ping Mode", "On" if self.ping_mode else "Off"),
            ("Repeat Mode", "On" if self.repeat_mode else "Off"),
            ("ESP-NOW Mode", "On" if self.espnow_mode else "Off"),
            ("Save to Conf", save_status_text)
        ]

        # 实现滚动功能
        visible_settings = 4  # 一次显示的设置项数量
        if len(settings_map) > visible_settings:
            # 计算滚动位置
            scroll_index = max(0, self.active_setting_index - visible_settings // 2)
            scroll_index = min(scroll_index, len(settings_map) - visible_settings)

            # 绘制滚动条
            scrollbar_width = 4
            scrollbar_height = (WH - 30) * visible_settings // len(settings_map)
            scrollbar_y = WY + 30 + (WH - 30 - scrollbar_height) * scroll_index // (
                        len(settings_map) - visible_settings)
            Lcd.fillRect(WX + WW - scrollbar_width - 2, WY + 30, scrollbar_width, WH - 30, COLOR_DARKGRAY)
            Lcd.fillRect(WX + WW - scrollbar_width - 2, scrollbar_y, scrollbar_width, scrollbar_height, UX_COLOR_ACCENT)

            # 只绘制可见的设置项
            start_idx = scroll_index
            end_idx = scroll_index + visible_settings
        else:
            start_idx = 0
            end_idx = len(settings_map)

        y_pos = WY + 35
        x_offset = 15

        for i in range(start_idx, end_idx):
            name, value = settings_map[i]
            base_color = COLOR_YELLOW if i == self.active_setting_index else COLOR_WHITE

            # 绘制设置名称
            name_text = name + ':'
            name_width = Lcd.textWidth(name_text)
            Lcd.setTextColor(base_color, COLOR_BLACK)
            Lcd.drawString(name_text, WX + WW // 2 - 8 - name_width + x_offset, y_pos)

            # 根据设置类型设置不同的文本颜色
            status_color = None
            if i == 0:
                status_color = base_color
            elif i == 2:
                status_color = COLOR_GREEN if self.ping_mode else COLOR_RED
            elif i == 3:
                status_color = COLOR_GREEN if self.repeat_mode else COLOR_RED
            elif i == 4:
                status_color = COLOR_GREEN if self.espnow_mode else COLOR_RED
            elif i == 5:
                status_color = save_status_color

            # 绘制设置值
            Lcd.setTextColor(status_color if status_color is not None else base_color, COLOR_BLACK)
            Lcd.drawString(str(value), WX + WW // 2 + x_offset, y_pos)

            y_pos += 20  # 适当增加行间距以提高可读性

        # 重置文本颜色和字体为默认值
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)

    def draw_log_window(self):
        Lcd.fillRect(WX, WY, WW, WH, COLOR_BLACK)
        Lcd.setFont(Widgets.FONTS.DejaVu9)
        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)

        title = "SD Card Log"
        title_width = Lcd.textWidth(title)
        Lcd.drawString(title, WX + (WW - title_width) // 2, WY + 10)
        Lcd.drawLine(WX, WY + 25, WX + WW, WY + 25, COLOR_GRAY)

        if not self.sdcard_mounted:
            Lcd.drawString("SD Card not mounted.", WX + 10, WY + 40)
            return

        # 首次进入或需要刷新时加载日志
        if self.log_tab_active:
            self.load_log_page_from_sd(self.log_page_index)
            self.log_tab_active = False  # 重置标志，避免重复加载

        if not self.log_page_cache:
            Lcd.drawString("No log entries found.", WX + 10, WY + 40)
        else:
            y_pos = WY + 35
            line_height = 12
            lines_drawn = 0
            max_lines = (WH - 50) // line_height
            for log_entry in self.log_page_cache:
                if lines_drawn >= max_lines: break
                wrapped_lines = self._get_wrapped_lines(log_entry, WW - 20)
                for line in wrapped_lines:
                    if lines_drawn >= max_lines: break
                    # 简单的颜色处理
                    if "[ERROR]" in line:
                        Lcd.setTextColor(COLOR_RED, COLOR_BLACK)
                    elif "[WARN]" in line:
                        Lcd.setTextColor(COLOR_YELLOW, COLOR_BLACK)
                    else:
                        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
                    Lcd.drawString(line, WX + 10, y_pos)
                    y_pos += line_height
                    lines_drawn += 1

        # 绘制页码和操作提示
        Lcd.setTextColor(COLOR_SILVER, COLOR_BLACK)
        page_info = f"Page {self.log_page_index + 1}/{self.log_total_pages}"
        Lcd.drawString(page_info, WX + WW - Lcd.textWidth(page_info) - M, WY + WH - 15)
        Lcd.drawString(",:Prev  /:Next  ␣:Refresh", WX + M, WY + WH - 15)

    def handle_input(self, key):
        print(f"DEBUG: Key received: {repr(key)}")

        if self.active_tab_index == 5:  # 日志窗口
            if key == ',':  # 上一页
                if self.log_page_index > 0:
                    self.log_page_index -= 1
                    self.load_log_page_from_sd(self.log_page_index)
                    self.redraw_flags |= 0b100
            elif key == '/':  # 下一页
                if self.log_page_index < self.log_total_pages - 1:
                    self.log_page_index += 1
                    self.load_log_page_from_sd(self.log_page_index)
                    self.redraw_flags |= 0b100
            elif key == ' ':  # 刷新到最新页
                self.load_log_page_from_sd()  # 不带参数加载最新页
                self.redraw_flags |= 0b100

        elif self.active_tab_index == 4:  # 设置窗口
            settings_count = 6

            if key == ';':
                self.active_setting_index = (self.active_setting_index - 1 + settings_count) % settings_count
                self.redraw_flags |= 0b100
            elif key == '.':
                self.active_setting_index = (self.active_setting_index + 1) % settings_count
                self.redraw_flags |= 0b100
            else:
                setting_to_edit = self.active_setting_index
                if setting_to_edit == 0:
                    if key == '\x08':
                        self.username = self.username[:-1]
                    elif len(key) == 1 and len(self.username) < 8:
                        self.username += key
                elif setting_to_edit == 1:
                    if key == ',':
                        self.brightness = max(0, self.brightness - 10)
                    elif key == '/':
                        self.brightness = min(100, self.brightness + 10)
                    Lcd.setBrightness(self.brightness)
                elif setting_to_edit == 2 and key == '\r':
                    self.ping_mode = not self.ping_mode
                elif setting_to_edit == 3 and key == '\r':
                    self.repeat_mode = not self.repeat_mode
                elif setting_to_edit == 4 and key == '\r':
                    self.toggle_espnow_mode()
                elif setting_to_edit == 5 and key == '\r':
                    self.sd_write_stage = 1  # 标记为正在保存
                    if self.save_settings():
                        self.sd_write_stage = 2  # 成功
                    else:
                        self.sd_write_stage = 3  # 失败
                    self.sd_write_status_reset_time = time.ticks_add(time.ticks_ms(), 2000)  # 2秒后重置

                self.redraw_flags |= 0b101

        elif 0 <= self.active_tab_index <= 2:  # 聊天窗口
            buffer = self.chat_tabs[self.active_tab_index]['buffer']
            if key == '\r':
                self.send_message(self.active_tab_index, buffer)
                self.chat_tabs[self.active_tab_index]['buffer'] = ""
            elif key == '\x08':
                self.chat_tabs[self.active_tab_index]['buffer'] = buffer[:-1]
            else:
                self.chat_tabs[self.active_tab_index]['buffer'] += key
            self.redraw_flags |= 0b100

    def send_message(self, channel, text):
        if text is None:
            return
        # 修正：即使是空消息 (Ping)，也应该被记录下来，以保持逻辑一致性并避免崩溃。
        # C++ 版本虽然不显示 Ping，但它在逻辑上处理了空消息的发送。
        msg = {'username': "", 'text': text, 'is_espnow': self.espnow_mode}
        # 只有在当前活跃的标签页是消息发送的频道时，才将自己的消息加入显示列表
        if self.active_tab_index == channel:
            self.chat_tabs[channel]['messages'].append(msg)

        # 构建二进制消息帧
        self.nonce = (self.nonce + 1) & 0x3F  # Nonce自增并保持在6位范围内
        header = (channel << 6) | self.nonce
        payload = bytes([header]) + self.username.encode('utf-8') + b'\x00' + text.encode('utf-8')

        if self.espnow_mode and self.espnow:
            self.espnow.send(b'\xff' * 6, payload)
        elif self.lora:
            self.lora.send(0xFFFF, 0, payload)  # LoRa频道使用默认的0
        self.last_tx_time = time.ticks_ms()
        self.redraw_flags |= 0b100

    def handle_received_message(self, sender, message, rssi):
        # 打印所有接收到的原始报文，包括噪声
        self.log_message("RAW", f"Packet: {message}, RSSI: {rssi}")

        try:
            # 步骤 1: 解析二进制消息帧
            if len(message) < 2:
                self.log_message("DEBUG", f"Packet too short: {message}")
                return

            header = message[0]
            channel = header >> 6
            # nonce = header & 0x3F # Nonce暂时不用

            # 修复：允许频道3（Ping消息），但只处理0-3的频道
            if not (0 <= channel <= 3):
                self.log_message("DEBUG", f"Invalid channel {channel} in packet, dropping.")
                return

            payload = message[1:]
            null_pos = payload.find(b'\x00')

            if null_pos == -1:
                self.log_message("DEBUG", "Invalid frame, no null terminator")
                return

            # 将解码操作单独放在try-except块中，以更精确地捕获噪声
            username = payload[:null_pos].decode('utf-8')
            text = payload[null_pos + 1:].decode('utf-8')

        except UnicodeError:
            # 如果只是解码失败，很可能是噪声
            self.log_message("DEBUG", f"Noise or non-UTF8 packet ignored: {message}")
            return
        except IndexError as e:
            # 如果是其他结构性问题（如切片越界），则记录为解析错误
            self.log_message("DEBUG", f"Frame parse error: {e} on data: {message}")
            return

        try:
            self.last_rx_time = time.ticks_ms()
            self.max_rssi = rssi if rssi > self.max_rssi else self.max_rssi

            # 如果是Ping消息（频道3或文本为空），则只更新在线状态后返回
            # 同时，如果处于中继模式，则不忽略空文本消息
            is_ping = (channel == 3) or (not text and not self.repeat_mode)
            if is_ping:
                if channel == 3:
                    self.log_message("DEBUG", f"Ping received from {username}")
                # 但仍然更新用户在线状态
                self.update_presence(username, rssi)
                return

            # 将消息添加到对应的频道
            msg = {'username': username, 'text': text, 'rssi': rssi, 'is_espnow': self.espnow_mode}
            self.chat_tabs[channel]['messages'].append(msg)

            # 如果当前正显示该频道，则触发重绘
            if self.active_tab_index == channel:
                self.redraw_flags |= 0b100

            # 中继模式处理
            if self.repeat_mode:
                response = "rp:{}|{}|{}".format(username, text, rssi)
                self.send_message(0, response)  # 中继消息默认发到A频道

            # 更新用户在线状态
            self.update_presence(username, rssi)

            # 将解码后的消息添加到日志中
            self.log_message("INFO", f"CH{chr(ord('A') + channel)}| {username}: {text}")

        except Exception as e:
            self.log_message("ERROR", f"Msg processing error: {e} on data: {message}")

    def update_presence(self, username, rssi):
        """更新用户在线状态列表"""
        found = False
        for p in self.presences:
            if p['username'] == username:
                p['rssi'] = rssi
                p['last_seen'] = time.ticks_ms()
                found = True
                break
        if not found:
            self.presences.append({'username': username, 'rssi': rssi, 'last_seen': time.ticks_ms()})

    def log_message(self, level, message):
        """中心化的日志记录函数"""
        timestamp = time.localtime()
        time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
        log_entry = f"[{time_str}][{level}] {message}"

        # 打印到串口
        print(log_entry)

        # 添加到内存日志 (用于旧的日志窗口，可逐步废弃)
        self.log_messages.append(log_entry)
        if len(self.log_messages) > self.max_log_messages:
            self.log_messages.pop(0)

        # 写入SD卡
        self.log_to_sd(log_entry)

    def log_to_sd(self, log_entry):
        """将单条日志追加到SD卡文件"""
        if not self.sdcard_mounted or not self.sd_log_enabled:
            return
        try:
            # 检查文件大小，如果超过限制则清空
            try:
                stat = uos.stat(LOG_FILENAME)
                if stat[6] > MAX_LOG_FILE_SIZE:
                    with open(LOG_FILENAME, 'w') as f:
                        f.write(f"--- Log Cleared (size > {MAX_LOG_FILE_SIZE // 1024}KB) ---\n")
            except OSError:
                # 文件不存在，忽略
                pass

            with open(LOG_FILENAME, 'a') as f:
                f.write(log_entry + '\n')
        except Exception as e:
            print(f"ERROR: Failed to write to SD log: {e}")

    def load_log_page_from_sd(self, page_index=-1):
        """从SD卡加载指定页的日志"""
        if not self.sdcard_mounted:
            self.log_page_cache = []
            return

        line_height = 12
        visible_lines = (WH - 50) // line_height
        self.log_page_cache = []

        try:
            # 健壮性改进：先检查文件是否存在
            uos.stat(LOG_FILENAME)
        except OSError:
            # 文件不存在，设置提示信息并返回
            self.log_page_cache = ["Log file not found."]
            self.log_total_pages = 1
            self.log_page_index = 0
            return

        try:
            # 内存优化：逐行读取文件以计算总行数，避免一次性加载整个文件
            total_lines = 0
            with open(LOG_FILENAME, 'rb') as f:  # 以二进制模式读取
                for _ in f:
                    total_lines += 1

            self.log_total_pages = (total_lines + visible_lines - 1) // visible_lines if total_lines > 0 else 1

            if page_index == -1:  # 加载最后一页
                self.log_page_index = self.log_total_pages - 1
            else:
                self.log_page_index = min(page_index, self.log_total_pages - 1)

            start_line = self.log_page_index * visible_lines

            # 再次打开文件，并逐行读取以获取目标页的内容
            with open(LOG_FILENAME, 'rb') as f:  # 以二进制模式读取
                current_line_num = 0
                for byte_line in f:
                    if current_line_num >= start_line:
                        if len(self.log_page_cache) < visible_lines:
                            try:
                                # 手动解码，并忽略无法解码的行
                                self.log_page_cache.append(byte_line.strip().decode('utf-8'))
                            except UnicodeError:
                                self.log_page_cache.append("[... unreadable log entry ...]")
                        else:
                            break  # 当前页已满
                    current_line_num += 1

        except Exception as e:
            # 使用 sys.print_exception 来获取更详细的错误信息，这在内存不足时更可靠
            import sys
            print("ERROR: Failed to load log page. Exception details:")
            sys.print_exception(e)  # 这会将完整的错误堆栈跟踪打印到 Web-REPL
            # 在屏幕上显示具体的异常类型
            self.log_page_cache = [f"Error loading log:", f"{type(e).__name__}"]

    def lora_cb(self, data, rssi):
        if data:
            self.log_message("LORA", f"RSSI: {rssi}")
            self.handle_received_message(None, data, rssi)

    def espnow_cb(self, mac, msg):
        if msg:
            try:
                rssi = self.wifi_sta.status('rssi')
                self.log_message("ESP", f"From: {mac.hex()}, RSSI: {rssi}")
                self.handle_received_message(mac, msg, rssi)
            except Exception as e:
                print(f"ESPNow decode error: {e}")

    def kb_event_cb(self, event):
        key = self.kb.get_string()
        if not key:
            return

        self.redraw_flags = 0
        if key == '\t':
            self.active_tab_index = (self.active_tab_index + 1) % 6  # 6个标签页

            # 当切换到日志标签页时，设置一个标志来触发日志加载
            if self.active_tab_index == 5:
                self.log_tab_active = True

            self.redraw_flags |= 0b110
            return
        self.handle_input(key)

    def save_screenshot(self):
        if not self.sdcard_mounted:
            self.log_message("ERROR", "Screenshot failed: SD not mounted.")
            return

        try:
            # 寻找一个不重复的文件名
            i = 0
            while True:
                filename = f"/sd/LoRaChat/screenshots/screenshot.{i}.bmp"
                try:
                    uos.stat(filename)
                    i += 1
                except OSError:
                    # 文件不存在，这个文件名可用
                    break

            width = Lcd.width()
            height = Lcd.height()

            # BMP文件大小计算
            row_size = (width * 3 + 3) & ~3  # 每行字节数必须是4的倍数
            image_size = row_size * height
            file_size = 54 + image_size

            with open(filename, 'wb') as f:
                # 写入BMP文件头 (54字节)
                f.write(b'BM')  # 签名
                f.write(file_size.to_bytes(4, 'little'))
                f.write(b'\x00\x00\x00\x00')  # 保留
                f.write((54).to_bytes(4, 'little'))  # 数据偏移

                # 写入BMP信息头 (40字节)
                f.write((40).to_bytes(4, 'little'))  # 信息头大小
                f.write(width.to_bytes(4, 'little'))
                f.write(height.to_bytes(4, 'little'))
                f.write((1).to_bytes(2, 'little'))  # 颜色平面数
                f.write((24).to_bytes(2, 'little'))  # 每像素位数 (24位)
                f.write(b'\x00\x00\x00\x00')  # 不压缩
                f.write(image_size.to_bytes(4, 'little'))
                f.write(b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')  # 分辨率等

                # 逐像素读取并写入数据
                # BMP的像素是从下到上存储的
                for y in range(height - 1, -1, -1):
                    row_data = bytearray()
                    for x in range(width):
                        pixel_color = Lcd.getPixel(x, y)  # 获取RGB565颜色
                        # 将RGB565转换为24位BGR
                        b = (pixel_color & 0x001F) << 3
                        g = (pixel_color & 0x07E0) >> 3
                        r = (pixel_color & 0xF800) >> 8
                        row_data.extend([b, g, r])
                    f.write(row_data)

            self.log_message("INFO", f"Screenshot saved to {filename}")
        except Exception as e:
            self.log_message("ERROR", f"Screenshot failed: {e}")

    def espnow_init(self):
        print("Initializing ESP-NOW...")
        self.wifi_sta = network.WLAN(network.STA_IF)
        self.wifi_sta.active(True)
        self.espnow = espnow.ESPNow()
        self.espnow.active(True)
        self.espnow.add_peer(b'\xff' * 6)
        self.espnow.irq(self.espnow_cb)
        print("ESP-NOW Initialized.")

    def espnow_deinit(self):
        if self.espnow:
            self.espnow.active(False)
            self.espnow = None
        if self.wifi_sta:
            self.wifi_sta.active(False)
            self.wifi_sta = None
        print("ESP-NOW De-initialized.")

    def lora_init(self):
        if self.lora is None:
            try:
                self.lora = LoRaE220433Unit(1, port=(1, 2))
            except Exception as e:
                print("LoRa init failed:", e)
                return
        self.lora.receive_none_block(self.lora_cb)
        print("LoRa Initialized.")

    def lora_deinit(self):
        if self.lora:
            self.lora.stop_receive()
        print("LoRa De-initialized.")

    def toggle_espnow_mode(self):
        self.espnow_mode = not self.espnow_mode
        if self.espnow_mode:
            self.lora_deinit()
            self.espnow_init()
        else:
            self.espnow_deinit()
            self.lora_init()
        self.chat_tabs = [{'messages': [], 'buffer': ""} for _ in range(3)]
        self.presences = []
        self.max_rssi = -1000
        self.redraw_flags |= 0b111

    def setup(self):
        print("DEBUG: Starting setup function...")
        M5.begin()
        print("DEBUG: M5.begin() completed.")
        Lcd.setRotation(1)
        print("DEBUG: Lcd.setRotation(1) completed.")

        # 直接使用Lcd进行绘制，不使用canvas
        print("DEBUG: Using direct Lcd drawing instead of canvas")
        Lcd.fillScreen(BG_COLOR)
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)
        Lcd.drawString("LoRaChat App", 10, 10)
        Lcd.drawString("Loading...", 10, 30)

        # 初始化SD卡
        self.initialize_sdcard()

        # 逐点绘制扳手图标，替换pushImage方法
        for row in range(wrenchHeight):
            for col in range(wrenchWidth):
                idx = row * wrenchWidth + col
                color_pixel = wrenchData[idx]
                if color_pixel != transparencyColor:
                    Lcd.drawPixel(10 + col, 50 + row, color_pixel)

        try:
            self.kb = MatrixKeyboard()
            self.kb.set_callback(self.kb_event_cb)
            print("DEBUG: Keyboard initialized.")
        except Exception as e:
            print(f"DEBUG: Keyboard init failed: {e}")
            Lcd.drawString(f"Keyboard error: {e}", 10, 70)
        if self.espnow_mode:
            self.espnow_init()
        else:
            self.lora_init()
        print("DEBUG: Communication module initialized.")

        # 简单绘制初始UI
        print("DEBUG: Drawing simple initial UI...")
        Lcd.fillScreen(BG_COLOR)
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)
        Lcd.drawString("LoRaChat Ready", 10, 10)
        Lcd.drawString(f"Username: {self.username}", 10, 30)
        Lcd.drawString("Press TAB to change tabs", 10, 50)
        Lcd.drawString("A/B/C for chat windows", 10, 70)

        print("DEBUG: Simple UI drawn. Setup complete.")
        return True

    def initialize_sdcard(self):
        try:
            if not SDCARD_AVAILABLE:
                print("DEBUG: SD card library not available. Skipping initialization.")
                self.log_message("ERROR", "SD lib not found. Import from hardware.")
                # 尝试从当前目录加载配置文件作为备选方案
                self._try_load_config_from_alternate()
                return

            print("DEBUG: Initializing SD card for M5Cardputer using hardware library...")

            # 使用正确的参数初始化SD卡，与uiflow网页端编程得到的代码一致
            try:
                # 使用与CardputerCamera.py相同的初始化方式
                sdcard.SDCard(slot=3, width=1, sck=40, miso=39, mosi=14, cs=12, freq=20000000)
                print("DEBUG: SD card initialized successfully using hardware library.")
                # 检查是否已挂载
                try:
                    uos.stat("/sd")
                    print("DEBUG: SD card already mounted at /sd")
                    self.sdcard_mounted = True
                except OSError:
                    print("DEBUG: SD card not mounted. Hardware library should handle mounting automatically.")
                    # 尝试从当前目录加载配置文件作为备选方案
                    self._try_load_config_from_alternate()
                    return
            except Exception as e:
                print(f"DEBUG: Failed to initialize SD card using hardware library: {e}")
                import sys
                sys.print_exception(e)
                # 尝试从当前目录加载配置文件作为备选方案
                self._try_load_config_from_alternate()
                return

            # 检查并创建LoRaChat目录
            try:
                uos.stat("/sd/LoRaChat")
                print("DEBUG: LoRaChat directory already exists.")
            except OSError:
                try:
                    uos.mkdir("/sd/LoRaChat")
                    print("DEBUG: Created LoRaChat directory.")
                except Exception as e:
                    print(f"DEBUG: Failed to create LoRaChat directory: {e}")
                    # 尝试从当前目录加载配置文件作为备选方案
                    self._try_load_config_from_alternate()
                    return

            # 创建截图文件夹
            try:
                uos.stat("/sd/LoRaChat/screenshots")
            except OSError:
                try:
                    uos.mkdir("/sd/LoRaChat/screenshots")
                except Exception as e:
                    print(f"DEBUG: Failed to create screenshots directory: {e}")

            # 读取配置文件（如果存在）
            try:
                print(f"DEBUG: Trying to read config from {CONFIG_FILENAME}")
                with open(CONFIG_FILENAME, 'r') as f:
                    lines = f.readlines()
                    print(f"DEBUG: Read {len(lines)} lines from config file")
                    for line in lines:
                        line = line.strip()
                        if '=' in line and not line.startswith('#'):
                            key, value = line.split('=', 1)
                            key = key.strip()
                            value = value.strip().lower()
                            print(f"DEBUG: Config - {key} = {value}")
                            # 同时支持驼峰命名和小写命名
                            if key == 'username':
                                self.username = value
                            elif key == 'brightness':
                                try:
                                    self.brightness = int(value)
                                    Lcd.setBrightness(self.brightness)
                                except ValueError:
                                    print(f"DEBUG: Invalid brightness value: {value}")
                            elif key == 'pingmode' or key == 'pingMode':
                                self.ping_mode = value == 'on'
                            elif key == 'repeatmode' or key == 'repeatMode':
                                self.repeat_mode = value == 'on'
                            elif key == 'espnowmode' or key == 'espNowMode':
                                self.espnow_mode = value == 'on'
                print("DEBUG: Configuration loaded successfully.")
            except OSError as e:
                print(f"DEBUG: Configuration file not found or cannot be read: {e}")
                # 如果是第一次运行，创建默认配置文件
                if not self.save_settings():
                    print("DEBUG: WARNING: Failed to create default configuration file.")
                    # 尝试从当前目录加载配置文件作为备选方案
                    self._try_load_config_from_alternate()
                else:
                    print("DEBUG: Created default configuration file.")

        except Exception as e:
            print(f"DEBUG: SD card initialization failed: {e}")
            import sys
            sys.print_exception(e)
            self.log_message("ERROR", f"SD init failed: {e}")
            # 尝试从当前目录加载配置文件作为备选方案
            self._try_load_config_from_alternate()

    def _try_load_config_from_alternate(self):
        """尝试从当前目录加载配置文件作为备选方案"""
        try:
            alt_config_path = "LoRaChat.conf"
            with open(alt_config_path, 'r') as f:
                print(f"DEBUG: Loading config from alternate location: {alt_config_path}")
                for line in f:
                    line = line.strip()
                    if '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().lower()
                        print(f"DEBUG: Config (alternate) - {key} = {value}")
                        # 同时支持驼峰命名和小写命名
                        if key == 'username':
                            self.username = value
                        elif key == 'brightness':
                            try:
                                self.brightness = int(value)
                                Lcd.setBrightness(self.brightness)
                            except ValueError:
                                print(f"DEBUG: Invalid brightness value: {value}")
                        elif key == 'pingmode' or key == 'pingMode':
                            self.ping_mode = value == 'on'
                        elif key == 'repeatmode' or key == 'repeatMode':
                            self.repeat_mode = value == 'on'
                        elif key == 'espnowmode' or key == 'espNowMode':
                            self.espnow_mode = value == 'on'
            print("DEBUG: Configuration loaded from alternate location successfully.")
        except Exception as e2:
            print(f"DEBUG: Failed to load config from alternate location: {e2}")

    def save_settings(self):
        try:
            # 检查SD卡是否已挂载
            if not hasattr(self, 'sdcard_mounted') or not self.sdcard_mounted:
                print("DEBUG: SD card not mounted. Cannot save settings.")
                # 尝试重新初始化SD卡
                self.initialize_sdcard()
                if not self.sdcard_mounted:
                    self.log_message("ERROR", "Cannot save: SD not available.")
                    return False

            print("DEBUG: Saving settings to SD card...")

            # 确保目录存在
            try:
                uos.stat("/sd/LoRaChat")
            except OSError:
                try:
                    uos.mkdir("/sd/LoRaChat")
                    print("DEBUG: Created LoRaChat directory.")
                except Exception as e:
                    self.log_message("ERROR", f"Cannot create dir: {e}")
                    return False

            # 格式化配置内容，与LoRaChat.conf格式完全一致
            config_content = (
                f"username={self.username}\n"
                f"brightness={self.brightness}\n"
                f"pingMode={'on' if self.ping_mode else 'off'}\n"
                f"repeatMode={'on' if self.repeat_mode else 'off'}\n"
                f"espNowMode={'on' if self.espnow_mode else 'off'}\n"
                f"sdLogEnabled=on\n"
                f"logOutputEnabled=on\n"
            )

            print(f"DEBUG: Config content to save:\n{config_content}")

            # 写入配置文件
            try:
                # 尝试直接写入
                with open(CONFIG_FILENAME, 'w') as f:
                    bytes_written = f.write(config_content)
                print(f"DEBUG: Settings saved successfully. Wrote {bytes_written} bytes.")

                # 验证文件是否已创建
                try:
                    stat_info = uos.stat(CONFIG_FILENAME)
                    print(f"DEBUG: Config file created. Size: {stat_info[6]} bytes")
                    # 读取回文件内容进行验证
                    try:
                        with open(CONFIG_FILENAME, 'r') as f:
                            saved_content = f.read()
                            print(f"DEBUG: Verified saved content:\n{saved_content}")
                    except Exception as e:
                        print(f"DEBUG: Failed to read back saved file: {e}")
                except OSError:
                    print("DEBUG: WARNING: Config file was written but cannot be accessed.")

                self.log_message("INFO", f"Settings saved to {CONFIG_FILENAME}")

                return True
            except Exception as e:
                print(f"DEBUG: Failed to write config file: {e}")
                import sys
                sys.print_exception(e)
                # 尝试使用备用方法写入（如果有）
                try:
                    # 尝试在当前目录创建配置文件作为后备方案
                    alt_config_path = "LoRaChat.conf"
                    with open(alt_config_path, 'w') as f:
                        f.write(config_content)
                    print(f"DEBUG: Saved settings to alternate location: {alt_config_path}")
                    self.log_message("INFO", f"Settings saved to {alt_config_path}")
                    return True
                except Exception as e2:
                    print(f"DEBUG: Also failed to save to alternate location: {e2}")
                return False

        except Exception as e:
            print(f"DEBUG: Unexpected error saving settings: {e}")
            import sys
            sys.print_exception(e)
            self.log_message("ERROR", f"Unexpected error saving settings: {e}")
            return False

    def loop(self):
        try:
            M5.update()
            if M5.BtnA.wasPressed():
                self.save_screenshot()

            if self.kb:
                self.kb.tick()
            now = time.ticks_ms()
            if time.ticks_diff(now, self.last_update_time) > 1000:
                self.last_update_time = now
                new_batt = Power.getBatteryLevel()
                if new_batt != self.battery_pct:
                    self.battery_pct = new_batt
                    self.redraw_flags |= 0b001
                if time.ticks_diff(now, self.last_rx_time) > 2000 and self.max_rssi != -1000:
                    self.max_rssi = -1000
                    self.redraw_flags |= 0b001
                if self.active_tab_index == 3:
                    self.redraw_flags |= 0b100
            if self.ping_mode and time.ticks_diff(now, self.last_ping_time) > 60000:
                if time.ticks_diff(now, self.last_tx_time) > 60000:
                    self.send_message(0, "")
                self.last_ping_time = now
            if self.redraw_flags & 0b001:
                self.draw_system_bar()
            if self.redraw_flags & 0b010:
                self.draw_tab_bar()
            if self.redraw_flags & 0b100:
                self.draw_main_window()
            self.redraw_flags = 0
            gc.collect()
            time.sleep_ms(20)
        except Exception as e:
            # 显示错误到屏幕
            Lcd.fillScreen(0xFF0000)
            Lcd.setTextColor(0xFFFFFF)
            Lcd.setCursor(10, 10)
            try:
                Lcd.setFont(Widgets.FONTS.DejaVu12)
            except:
                pass
            Lcd.print("FATAL ERROR")
            Lcd.setCursor(10, 30)
            try:
                Lcd.setFont(Widgets.FONTS.DejaVu9)
            except:
                pass

            # 尝试捕获完整的错误信息并输出到webterminal
            error_str = str(e)
            print("FATAL ERROR:", error_str)

            try:
                import io, sys
                s = io.StringIO()
                sys.print_exception(e, s)
                error_str = s.getvalue()
                print("Detailed error:", error_str)
                max_len = (W - 20) // 7
                y = 30
                for i in range(0, len(error_str), max_len):
                    Lcd.drawString(error_str[i:i + max_len], 10, y)
                    y += 10
            except Exception as inner_e:
                Lcd.drawString(str(e), 10, 30)
                print("Failed to get detailed error:", inner_e)
            while True:
                time.sleep(1)


if __name__ == '__main__':
    app = LoRaChatApp()
    # 只有在 setup 成功时才进入主循环
    if app.setup():
        while True:
            app.loop()
