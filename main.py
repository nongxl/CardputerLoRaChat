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

# --- 图标数据 ---
transparencyColor = 0x0000
wrenchWidth, wrenchHeight = 10, 10
# 扳手图标数据 - 简化定义
wrenchData = [
    0,0,0,0,0,1,1,1,0,0,
    0,0,0,0,1,1,1,0,0,0,
    0,0,0,1,1,1,0,0,0,1,
    0,0,0,1,1,1,0,0,1,1,
    0,0,0,0,1,1,1,1,1,1,
    0,0,0,1,1,1,1,1,1,0,
    0,0,1,1,1,0,1,1,0,0,
    0,1,1,1,0,0,0,0,0,0,
    1,1,1,0,0,0,0,0,0,0,
    1,1,0,0,0,0,0,0,0,0
]
# 将0转换为透明色，1转换为绿色
for i in range(len(wrenchData)):
    wrenchData[i] = transparencyColor if wrenchData[i] == 0 else COLOR_GREEN
userWidth, userHeight = 10, 10
# 用户图标数据 - 简化定义
userData = [
    0,0,0,0,1,1,0,0,0,0,
    0,0,0,1,1,1,1,0,0,0,
    0,0,0,1,1,1,1,0,0,0,
    0,0,0,0,1,1,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,
    0,0,0,1,1,1,1,0,0,0,
    0,0,1,1,1,1,1,1,0,0,
    0,0,1,1,1,1,1,1,0,0,
    0,0,1,1,1,1,1,1,0,0,
    0,0,1,1,1,1,1,1,0,0
]
# 将0转换为透明色，1转换为绿色
for i in range(len(userData)):
    userData[i] = transparencyColor if userData[i] == 0 else COLOR_GREEN

logWidth, logHeight = 10, 10
# 日志图标数据 - 简化定义
logData = [
    0,0,0,0,0,0,0,0,0,0,
    0,1,1,1,1,1,1,1,1,0,
    0,1,0,0,0,0,0,0,1,0,
    0,1,0,0,0,0,0,0,1,0,
    0,1,0,0,0,0,0,0,1,0,
    0,1,0,0,0,0,0,0,1,0,
    0,1,1,1,1,1,1,1,1,0,
    0,0,1,1,1,1,1,1,1,1,
    0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0
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
        
        # 初始化滚动状态
        self.log_scroll_offset = 0
        
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
            Lcd.fillTriangle(TX + M, taby + tabh - 2 * tabm, TX + TW, taby + tabh - 2 * tabm, TX + TW, taby + tabh - tabm, color)
            
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
                            Lcd.drawPixel(center_x - userWidth // 2 + col, center_y + 4 - userHeight // 2 + row, color_pixel)
            elif i == 4:
                # 绘制扳手图标
                for row in range(wrenchHeight):
                    for col in range(wrenchWidth):
                        idx = row * wrenchWidth + col
                        color_pixel = wrenchData[idx]
                        if color_pixel != transparencyColor:
                            Lcd.drawPixel(center_x - wrenchWidth // 2 + col, center_y + 4 - wrenchHeight // 2 + row, color_pixel)
            elif i == 5:
                # 绘制日志图标
                for row in range(logHeight):
                    for col in range(logWidth):
                        idx = row * logWidth + col
                        color_pixel = logData[idx]
                        if color_pixel != transparencyColor:
                            Lcd.drawPixel(center_x - logWidth // 2 + col, center_y + 4 - logHeight // 2 + row, color_pixel)

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
        Lcd.drawLine(WX + 10, buffer_y, WX + WW - 10, buffer_y, COLOR_GRAY)
        buffer_text = self.chat_tabs[self.active_tab_index]['buffer']
        if buffer_text:
            text_width = Lcd.textWidth(buffer_text)
            Lcd.drawString(buffer_text, WX + WW - 2 * M - text_width, buffer_y + (buffer_h - font_h) // 2)
        messages = self.chat_tabs[self.active_tab_index]['messages']
        if not messages: 
            return
        lines_drawn = 0
        for msg in reversed(messages):
            if lines_drawn >= row_count: 
                break
            is_own = msg['username'] == ""
            text = msg['text'] if is_own else msg['username'] + ": " + msg['text']
            max_chars = (WW - 4 * M) // 7
            lines = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
            for line in reversed(lines):
                if lines_drawn >= row_count: 
                    break
                cursor_y = WY + 2 * M + (row_count - lines_drawn - 1) * (font_h + M)
                if is_own:
                    text_width = Lcd.textWidth(line)
                    Lcd.drawString(line, WX + WW - 2 * M - text_width, cursor_y)
                else:
                    username_part = msg['username'] + ": "
                    if line.startswith(username_part):
                        username_width = Lcd.textWidth(username_part)
                        Lcd.drawString(username_part, WX + 2 * M, cursor_y)
                        Lcd.drawRoundRect(WX + 2 * M - 2, cursor_y - 2, username_width, font_h + 4, 2, COLOR_YELLOW)
                        Lcd.drawString(line[len(username_part):], WX + 2 * M + username_width, cursor_y)
                    else:
                        Lcd.drawString(line, WX + 2 * M, cursor_y)
                lines_drawn += 1

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
        
        # 绘制设置项，采用与旧版本相同的布局
        settings_map = [
            ("Username", self.username),
            ("Brightness", f"{self.brightness}%"),
            ("Ping Mode", "On" if self.ping_mode else "Off"),
            ("Repeat Mode", "On" if self.repeat_mode else "Off"),
            ("ESP-NOW Mode", "On" if self.espnow_mode else "Off"),
            ("Save to Conf", "Press Enter")
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
            scrollbar_y = WY + 30 + (WH - 30 - scrollbar_height) * scroll_index // (len(settings_map) - visible_settings)
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
            
            # 绘制设置值
            Lcd.setTextColor(status_color if status_color is not None else base_color, COLOR_BLACK)
            Lcd.drawString(str(value), WX + WW // 2 + x_offset, y_pos)
            
            y_pos += 20  # 适当增加行间距以提高可读性
        
        # 重置文本颜色和字体为默认值
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)

    def draw_log_window(self):
        # 直接使用Lcd绘制日志窗口，确保无背景色和一致的字体
        
        # 先清除整个窗口背景
        Lcd.fillRect(WX, WY, WW, WH, COLOR_BLACK)
        
        # 设置统一字体
        Lcd.setFont(Widgets.FONTS.DejaVu9)
        
        # 绘制标题 - 居中显示，并确保文本背景与窗口背景一致
        title = "Message Log"
        title_width = Lcd.textWidth(title)
        Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
        Lcd.drawString(title, WX + (WW - title_width) // 2, WY + 10)
        Lcd.drawLine(WX, WY + 25, WX + WW, WY + 25, COLOR_GRAY)
        
        # 如果没有日志消息，显示提示
        if not self.log_messages:
            no_msg_text = "No messages received yet"
            no_msg_width = Lcd.textWidth(no_msg_text)
            Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
            Lcd.drawString(no_msg_text, WX + (WW - no_msg_width) // 2, WY + 40)
            Lcd.setTextColor(COLOR_WHITE)
            Lcd.setFont(Widgets.FONTS.DejaVu12)
            return
        
        # 实现滚动功能
        line_height = 12
        visible_lines = (WH - 35) // line_height  # 可见行数
        
        # 创建滚动位置属性（如果不存在）
        if not hasattr(self, 'log_scroll_offset'):
            self.log_scroll_offset = 0
        
        # 确保滚动偏移量有效
        max_offset = max(0, len(self.log_messages) - visible_lines)
        self.log_scroll_offset = min(self.log_scroll_offset, max_offset)
        
        # 绘制滚动条
        if len(self.log_messages) > visible_lines:
            scrollbar_width = 4
            scrollbar_height = max(10, (WH - 30) * visible_lines // len(self.log_messages))
            scrollbar_y = WY + 30 + (WH - 30 - scrollbar_height) * self.log_scroll_offset // max_offset
            Lcd.fillRect(WX + WW - scrollbar_width - 2, WY + 30, scrollbar_width, WH - 30, COLOR_DARKGRAY)
            Lcd.fillRect(WX + WW - scrollbar_width - 2, scrollbar_y, scrollbar_width, scrollbar_height, UX_COLOR_ACCENT)
        
        # 绘制可见的日志消息
        y_offset = WY + WH - 10
        start_idx = len(self.log_messages) - visible_lines - self.log_scroll_offset
        start_idx = max(0, start_idx)
        
        for message in self.log_messages[start_idx:start_idx + visible_lines]:
            y_offset -= line_height
            if y_offset < WY + 35:  # 预留标题区域
                break
            
            # 清除行背景
            Lcd.fillRect(WX, y_offset, WW, line_height, COLOR_BLACK)
            # 截断过长的消息以适应屏幕宽度
            max_chars = (WW - 20) // 5  # 估计每个字符的宽度
            if len(message) > max_chars:
                message = message[:max_chars] + "..."
            
            # 确保文本颜色为白色，背景为黑色
            Lcd.setTextColor(COLOR_WHITE, COLOR_BLACK)
            Lcd.drawString(message, WX + 10, y_offset)
            
        # 重置文本颜色和字体为默认值
        Lcd.setTextColor(COLOR_WHITE)
        Lcd.setFont(Widgets.FONTS.DejaVu12)

    def handle_input(self, key):
        print(f"DEBUG: Key received: {repr(key)}")  # 添加调试信息
        
        if self.active_tab_index == 5:  # 日志窗口
            # 日志窗口滚动控制
            if key == '\r':  # 按回车返回设置窗口
                self.active_tab_index = 4
                self.redraw_flags |= 0b100
            elif key == ';':  # 向上滚动
                if hasattr(self, 'log_scroll_offset'):
                    self.log_scroll_offset = max(0, self.log_scroll_offset - 1)
                    self.redraw_flags |= 0b100
            elif key == '.':  # 向下滚动
                if hasattr(self, 'log_scroll_offset') and hasattr(self, 'log_messages'):
                    visible_lines = (WH - 35) // 12
                    max_offset = max(0, len(self.log_messages) - visible_lines)
                    self.log_scroll_offset = min(self.log_scroll_offset + 1, max_offset)
                    self.redraw_flags |= 0b100
        elif self.active_tab_index == 4:  # 设置窗口
            settings_count = 6  # 与旧版本一致，共6个设置项
            
            # 使用;和.选择设置项
            if key == ';':
                print("DEBUG: Previous setting selected")
                self.active_setting_index = (self.active_setting_index - 1 + settings_count) % settings_count
                self.redraw_flags |= 0b100
            elif key == '.':
                print("DEBUG: Next setting selected")
                self.active_setting_index = (self.active_setting_index + 1) % settings_count
                self.redraw_flags |= 0b100
            else:
                # 根据当前选中的设置项处理输入
                setting_to_edit = self.active_setting_index
                if setting_to_edit == 0:  # 用户名设置
                    if key == '\x08':  # 退格键
                        self.username = self.username[:-1]
                        print(f"DEBUG: Username edited: {self.username}")
                    elif len(key) == 1 and len(self.username) < 8:  # 普通字符键
                        self.username += key
                        print(f"DEBUG: Username edited: {self.username}")
                elif setting_to_edit == 1:  # 亮度设置
                    if key == ',':  # 亮度降低
                        print(f"DEBUG: Brightness down: {self.brightness} -> {max(0, self.brightness - 10)}")
                        self.brightness = max(0, self.brightness - 10)
                        Lcd.setBrightness(self.brightness)
                    if key == '/':  # 亮度增加
                        print(f"DEBUG: Brightness up: {self.brightness} -> {min(100, self.brightness + 10)}")
                        self.brightness = min(100, self.brightness + 10)
                        Lcd.setBrightness(self.brightness)
                elif setting_to_edit == 2:  # Ping模式
                    if key == '\r':  # 回车键切换
                        print(f"DEBUG: Ping mode toggled: {self.ping_mode} -> {not self.ping_mode}")
                        self.ping_mode = not self.ping_mode
                elif setting_to_edit == 3:  # Repeat模式
                    if key == '\r':  # 回车键切换
                        print(f"DEBUG: Repeat mode toggled: {self.repeat_mode} -> {not self.repeat_mode}")
                        self.repeat_mode = not self.repeat_mode
                elif setting_to_edit == 4:  # 通信模式
                    if key == '\r':  # 回车键切换
                        print(f"DEBUG: Communication mode toggled")
                        self.toggle_espnow_mode()
                elif setting_to_edit == 5:  # 保存配置
                    if key == '\r':  # 回车键保存
                        print(f"DEBUG: Saving settings")
                        self.save_settings()
                
                # 如果有任何设置被修改，触发重绘
                if setting_to_edit >= 0:
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
        self.chat_tabs[channel]['messages'].append(msg)
        payload = "{}:{}".format(self.username, text)
        if self.espnow_mode and self.espnow:
            self.espnow.send(b'\xff' * 6, payload)
        elif self.lora:
            # 修正: LoRaE220 库的 send 方法需要字节串(bytes), 而不是字符串(str)。
            # 这是导致从SD卡加载配置后程序崩溃的根本原因。
            self.lora.send(0xFFFF, channel, payload.encode('utf-8'))
        self.last_tx_time = time.ticks_ms()
        self.redraw_flags |= 0b100

    def handle_received_message(self, sender, message, rssi):
        # 打印所有接收到的原始报文，包括噪声
        print("Received raw packet: {}, RSSI: {}".format(message, rssi))

        # 将原始报文添加到日志中（无论是否可解码）
        timestamp = time.localtime()
        time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
        raw_log_entry = f"[{time_str}] RAW: {message}, RSSI: {rssi}"
        self.log_messages.append(raw_log_entry)
        # 保持日志长度不超过20条
        if len(self.log_messages) > self.max_log_messages:
            self.log_messages.pop(0)

        try:
            # 步骤 1: 尝试解码。如果数据不是有效的UTF-8（例如噪声），则会失败。
            decoded_text = message.decode('utf-8')
        except UnicodeError:
            # 步骤 2: 如果解码失败，则认为是噪声，打印一条信息并直接返回。
            print("Received non-utf8 data (noise), ignoring: {}".format(message))
            return

        try:
            self.last_rx_time = time.ticks_ms()
            self.max_rssi = rssi if rssi > self.max_rssi else self.max_rssi
            parts = decoded_text.split(':', 1)
            if len(parts) == 2:
                username, text = parts
                if not text and not self.repeat_mode: 
                    return
                msg = {'username': username, 'text': text, 'rssi': rssi, 'is_espnow': self.espnow_mode}
                self.chat_tabs[0]['messages'].append(msg)
                self.redraw_flags |= 0b100
                if self.repeat_mode:
                    response = "rp:{}|{}|{}".format(username, text, rssi)
                    self.send_message(0, response)
                found = False
                for p in self.presences:
                    if p['username'] == username:
                        p['rssi'] = rssi
                        p['last_seen'] = time.ticks_ms()
                        found = True
                        break
                if not found:
                    self.presences.append({'username': username, 'rssi': rssi, 'last_seen': time.ticks_ms()})
                
                # 将解码后的消息添加到日志中
                decoded_log_entry = f"[{time_str}] {username}: {text}"
                self.log_messages.append(decoded_log_entry)
                # 保持日志长度不超过20条
                if len(self.log_messages) > self.max_log_messages:
                    self.log_messages.pop(0)
        except Exception as e:
            print("Message processing error: {} on data: {}".format(e, message))

    def lora_cb(self, data, rssi):
        if data:
            # 将消息添加到日志中
            timestamp = time.localtime()
            time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
            log_entry = f"[{time_str}] LoRa: RSSI: {rssi}"
            self.log_messages.append(log_entry)
            # 保持日志长度不超过20条
            if len(self.log_messages) > self.max_log_messages:
                self.log_messages.pop(0)
            self.handle_received_message(None, data, rssi)

    def espnow_cb(self, mac, msg):
        if msg:
            try:
                rssi = self.wifi_sta.status('rssi')
                # 将消息添加到日志中
                timestamp = time.localtime()
                time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                log_entry = f"[{time_str}] ESPNow: {mac.hex()}: RSSI: {rssi}"
                self.log_messages.append(log_entry)
                # 保持日志长度不超过20条
                if len(self.log_messages) > self.max_log_messages:
                    self.log_messages.pop(0)
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
            self.redraw_flags |= 0b110
            return
        self.handle_input(key)

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
        # 标记SD卡是否可用和挂载状态
        self.sdcard_mounted = False
        
        try:
            if not SDCARD_AVAILABLE:
                print("DEBUG: SD card library not available. Skipping initialization.")
                # 添加错误日志，提示用户需要从hardware导入sdcard
                timestamp = time.localtime()
                time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                self.log_messages.append(f"[{time_str}] ERROR: SD card library not found. Make sure to import from hardware.")
                if len(self.log_messages) > self.max_log_messages:
                    self.log_messages.pop(0)
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
            sys.print_exception(e)  # 打印完整的异常栈跟踪
            # 添加错误日志
            timestamp = time.localtime()
            time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
            self.log_messages.append(f"[{time_str}] ERROR initializing SD card: {str(e)}")
            if len(self.log_messages) > self.max_log_messages:
                self.log_messages.pop(0)
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
                    # 添加错误日志
                    timestamp = time.localtime()
                    time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                    self.log_messages.append(f"[{time_str}] ERROR: SD card not available")
                    if len(self.log_messages) > self.max_log_messages:
                        self.log_messages.pop(0)
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
                    print(f"DEBUG: Failed to create LoRaChat directory: {e}")
                    timestamp = time.localtime()
                    time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                    self.log_messages.append(f"[{time_str}] ERROR: Cannot create directory: {e}")
                    if len(self.log_messages) > self.max_log_messages:
                        self.log_messages.pop(0)
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
                    
                # 添加成功日志消息
                timestamp = time.localtime()
                time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                self.log_messages.append(f"[{time_str}] Settings saved to {CONFIG_FILENAME}")
                if len(self.log_messages) > self.max_log_messages:
                    self.log_messages.pop(0)
                
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
                    timestamp = time.localtime()
                    time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
                    self.log_messages.append(f"[{time_str}] Settings saved to alternate location: {alt_config_path}")
                    if len(self.log_messages) > self.max_log_messages:
                        self.log_messages.pop(0)
                    return True
                except Exception as e2:
                    print(f"DEBUG: Also failed to save to alternate location: {e2}")
                return False
                
        except Exception as e:
            print(f"DEBUG: Unexpected error saving settings: {e}")
            import sys
            sys.print_exception(e)
            # 添加错误日志
            timestamp = time.localtime()
            time_str = f"{timestamp[3]:02d}:{timestamp[4]:02d}:{timestamp[5]:02d}"
            self.log_messages.append(f"[{time_str}] ERROR saving settings: {e}")
            if len(self.log_messages) > self.max_log_messages:
                self.log_messages.pop(0)
            return False

    def loop(self):
        try:
            M5.update()
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
