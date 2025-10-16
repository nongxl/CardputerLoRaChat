#include <esp_now.h>
#include <esp_wifi.h>
#include <M5Cardputer.h>
#include <M5_LoRa_E220.h>
#include <SD.h>
#include <WiFi.h>
#include <time.h>
#include <sys/time.h>

#include "common.h"
#include "draw_helper.h"

// Function prototypes
void loadLogPageFromSd(int page);
void logMessage(const String& message);

#define PING_CHANNEL 0b11
#define PING_MESSAGE ""
#define LORA_PING_INTERVAL_MS 1000 * 60    // 1 minute
#define ESP_NOW_PING_INTERVAL_MS 1000 * 15   // 15 seconds
#define PRESENCE_TIMEOUT_MS 1000 * 60 * 3 // 3 minutes, the time before a msg "expires" for the purposes of tracking a user presence

uint8_t messageNonce = 0;

LoRa_E220 lora;
struct LoRaConfigItem_t loraConfig;
struct RecvFrame_t loraFrame;
TaskHandle_t loraReceiveTaskHandle = NULL;
bool isLoraInit = false;

uint8_t espNowBroadcastAddress[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
esp_now_peer_info_t espNowBroadcastPeerInfo;
int espNowLastRssi = 0;
bool isEspNowInit = false;

M5Canvas *canvas;
M5Canvas *canvasSystemBar;
M5Canvas *canvasTabBar;

// used by draw loop to trigger redraws
volatile uint8_t keyboardRedrawFlags = RedrawFlags::None;
volatile bool receivedMessage = false; // signal to redraw window
volatile int updateDelay = 0;
volatile unsigned long lastRx = false;
volatile unsigned long lastTx = false;
const int RxTxShowDelay = 1000; // ms

// system bar state
uint8_t batteryPct = M5Cardputer.Power.getBatteryLevel();
int maxRssi = -1000;

// tab state
uint8_t activeTabIndex;

// Tab indices
const uint8_t SettingsTabIndex = 4;
const uint8_t UserInfoTabIndex = 3;
const uint8_t ChatTabCount = 3;
const uint8_t TabCount = 6;
ChatTab chatTab[ChatTabCount];

// log functionality variables
bool logTabActive = false;
int currentLogPage = 0;
int totalLogPages = 0;
std::vector<LogEntry> cachedLogEntries;
bool sdCardAvailable = false;

// settings
uint8_t activeSettingIndex;
const uint8_t MinUsernameLength = 2; // TODO
const uint8_t MaxUsernameLength = 8;
const uint8_t MaxMessageLength = 100; // TODO
String username = "user";
uint8_t brightness = 70;
float chatTextSize = 1.0; // TODO: S, M, L?
bool pingMode = true;
bool repeatMode = false;
bool espNowMode = false;
int loraWriteStage = 0;
int sdWriteStage = 0;
bool sdInit = false;
SPIClass SPI2;

// display layout constants
const uint8_t w = 240; // M5Cardputer.Display.width();
const uint8_t h = 135; // M5Cardputer.Display.height();
const uint8_t m = 2;
// system bar
const uint8_t sx = 0;
const uint8_t sy = 0;
const uint8_t sw = w;
const uint8_t sh = 20;
// tab bar
const uint8_t tx = 0;
const uint8_t ty = sy + sh;
const uint8_t tw = 16;
const uint8_t th = h - ty;
// main window
const uint8_t wx = tw;
const uint8_t wy = sy + sh;
const uint8_t ww = w - wx;
const uint8_t wh = h - wy;

String getHexString(const void *data, size_t size)
{
  const byte *bytes = (const byte *)(data);
  String hexDump = "";

  for (size_t i = 0; i < size; ++i)
  {
    char hex[4];
    snprintf(hex, sizeof(hex), "%02x ", bytes[i]);
    hexDump += hex;
  }

  return hexDump; // Return the accumulated hex dump string
}

void saveScreenshot()
{
  size_t pngLen;
  uint8_t *pngBytes = (uint8_t *)M5Cardputer.Display.createPng(&pngLen, 0, 0, 240, 135);

  int i = 0;
  String filename;
  do
  {
    filename = "/screenshot." + String(i++) + ".png";
  } while (SD.exists(filename));

  File file = SD.open(filename, FILE_WRITE);
  if (file)
  {
    file.write(pngBytes, pngLen);
    file.flush();
    file.close();
    USBSerial.println("saved screenshot to " + filename + ", " + String(pngLen) + " bytes");
  }
  else
  {
    USBSerial.println("cannot save screenshot to file " + filename);
  }

  free(pngBytes);
}

std::vector<String> getMessageLines(const String &message, int lineWidth)
{
  std::vector<String> messageLines;
  String currentLine;
  String word;

  for (char c : message)
  {
    if (std::isspace(c))
    {
      if (currentLine.length() + word.length() <= lineWidth)
      {
        currentLine += (currentLine.isEmpty() ? "" : " ") + word;
        word.clear();
      }
      else
      {
        messageLines.push_back(currentLine);
        currentLine.clear();

        currentLine += word; // TODO: word too long, hyphenate
        word.clear();
      }
    }
    else
    {
      word += c;
    }
  }

  if (!currentLine.isEmpty() || !word.isEmpty())
  {
    currentLine += (currentLine.isEmpty() ? "" : " ") + word;
    messageLines.push_back(currentLine);
  }

  return messageLines;
}

int getPresenceRssi()
{
  int maxRssiAllUsers = -1000;

  for (auto presence : presence)
  {
    // only consider presences that match the current mode
    if (espNowMode && !presence.isEspNow ||
        !espNowMode && presence.isEspNow)
    {
      continue;
    }

    // only consider presences that have been seen recently
    if (presence.rssi > maxRssiAllUsers && millis() - presence.lastSeenMillis < PRESENCE_TIMEOUT_MS)
    {
      maxRssiAllUsers = presence.rssi;
    }
  }

  return maxRssiAllUsers;
}

bool recordPresence(const Message &message)
{
  // return true if presence is new or renewed

  for (int i = 0; i < presence.size(); i++)
  {
    if (presence[i].username == message.username && presence[i].isEspNow == message.isEspNow)
    {
      presence[i].rssi = message.rssi;

      bool beenAWhile = millis() - presence[i].lastSeenMillis > PRESENCE_TIMEOUT_MS;
      presence[i].lastSeenMillis = millis();
      return beenAWhile;
    }
  }

  log_w("new %s presence: %s", message.isEspNow ? "ESP-NOW" : "LoRa", message.username.c_str());
  presence.push_back({message.username, message.isEspNow, message.rssi, millis()});
  return true;
}

void drawSystemBar()
{
  canvasSystemBar->fillSprite(BG_COLOR);
  canvasSystemBar->fillRoundRect(sx + m, sy, sw - 2 * m, sh - m, 3, UX_COLOR_DARK);
  canvasSystemBar->fillRect(sx + m, sy, sw - 2 * m, 3, UX_COLOR_DARK); // fill round edges on top
  canvasSystemBar->setTextColor(TFT_SILVER, UX_COLOR_DARK);
  canvasSystemBar->setTextSize(1);
  canvasSystemBar->setTextDatum(middle_left);
  canvasSystemBar->drawString(username, sx + 3 * m, sy + sh / 2);
  canvasSystemBar->setTextDatum(middle_center);
  canvasSystemBar->drawString(espNowMode ? "EspNowChat" : "LoRaChat", sw / 2, sy + sh / 2);
  if (millis() - lastTx < RxTxShowDelay)
    draw_tx_indicator(canvasSystemBar, sw - 71, sy + 1 * (sh / 3) - 1);
  if (millis() - lastRx < RxTxShowDelay)
    draw_rx_indicator(canvasSystemBar, sw - 71, sy + 2 * (sh / 3) - 1);
  draw_rssi_indicator(canvasSystemBar, sw - 60, sy + sh / 2 - 1, maxRssi, !espNowMode);
  draw_battery_indicator(canvasSystemBar, sw - 30, sy + sh / 2 - 1, batteryPct);
  canvasSystemBar->pushSprite(sx, sy);
}

void drawTabBar()
{
  canvasTabBar->fillSprite(BG_COLOR);
  int tabx = m;
  int tabw = tw;
  // 减小标签页高度，确保6个标签都能显示
  int tabh = (th + 3 * m) / 6;
  int tabm = 5;

  // 先绘制非活动标签
  for (int i = 5; i >= 0; i--)
  {
    if (i == activeTabIndex)
    {
      continue;
    }
    
    unsigned short color = UX_COLOR_DARK;
    int taby = tabm + i * tabh;


    // tab shape
    canvasTabBar->fillTriangle(tabx, taby, tabw, taby, tabw, taby - tabm, color);
    canvasTabBar->fillRect(tabx, taby, tabw, tabh - 2 * tabm, color);
    canvasTabBar->fillTriangle(tabx, taby + tabh - 2 * tabm, tabw, taby + tabh - 2 * tabm, tabw, taby + tabh - tabm, color);

    // label/icon
    switch (i)
    {
    case 0:
    case 1:
    case 2:
      canvasTabBar->setTextColor(TFT_SILVER, color);
      canvasTabBar->setTextDatum(middle_center);
      canvasTabBar->drawString(String(char('A' + i)), tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 2);
      break;
    case UserInfoTabIndex:
      draw_user_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    case SettingsTabIndex:
      draw_wrench_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    case 5:
      draw_log_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    }
  }
  
  // 最后绘制活动标签，确保它在最顶层
  if (activeTabIndex >= 0 && activeTabIndex < TabCount) {
    int active_i = activeTabIndex;
    unsigned short color = UX_COLOR_ACCENT;
    int taby = tabm + active_i * tabh;
    
    // tab shape
    canvasTabBar->fillTriangle(tabx, taby, tabw, taby, tabw, taby - tabm, color);
    canvasTabBar->fillRect(tabx, taby, tabw, tabh - 2 * tabm, color);
    canvasTabBar->fillTriangle(tabx, taby + tabh - 2 * tabm, tabw, taby + tabh - 2 * tabm, tabw, taby + tabh - tabm, color);
    
    // label/icon
    switch (active_i)
    {
    case 0:
    case 1:
    case 2:
      canvasTabBar->setTextColor(TFT_SILVER, color);
      canvasTabBar->setTextDatum(middle_center);
      canvasTabBar->drawString(String(char('A' + active_i)), tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 2);
      break;
    case UserInfoTabIndex:
      draw_user_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    case SettingsTabIndex:
      draw_wrench_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    case 5:
      draw_log_icon(canvasTabBar, tabx + tw / 2 - 1, taby + tabh / 2 - tabm / 2 - 3);
      break;
    }
  }
  
  canvasTabBar->pushSprite(tx, ty);
}

void drawChatWindow()
{
  // TODO: only change when font changes
  int rowCount = (wh - 3 * m) / (canvas->fontHeight() + m) - 1;
  int colCount = (ww - 4 * m) / canvas->fontWidth() - 1;
  int messageWidth = (colCount * 3) / 4;
  int messageBufferHeight = wh - ((canvas->fontHeight() + m) * rowCount) - m; // buffer takes last row plus extra space
  int messageBufferY = wh - messageBufferHeight + 2 * m;

  // draw message buffer
  for (int i = 0; i <= 1; i++)
  {
    canvas->drawLine(10, messageBufferY + i, ww - 10, messageBufferY + i, UX_COLOR_LIGHT);
  }

  if (chatTab[activeTabIndex].messageBuffer.length() > 0)
  {
    canvas->setTextDatum(middle_right);
    canvas->drawString(chatTab[activeTabIndex].messageBuffer, ww - 2 * m, messageBufferY + messageBufferHeight / 2);
  }

  // draw message window
  if (chatTab[activeTabIndex].messages.size() > 0)
  {
    int linesDrawn = 0;

    // draw all messages or until window is full
    // TODO: view index, scrolling
    for (int i = chatTab[activeTabIndex].messages.size() - 1; i >= 0; i--)
    {
      Message message = chatTab[activeTabIndex].messages[i];
      bool isOwnMessage = message.username.isEmpty();

      // show only messages that match the current mode
      if (message.isEspNow != espNowMode)
      {
        continue;
      }

      int cursorX;
      if (isOwnMessage)
      {
        cursorX = ww - 2 * m;
        canvas->setTextDatum(top_right);
      }
      else
      {
        cursorX = 2 * m;
        canvas->setTextDatum(top_left);
        message.text = message.username + message.text;
      }

      std::vector<String> lines = getMessageLines(message.text, messageWidth);
      for (int j = lines.size() - 1; j >= 0; j--)
      {
        int cursorY = 2 * m + (rowCount - linesDrawn - 1) * (canvas->fontHeight() + m);
        // canvas->setTextColor(TFT_SILVER);
        if (j == 0 && !isOwnMessage)
        {
          int usernameWidth = canvas->fontWidth() * (message.username.length() + 1);
          int textColor = UX_COLOR_ACCENT2;
          int borderColor = UX_COLOR_ACCENT;

          canvas->setTextColor(textColor);
          canvas->drawString(lines[j].substring(0, message.username.length()), cursorX, cursorY);
          canvas->drawRoundRect(cursorX - 2, cursorY - 2, usernameWidth - 3, canvas->fontHeight() + 4, 2, borderColor);

          canvas->setTextColor(TFT_SILVER);
          canvas->drawString(lines[j].substring(message.username.length()), cursorX + usernameWidth, cursorY);
        }
        else
        {
          canvas->setTextColor(TFT_SILVER);
          canvas->drawString(lines[j], cursorX, cursorY);
        }

        linesDrawn++;

        if (linesDrawn >= rowCount)
        {
          break;
        }
      }
    }
  }
}

void drawUserPresenceWindow()
{
  // TODO: order by last seen
  int entryYOffset = 20;
  int rowHeight = m + canvas->fontHeight() + m;
  int rowCount = (wh - entryYOffset) / rowHeight;
  int linesDrawn = 0;
  int cursorX = 2 * m;

  canvas->setTextColor(TFT_SILVER);
  canvas->setTextDatum(top_center);
  canvas->drawString("Users Seen", ww / 2, 2 * m);
  for (int i = 0; i <= 1; i++)
  {
    canvas->drawLine(10, 3 * m + canvas->fontHeight() + i, ww - 10, 3 * m + canvas->fontHeight() + i, UX_COLOR_LIGHT);
  }

  canvas->setTextDatum(top_left);
  for (int i = 0; i < presence.size(); i++)
  {
    // only display presences that match the current mode
    if (espNowMode && !presence[i].isEspNow ||
        !espNowMode && presence[i].isEspNow)
    {
      continue;
    }

    int cursorY = entryYOffset + i * rowHeight;
    int lastSeenSecs = (millis() - presence[i].lastSeenMillis) / 1000;

    String lastSeenString = String(lastSeenSecs) + "s"; // show seconds by default
    if (lastSeenSecs > 60 * 60 * 3)                     // show hours after 3h
    {
      lastSeenString = String(lastSeenSecs / (60 * 60)) + "h";
    }
    else if (lastSeenSecs > PRESENCE_TIMEOUT_MS / 1000) // show minutes after 5m
    {
      lastSeenString = String(lastSeenSecs / 60) + "m";
    }

    String userPresenceString = String(presence[i].username.c_str()) + "RSSI: " + String(presence[i].rssi) + ", last seen: " + lastSeenString;
    int usernameWidth = canvas->fontWidth() * (presence[i].username.length() + 1);
    int textColor = UX_COLOR_ACCENT2;
    int borderColor = UX_COLOR_ACCENT;

    canvas->setTextColor(textColor);
    canvas->drawString(userPresenceString.substring(0, presence[i].username.length()), cursorX, cursorY);
    canvas->drawRoundRect(cursorX - 2, cursorY - 2, usernameWidth - 3, canvas->fontHeight() + 4, 2, borderColor);

    canvas->setTextColor(TFT_SILVER);
    canvas->drawString(userPresenceString.substring(presence[i].username.length()), cursorX + usernameWidth, cursorY);

    linesDrawn++;

    if (linesDrawn >= rowCount)
    {
      break;
    }
  }
}

void drawSettingsWindow()
{
  int settingX = ww / 2 - 16;
  int settingXGap = 10;
  int settingYOffset = 20;

  String loraSetting;
  int loraSettingColor = 0;
  switch (loraWriteStage)
  {
  case 0:
    loraSetting = "Write to module?";
    break;
  case 1:
    loraSetting = "M0, M1 off?";
    loraSettingColor = TFT_YELLOW;
    break;
  case 2:
    loraSetting = "OK!";
    loraSettingColor = TFT_GREEN;
    break;
  case 3:
    loraSetting = "Error!";
    loraSettingColor = TFT_RED;
    break;
  }

  String writeConfigSetting;
  int writeConfigSettingColor = 0;
  switch (sdWriteStage)
  {
  case 0:
    writeConfigSetting = sdInit ? "Write to SD?" : "No SD found";
    writeConfigSettingColor = sdInit ? 0 : TFT_YELLOW;
    break;
  case 1:
    writeConfigSetting = "Overwrite?";
    writeConfigSettingColor = TFT_YELLOW;
    break;
  case 2:
    writeConfigSetting = "OK!";
    writeConfigSettingColor = TFT_GREEN;
    break;
  case 3:
    writeConfigSetting = "Error!";
    writeConfigSettingColor = TFT_RED;
    break;
  }

  String settingValues[SettingsCount];
  settingValues[Settings::Username] = username;
  settingValues[Settings::Brightness] = String(brightness);
  settingValues[Settings::PingMode] = String(pingMode ? "On" : "Off");
  settingValues[Settings::RepeatMode] = String(repeatMode ? "On" : "Off");
  settingValues[Settings::EspNowMode] = String(espNowMode ? "On" : "Off");
  settingValues[Settings::WriteConfig] = writeConfigSetting;
  settingValues[Settings::LoRaSettings] = loraSetting;

  int settingColors[SettingsCount];
  settingColors[Settings::Username] = username.length() < MinUsernameLength ? TFT_RED : (activeSettingIndex == Settings::Username ? TFT_GREEN : 0);
  settingColors[Settings::Brightness] = 0;
  settingColors[Settings::PingMode] = pingMode ? TFT_GREEN : TFT_RED;
  settingColors[Settings::RepeatMode] = repeatMode ? TFT_GREEN : TFT_RED;
  settingColors[Settings::EspNowMode] = espNowMode ? TFT_GREEN : TFT_RED;
  ;
  settingColors[Settings::WriteConfig] = writeConfigSettingColor;
  settingColors[Settings::LoRaSettings] = loraSettingColor;

  canvas->setTextColor(TFT_SILVER);
  canvas->setTextDatum(top_center);
  canvas->drawString("Settings", ww / 2, 2 * m);

  for (int i = 0; i <= 1; i++)
  {
    canvas->drawLine(10, 3 * m + canvas->fontHeight() + i, ww - 10, 3 * m + canvas->fontHeight() + i, UX_COLOR_LIGHT);
  }

  for (int i = 0; i < SettingsCount; i++)
  {
    int settingY = settingYOffset + i * (m + canvas->fontHeight() + m);
    int settingColor = i == activeSettingIndex ? COLOR_ORANGE : TFT_SILVER;

    canvas->setTextColor(settingColor);
    canvas->setTextDatum(top_right);
    canvas->drawString(SettingsNames[i] + ':', settingX, settingY);

    canvas->setTextDatum(top_left);
    canvas->setTextColor(settingColors[i] == 0 ? settingColor : settingColors[i]);
    canvas->drawString(settingValues[i], settingX + settingXGap, settingY);
  }
}

void drawLogWindow()
{
  canvas->setTextColor(TFT_SILVER);
  canvas->setTextDatum(top_center);
  canvas->drawString("Message Log", ww / 2, 2 * m);
  
  for (int i = 0; i <= 1; i++)
  {
    canvas->drawLine(10, 3 * m + canvas->fontHeight() + i, ww - 10, 3 * m + canvas->fontHeight() + i, UX_COLOR_LIGHT);
  }

  canvas->setTextDatum(top_left);
  
  // 如果日志缓存为空，尝试从SD卡加载
  if (cachedLogEntries.empty())
  {
    // 显示加载中的提示
    canvas->setTextColor(COLOR_LIGHTGRAY);
    canvas->setTextDatum(TC_DATUM); // 使用TC_DATUM代替center_center
    canvas->drawString("Loading logs...", ww / 2, wh / 2);
    canvas->pushSprite(wx, wy); // 先显示加载提示
    
    // 切换回文本对齐方式
    canvas->setTextDatum(TL_DATUM); // 使用TL_DATUM代替top_left
    
    // 加载最新的日志页
    loadLogPageFromSd(totalLogPages - 1);
  }

  // 绘制日志内容
  int lineHeight = canvas->fontHeight() + 2;
  int entryYOffset = 4 * m + canvas->fontHeight();
  int linesDrawn = 0;
  
  // 由于我们已经在loadLogPageFromSd中加载了当前页的数据
  // 这里可以直接使用cachedLogEntries中的所有数据
  for (int i = 0; i < cachedLogEntries.size(); i++)
  {
    int y = entryYOffset + linesDrawn * lineHeight;
    
    // 绘制时间戳（灰色）
    canvas->setTextColor(COLOR_LIGHTGRAY);
    canvas->drawString(cachedLogEntries[i].timestamp, 2 * m, y);
    
    // 计算内容区域的最大宽度
    int timestampWidth = canvas->fontWidth() * cachedLogEntries[i].timestamp.length();
    int contentMaxWidth = ww - 4 * m - timestampWidth;
    
    // 获取日志内容的多行显示
    std::vector<String> contentLines = getMessageLines(cachedLogEntries[i].content, contentMaxWidth / canvas->fontWidth());
    
    // 绘制日志内容（银色）
    canvas->setTextColor(TFT_SILVER);
    for (const String& line : contentLines) {
      canvas->drawString(line, 3 * m + timestampWidth, y);
      y += lineHeight;
      linesDrawn++;
      
      // 确保不会超出页面高度，留出足够空间给底部操作提示
      if (y > wh - 25) {
        break;
      }
    }
  }
  
  // 绘制页码信息
  canvas->setTextDatum(bottom_right);
  canvas->setTextColor(COLOR_LIGHTGRAY);
  canvas->drawString(String(currentLogPage + 1) + "/" + String(totalLogPages), ww - 2 * m, wh - 2 * m);
  
  // 绘制操作提示
  canvas->setTextDatum(bottom_left);
  canvas->drawString(",:Prev /:Next ␣:Refresh", 2 * m, wh - 2 * m);
}

void drawMainWindow()
{
  canvas->fillSprite(BG_COLOR);
  canvas->fillRoundRect(0, 0, ww - m, wh - m, 3, UX_COLOR_MED);
  canvas->fillRect(0, 0, 3, wh - m, UX_COLOR_MED); // removes rounded edges on left side for tabs
  canvas->setTextColor(TFT_SILVER, UX_COLOR_MED);
  canvas->setTextDatum(top_left);

  switch (activeTabIndex)
  {
  case 0:
  case 1:
  case 2:
    drawChatWindow();
    break;
  case UserInfoTabIndex:
    drawUserPresenceWindow();
    break;
  case SettingsTabIndex:
    drawSettingsWindow();
    break;
  case 5:
    drawLogWindow();
    break;
  }

  canvas->pushSprite(wx, wy);
}

bool sdCardInit()
{
  uint8_t retries = 3;
  SPI2.begin(M5.getPin(m5::pin_name_t::sd_spi_sclk),
             M5.getPin(m5::pin_name_t::sd_spi_miso),
             M5.getPin(m5::pin_name_t::sd_spi_mosi),
             M5.getPin(m5::pin_name_t::sd_spi_ss));
  while (!(sdInit = SD.begin(M5.getPin(m5::pin_name_t::sd_spi_ss), SPI2)) && retries-- > 0)
  {
    delay(100);
  }

  return sdInit;
}

// 缓存的日志索引

// 缓存的日志索引
std::vector<uint32_t> logLineOffsets;

// 构建日志文件的行偏移索引
void buildLogLineIndex() {
  if (!sdInit) return;
  
  File logFile = SD.open(LOG_FILE_PATH, FILE_READ);
  if (!logFile) {
    log_e("Failed to open log file for indexing: %s", LOG_FILE_PATH);
    return;
  }
  
  logLineOffsets.clear();
  uint32_t currentOffset = 0;
  
  // 记录第一行的偏移量
  logLineOffsets.push_back(0);
  
  // 逐字节读取文件，查找换行符
  while (logFile.available()) {
    char c = logFile.read();
    currentOffset++;
    if (c == '\n') {
      // 记录下一行的偏移量
      logLineOffsets.push_back(currentOffset);
      
      // 限制索引大小，防止内存溢出
      if (logLineOffsets.size() > MAX_CACHED_LOG_LINES + 1) {
        // 如果索引超过最大缓存行数，只保留最新的行偏移
        std::vector<uint32_t> newOffsets;
        int startIdx = logLineOffsets.size() - (MAX_CACHED_LOG_LINES + 1);
        for (int i = startIdx; i < logLineOffsets.size(); i++) {
          newOffsets.push_back(logLineOffsets[i]);
        }
        logLineOffsets = newOffsets;
      }
    }
  }
  
  logFile.close();
}

// 从日志文件加载指定页面的数据
void loadLogPageFromSd(int page)
{
  if (!sdInit)
  {
    if (!sdCardInit())
    {
      return;
    }
  }

  // 确保日志文件存在
  if (!SD.exists(LOG_FILE_PATH))
  {
    File logFile = SD.open(LOG_FILE_PATH, FILE_WRITE);
    if (logFile)
    {
      logFile.close();
    }
    cachedLogEntries.clear();
    logLineOffsets.clear();
    totalLogPages = 0;
    currentLogPage = 0;
    return;
  }

  // 如果日志索引为空，构建索引
  if (logLineOffsets.empty()) {
    buildLogLineIndex();
  }
  
  // 计算总行数和总页数（从索引获取，避免重复读取整个文件）
  int totalLines = logLineOffsets.size() > 0 ? logLineOffsets.size() - 1 : 0;
  
  // 限制缓存的最大行数
  int maxVisibleLines = (totalLines < MAX_CACHED_LOG_LINES) ? totalLines : MAX_CACHED_LOG_LINES; // 用三元运算符代替MIN宏
  totalLogPages = (maxVisibleLines + MAX_LOG_LINES_PER_PAGE - 1) / MAX_LOG_LINES_PER_PAGE;
  if (totalLogPages == 0) totalLogPages = 1;
  
  // 确保页码有效
  currentLogPage = page;
  if (currentLogPage < 0) currentLogPage = 0; // 最旧的一页
  if (currentLogPage >= totalLogPages) currentLogPage = totalLogPages - 1; // 最新的一页
  
  // 计算要加载的起始和结束行索引
  // 修改为：页面索引0对应最旧的日志，页面索引totalLogPages-1对应最新的日志
  int startLineIndex = currentLogPage * MAX_LOG_LINES_PER_PAGE;
  int endLineIndex = (currentLogPage + 1) * MAX_LOG_LINES_PER_PAGE;
  
  // 调整边界条件
  if (startLineIndex < 0) startLineIndex = 0;
  if (endLineIndex > totalLines) endLineIndex = totalLines;
  
  // 如果没有需要加载的行，清除缓存并返回
  if (startLineIndex >= endLineIndex) {
    cachedLogEntries.clear();
    return;
  }
  
  File logFile = SD.open(LOG_FILE_PATH, FILE_READ);
  if (!logFile)
  {
    log_e("Failed to open log file: %s", LOG_FILE_PATH);
    return;
  }
  
  // 清空缓存，准备加载新页面
  cachedLogEntries.clear();
  
  // 从索引获取文件偏移量并定位到指定位置
  uint32_t startOffset = logLineOffsets[startLineIndex];
  logFile.seek(startOffset);
  
  // 读取指定范围的日志行
  int linesRead = 0;
  while (logFile.available() && linesRead < (endLineIndex - startLineIndex))
  {
    String line = logFile.readStringUntil('\n');
    if (line.length() > 0)
    {
      int timestampEnd = line.indexOf(' ');
      if (timestampEnd > 0)
      {
        String timestamp = line.substring(0, timestampEnd);
        String content = line.substring(timestampEnd + 1);
        cachedLogEntries.push_back({timestamp, content});
        linesRead++;
      }
    }
  }
  
  logFile.close();
}

// 更新日志索引（在添加新日志时调用）
void updateLogIndex() {
  // 当有新日志添加时，重建索引或更新索引
  // 简化实现：直接重建索引（更可靠但不是最优的）
  buildLogLineIndex();
}

void logMessage(const String &message)
{
  if (!sdInit)
  {
    if (!sdCardInit())
    {
      return;
    }
  }

  // 创建时间戳
  time_t now = time(nullptr);
  struct tm timeinfo;
  localtime_r(&now, &timeinfo);
  char timestamp[13];
  sprintf(timestamp, "%02d-%02d %02d:%02d:%02d",
  timeinfo.tm_mon + 1, timeinfo.tm_mday,
  timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);

  // 打开文件并追加日志
  File logFile = SD.open(LOG_FILE_PATH, FILE_APPEND);
  if (logFile)
  {
    logFile.println(String(timestamp) + " " + message);
    logFile.flush();
    logFile.close();
    
    // 更新日志索引，确保下次加载时能正确定位新添加的日志行
    updateLogIndex();
  }
  else
  {
    log_e("Failed to open log file for writing: %s", LOG_FILE_PATH);
  }
}

void readConfigFromSd()
{
  M5Cardputer.update();

  if (!sdInit && !sdCardInit())
  {
    return;
  }

  File configFile = SD.open(SettingsFilename, FILE_READ);
  if (!configFile)
  {
    log_w("config file not found: %s", SettingsFilename.c_str());
    return;
  }

  log_w("reading config file: %s", SettingsFilename.c_str());

  while (configFile.available())
  {
    String line = configFile.readStringUntil('\n');
    String name = line.substring(0, line.indexOf('='));
    String value = line.substring(line.indexOf('=') + 1);

    name.trim();
    name.toLowerCase();
    value.trim();
    value.toLowerCase();

    if (name == "username")
    {
      username = value.substring(0, MaxUsernameLength);
      log_w("username: %s", username);
    }
    else if (name == "brightness")
    {
      brightness = value.toInt();
      log_w("brightness: %s", String(brightness));
    }
    else if (name == "pingmode")
    {
      pingMode = (value == "true" || value == "1" || value == "on");
      log_w("pingMode: %s", String(pingMode));
    }
    else if (name == "repeatmode")
    {
      repeatMode = (value == "true" || value == "1" || value == "on");
      log_w("repeatMode: %s", String(repeatMode));
    }
    else if (name == "espnowmode")
    {
      espNowMode = (value == "true" || value == "1" || value == "on");
      log_w("espNowMode: %s", String(espNowMode));
    }
  }

  configFile.close();
}

bool writeConfigToSd()
{
  if (!sdInit && !sdCardInit())
  {
    log_w("cannot initialize SD card");
    return false;
  }

  File configFile = SD.open(SettingsFilename, FILE_WRITE);
  if (!configFile)
  {
    return false;
  }

  log_w("writing config file: %s", SettingsFilename.c_str());

  char configLine[100];

  sprintf(configLine, "username=%s", username.c_str());
  log_w("writing line: %s", configLine);
  configFile.println(configLine);

  sprintf(configLine, "brightness=%s", String(brightness).c_str());
  log_w("writing line: %s", configLine);
  configFile.println(configLine);

  sprintf(configLine, "pingMode=%s", pingMode ? "on" : "off");
  log_w("writing line: %s", configLine);
  configFile.println(configLine);

  sprintf(configLine, "repeatMode=%s", repeatMode ? "on" : "off");
  log_w("writing line: %s", configLine);
  configFile.println(configLine);

  sprintf(configLine, "espNowMode=%s", espNowMode ? "on" : "off");
  log_w("writing line: %s", configLine);
  configFile.println(configLine);

  configFile.flush();
  configFile.close();
  return true;
}

void createFrame(int channel, const String &messageText, uint8_t *frameData, size_t &frameDataLength)
{
  // Ensure the data array has enough space
  // if (length < sizeof(message) + strlen(message.text) + 1) {
  //   std::cerr << "Error: Insufficient space to create the message." << std::endl;
  //   return;
  // }
  log_w("creating frame: |%d|%d|%s|%s|", channel, messageNonce, username, messageText);
  frameDataLength = 0;

  frameData[0] = (messageNonce & 0x3F) | ((channel & 0x03) << 6);
  frameDataLength += 1;

  size_t usernameByteLength = std::min(username.length() + 1, (unsigned int)MaxUsernameLength + 1);
  memcpy(frameData + frameDataLength, username.c_str(), usernameByteLength);
  frameDataLength += usernameByteLength;

  size_t messageTextByteLength = std::min(messageText.length() + 1, (unsigned int)MaxMessageLength + 1);
  if (messageTextByteLength > 1)
  {
  memcpy(frameData + frameDataLength, messageText.c_str(), messageTextByteLength);
  frameDataLength += messageTextByteLength;
  }
}

void parseFrame(const uint8_t *frameData, size_t frameDataLength, Message &message)
{
  // 初始化消息结构
  message.nonce = 0;
  message.channel = 0;
  message.username = "";
  message.text = "";
  
  // 检查帧长度是否有效
  if (frameDataLength < (1 + MinUsernameLength + 1) || frameDataLength > (1 + MaxUsernameLength + 1 + MaxMessageLength + 1)) {
    log_w("invalid frame length: %d", frameDataLength);
    return;
  }

  size_t frameBytesRead = 0;

  // 解析头部信息
  message.nonce = (frameData[0] & 0x3F);
  message.channel = ((frameData[0] >> 6) & 0x03);
  frameBytesRead += 1;

  // 解析用户名
  if (frameBytesRead < frameDataLength && frameData[frameBytesRead] != '\0') {
    message.username = String((const char *)(frameData + frameBytesRead), MaxUsernameLength).c_str();
    frameBytesRead += message.username.length() + 1;
  }

  // 解析消息文本
  if (frameBytesRead < frameDataLength) {
    size_t messageLength = frameDataLength - frameBytesRead;
    message.text = String((const char *)(frameData + frameBytesRead), messageLength).c_str();
  }

  log_w("parsed frame: |%d|%d|%s|%s|", message.channel, message.nonce, message.username, message.text.c_str());
}

bool sendMessage(int channel, const String &messageText, Message &sentMessage)
{
  uint8_t frameData[201]; // TODO: correct max size
  size_t frameDataLength;
  createFrame(channel, messageText, frameData, frameDataLength);

  log_w("sending frame: %s", getHexString(frameData, frameDataLength).c_str());

  int result;
  if (!espNowMode && (result = lora.SendFrame(loraConfig, frameData, frameDataLength)) == 0 ||
      espNowMode && (result = esp_now_send(espNowBroadcastAddress, frameData, frameDataLength)) == ESP_OK)
  {
    sentMessage.channel = channel;
    sentMessage.nonce = messageNonce++;
    sentMessage.username = "";
    sentMessage.text = chatTab[activeTabIndex].messageBuffer;
    sentMessage.isEspNow = espNowMode;
    sentMessage.rssi = 0;

    // 记录发送消息的日志，包含原始十六进制帧数据
    String rawFrameHex = getHexString(frameData, frameDataLength);
    String logText = String("SENT ") + (espNowMode ? "ESP-NOW" : "LoRa") + ", Ch:" + String(channel) + ", Msg:" + messageText + ", Raw:" + rawFrameHex;
    logMessage(logText);

    lastTx = millis();
    updateDelay = 0;

    return true;
  }
  else
  {
    if (espNowMode)
      log_e("error sending esp-now frame: %s", esp_err_to_name(result));
    else
      log_e("error sending LoRa frame: %d", result);
  }

  return false;
}

// 检测是否为噪声帧
bool isNoiseFrame(const uint8_t *frameData, size_t frameDataLength, int rssi)
{
  // 条件1: RSSI值异常（这里假设RSSI为1是异常值，根据实际情况调整）
  if (rssi == 1) {
    return true;
  }
  
  // 条件2: 帧太短
  if (frameDataLength < 3) {
    return true;
  }
  
  // 条件3: 全是相同的字节（如全FF、全0等）
  bool allSame = true;
  uint8_t firstByte = frameData[0];
  for (size_t i = 1; i < frameDataLength; i++) {
    if (frameData[i] != firstByte) {
      allSame = false;
      break;
    }
  }
  if (allSame && (firstByte == 0xFF || firstByte == 0x00)) {
    return true;
  }
  
  // 条件4: 检查是否包含有效ASCII文本（特别是用户名部分）
  // 如果帧包含可打印ASCII字符（字母数字等），很可能是有效帧
  int printableCharCount = 0;
  int invalidCharCount = 0;
  
  for (size_t i = 0; i < frameDataLength; i++) {
    // 头部字节（第一个字节）可以包含特殊值，不参与可打印字符统计
    if (i == 0) continue;
    
    // 检查是否为可打印ASCII字符或null终止符
    if ((frameData[i] >= 0x20 && frameData[i] <= 0x7E) || frameData[i] == 0x00) {
      if (frameData[i] != 0x00) printableCharCount++;
    } else {
      invalidCharCount++;
    }
  }
  
  // 如果有足够多的可打印字符，不是噪声帧
  if (printableCharCount >= 3) { // 至少有3个可打印字符，可能是用户名的一部分
    return false;
  }
  
  // 条件5: 包含无效的控制字符比例过高（仅当没有足够多的可打印字符时检查）
  if (frameDataLength > 1 && (float)invalidCharCount / (frameDataLength - 1) > 0.5) { // 超过50%的非头部字符是无效的
    return true;
  }
  
  return false;
}

void receiveMessage(const uint8_t *frameData, size_t frameDataLength, int rssi, bool isEspNow)
{
  String rawFrameHex = getHexString(frameData, frameDataLength);
  log_w("received frame: %s", rawFrameHex.c_str());
  
  // 先检查是否为噪声帧
  bool noiseDetected = isNoiseFrame(frameData, frameDataLength, rssi);
  
  // 记录噪声检测信息
  if (noiseDetected) {
    String noiseLog = String("[DEBUG] Noise ignored: ") + rawFrameHex + String(", RSSI: ") + String(rssi);
    logMessage(noiseLog);
    
    // 记录详细的RSSI信息
    String rssiLog = String("[LORA] RSSI: ") + String(rssi);
    logMessage(rssiLog);
    
    // 记录原始包信息
    String rawLog = String("[RAW] Packet: ") + rawFrameHex + String(", RSSI: ") + String(rssi);
    logMessage(rawLog);
    
    // 对于噪声帧，可以直接返回，不进行后续处理
    return;
  }

  Message message;
  parseFrame(frameData, frameDataLength, message);
  message.isEspNow = isEspNow;
  message.rssi = rssi;
  lastRx = millis();
  updateDelay = 0;

  // 记录接收到的消息的日志，包含原始十六进制帧数据
  // 区分可解码和无法解码的消息
  String logText;
  if (message.text.isEmpty() || message.username.isEmpty()) {
    // 无法解码或部分解码的消息
    logText = String("RECV ") + (isEspNow ? "ESP-NOW" : "LoRa") + ", UNKNOWN FORMAT, RSSI:" + String(rssi) + ", Raw:" + rawFrameHex;
  } else {
    // 正常解码的消息
    logText = String("RECV ") + (isEspNow ? "ESP-NOW" : "LoRa") + ", Ch:" + String(message.channel) + ", From:" + message.username + ", RSSI:" + String(rssi) + ", Msg:" + message.text + ", Raw:" + rawFrameHex;
  }
  logMessage(logText);

  // TODO: check nonce, replay for basic meshing

  if (!message.username.isEmpty() && recordPresence(message) && !repeatMode && millis() - lastTx > 1000)
  {
    log_w("new presence, sending response ping");
    Message sentMessage;
    sendMessage(PING_CHANNEL, "", sentMessage);
  }

  if (message.text.isEmpty())
    return;

  chatTab[message.channel].messages.push_back(message);
  receivedMessage = true;

  if (repeatMode)
  {
    String response = String("name: " + String(message.username) + ", msg: " + String(message.text) + ", rssi: " + String(rssi));
    Message sentMessage;
    if (sendMessage(message.channel, response, sentMessage))
    {
      chatTab[activeTabIndex].messages.push_back(sentMessage);
    }
  }
}

void pingTask(void *pvParameters)
{
  // send out a ping every so often during inactivity to keep presence for other users
  Message sentMessage;
  sendMessage(PING_CHANNEL, PING_MESSAGE, sentMessage);

  while (1)
  {
    unsigned long pingInterval = espNowMode ? ESP_NOW_PING_INTERVAL_MS : LORA_PING_INTERVAL_MS;
    if (pingMode && millis() - lastTx > pingInterval)
    {
      sendMessage(PING_CHANNEL, PING_MESSAGE, sentMessage);
    }

    delay(1000);
  }
}

void espNowOnReceive(const uint8_t *mac, const uint8_t *data, int dataLength)
{
  // look backwards from the data pointer to find the start of the wifi frame to get RSSI
  // https://github.com/espressif/esp-now/blob/a60681b6453d060e7da7a1f7bcee15fded68d904/src/espnow/src/espnow.c#L187
  wifi_promiscuous_pkt_t *promiscuous_pkt = (wifi_promiscuous_pkt_t *)(data - sizeof(wifi_pkt_rx_ctrl_t) - sizeof(espnow_frame_format_t));
  wifi_pkt_rx_ctrl_t *rx_ctrl = &promiscuous_pkt->rx_ctrl;

  log_w("esp-now frame received, rssi: %d", rx_ctrl->rssi);
  receiveMessage(data, dataLength, rx_ctrl->rssi, true);
}

void espNowInit()
{
  if (isEspNowInit)
  {
    log_w("esp-now already enabled");
    return;
  }

  log_w("enabling esp-now");

  WiFi.mode(WIFI_STA);

  esp_err_t result;
  if ((result = esp_now_init()) != ESP_OK)
  {
    log_e("error initializing ESP-NOW: %s", esp_err_to_name(result));
    return;
  }

  memcpy(espNowBroadcastPeerInfo.peer_addr, espNowBroadcastAddress, 6);
  espNowBroadcastPeerInfo.channel = 0;
  espNowBroadcastPeerInfo.encrypt = false;

  if (esp_now_add_peer(&espNowBroadcastPeerInfo) != ESP_OK)
  {
    log_e("Failed to add peer");
    return;
  }

  esp_now_register_recv_cb(espNowOnReceive);

  isEspNowInit = true;
}

void espNowDeinit()
{
  if (!isEspNowInit)
  {
    log_w("esp-now already disabled");
    return;
  }

  log_w("disabling esp-now");
  esp_now_deinit();
  WiFi.mode(WIFI_OFF);
  isEspNowInit = false;
}

void loraReceiveTask(void *pvParameters)
{
  while (1)
  {
    if (lora.RecieveFrame(&loraFrame) == 0)
    {
      log_w("lora frame received, rssi: %d", loraFrame.rssi);
      receiveMessage(loraFrame.recv_data, loraFrame.recv_data_len, loraFrame.rssi, false);
    }

    delay(1);
  }
}

void loraInit()
{
  if (isLoraInit)
  {
    log_w("LoRa already enabled");
    return;
  }

  log_w("enabling LoRa");

  lora.Init(&Serial2, 9600, SERIAL_8N1, 1, 2);
  lora.SetDefaultConfigValue(loraConfig);
  lora.InitLoRaSetting(loraConfig);
  xTaskCreateUniversal(loraReceiveTask, "loraReceiveTask", 8192, NULL, 1, &loraReceiveTaskHandle, APP_CPU_NUM);

  isLoraInit = true;
}

void loraDeinit()
{
  if (!isLoraInit)
  {
    log_w("LoRa already disabled");
    return;
  }

  log_w("disabling LoRa");

  vTaskDelete(loraReceiveTaskHandle);
  loraReceiveTaskHandle = NULL;

  isLoraInit = false;
}

bool updateStringFromInput(Keyboard_Class::KeysState keyState, String &str, int maxLength = 255, bool alphaNumericOnly = false)
{
  bool updated = false;

  for (auto i : keyState.word)
  {
    if (str.length() >= maxLength)
    {
      log_e("max length reached (%d): [%s]!+[%s]", maxLength, str.c_str(), String(i).c_str());
    }
    else if (alphaNumericOnly && !std::isalnum(i))
    {
      log_e("non-alphanumeric character: [%s]!+[%s]", str.c_str(), String(i).c_str());
    }
    else
    {
      str += i;
      updated = true;
    }
  }

  if (keyState.del && str.length() > 0)
  {
    str.remove(str.length() - 1);
    updated = true;
  }

  return updated;
}

void handleChatTabInput(Keyboard_Class::KeysState keyState, uint8_t &redrawFlags)
{
  if (updateStringFromInput(keyState, chatTab[activeTabIndex].messageBuffer))
  {
    redrawFlags |= RedrawFlags::MainWindow;
  }

  if (keyState.enter)
  {
    // log_w(chatTab[activeTabIndex].messageBuffer.c_str());

    chatTab[activeTabIndex].messageBuffer.trim();

    // empty message reserved for pings
    if (chatTab[activeTabIndex].messageBuffer.isEmpty())
    {
      return;
    }

    Message sentMessage;
    if (sendMessage(activeTabIndex, chatTab[activeTabIndex].messageBuffer, sentMessage))
    {
      chatTab[activeTabIndex].messages.push_back(sentMessage);
    }
    else
    {
      sentMessage.text = "send failed";
      chatTab[activeTabIndex].messages.push_back(sentMessage);
    }

    chatTab[activeTabIndex].messageBuffer.clear();
    redrawFlags |= RedrawFlags::MainWindow;
  }
}

void handleSettingsTabInput(Keyboard_Class::KeysState keyState, uint8_t &redrawFlags)
{
  if (M5Cardputer.Keyboard.isKeyPressed(';'))
  {
    activeSettingIndex = (activeSettingIndex == 0)
                             ? SettingsCount - 1
                             : activeSettingIndex - 1;
    redrawFlags |= RedrawFlags::MainWindow;
  }
  if (M5Cardputer.Keyboard.isKeyPressed('.'))
  {
    activeSettingIndex = (activeSettingIndex + 1) % SettingsCount;
    redrawFlags |= RedrawFlags::MainWindow;
  }

  switch (activeSettingIndex)
  {
  case Settings::Username:
    if (updateStringFromInput(keyState, username, MaxUsernameLength, true))
    {
      redrawFlags |= RedrawFlags::SystemBar | RedrawFlags::MainWindow;
    }
    break;
  case Settings::Brightness:
    for (auto c : keyState.word)
    {
      if (c == ',' || c == '/')
      {
        brightness = (c == ',')
                         ? max(0, brightness - 10)
                         : min(100, brightness + 10);
        M5Cardputer.Display.setBrightness(brightness);
        redrawFlags |= RedrawFlags::MainWindow;
        break;
      }
    }
    break;
  case Settings::PingMode:
    for (auto c : keyState.word)
    {
      if (c == ',' || c == '/')
      {
        pingMode = !pingMode;
        redrawFlags |= RedrawFlags::MainWindow;
      }
    }
    if (keyState.enter)
    {
      pingMode = !pingMode;
      redrawFlags |= RedrawFlags::MainWindow;
    }
    break;
  case Settings::RepeatMode:
    for (auto c : keyState.word)
    {
      if (c == ',' || c == '/')
      {
        repeatMode = !repeatMode;
        redrawFlags |= RedrawFlags::MainWindow;
      }
      break;
    }
    if (keyState.enter)
    {
      repeatMode = !repeatMode;
      redrawFlags |= RedrawFlags::MainWindow;
    }
    break;
  case Settings::EspNowMode:
    for (auto c : keyState.word)
    {
      if (c == ',' || c == '/')
      {
        espNowMode = !espNowMode;

        if (espNowMode)
        {
          loraDeinit();
          espNowInit();
        }
        else
        {
          espNowDeinit();
          loraInit();
        }

        lastRx = lastTx = 0;
        maxRssi = -1000;
        redrawFlags |= RedrawFlags::MainWindow | RedrawFlags::SystemBar;
      }
    }
    break;
  case Settings::WriteConfig:
    if (keyState.enter)
    {
      if (!sdInit)
        break;

      switch (sdWriteStage)
      {
      case 0:
        sdWriteStage++;
        if (SD.exists(SettingsFilename))
          break;
      case 1:
        sdWriteStage = (writeConfigToSd())
                           ? sdWriteStage + 1
                           : sdWriteStage + 2;
        break;
      default:
        sdWriteStage = 0;
        break;
      }

      redrawFlags |= RedrawFlags::MainWindow;
    }
    break;
  case Settings::LoRaSettings:
    if (keyState.enter)
    {
      switch (loraWriteStage)
      {
      case 0:
        // show switch reminder
        loraWriteStage++;
        break;
      case 1:
        // try to write
        // debug
        loraWriteStage = (lora.InitLoRaSetting(loraConfig) == 0)
                             ? loraWriteStage + 1
                             : loraWriteStage + 2;
        break;
      default:
        loraWriteStage = 0;
        break;
      }

      redrawFlags |= RedrawFlags::MainWindow;
    }
    break;
  }

  if (activeSettingIndex != Settings::WriteConfig)
  {
    sdWriteStage = 0;
  }

  if (activeSettingIndex != Settings::LoRaSettings)
  {
    loraWriteStage = 0;
  }
}

void keyboardInputTask(void *pvParameters)
{
  const unsigned long debounceDelay = 200;
  unsigned long lastKeyPressMillis = 0;

  while (1)
  {
    M5Cardputer.update();
    if (M5Cardputer.Keyboard.isChange() && M5Cardputer.Keyboard.isPressed())
    {
      uint8_t redrawFlags = RedrawFlags::None;
      if (millis() - lastKeyPressMillis >= debounceDelay)
      {
        lastKeyPressMillis = millis();

        // need to see again with display off
        if (brightness <= 10 && !M5Cardputer.Keyboard.isKeyPressed(','))
        {
          brightness = 50;
          M5Cardputer.Display.setBrightness(brightness);
          redrawFlags |= RedrawFlags::MainWindow;
        }

        Keyboard_Class::KeysState keyState = M5Cardputer.Keyboard.keysState();

        if (activeTabIndex == SettingsTabIndex)
        {
          handleSettingsTabInput(keyState, redrawFlags);
        }
        else if (activeTabIndex == UserInfoTabIndex)
        {
          // TODO? what sort of input would be useful here?
        }
        else if (activeTabIndex == 5) // 日志标签页索引
        {
          // 日志标签页的输入处理：逗号和斜杠键用于翻页，空格用于刷新
          for (auto c : keyState.word)
          {
            if (c == ',')
            {
              // 上一页（更旧的日志）
              loadLogPageFromSd(currentLogPage - 1);
              redrawFlags |= RedrawFlags::MainWindow;
              break;
            }
            else if (c == '/')
            {
              // 下一页（更新的日志）
              loadLogPageFromSd(currentLogPage + 1);
              redrawFlags |= RedrawFlags::MainWindow;
              break;
            }
            else if (c == ' ') {
              // 刷新并跳转到最新页
              loadLogPageFromSd(totalLogPages - 1);
              redrawFlags |= RedrawFlags::MainWindow;
              break;
            }
          }
        }
        else
        {
          handleChatTabInput(keyState, redrawFlags);
        }

        if (keyState.tab)
        {
          activeTabIndex = (activeTabIndex + 1) % TabCount;
          updateDelay = 0;
          redrawFlags |= RedrawFlags::TabBar | RedrawFlags::MainWindow;
        }
      }

      keyboardRedrawFlags = redrawFlags;
    }

    if (M5Cardputer.BtnA.isPressed())
    {
      saveScreenshot();
    }
  }
}

// 时间设置函数
void setupDateTime() {
  // 创建一个临时画布用于双缓冲，避免闪烁
  M5Canvas dateTimeCanvas(&M5Cardputer.Display);
  dateTimeCanvas.createSprite(ww, wh);
  
  // 使用支持中文的字体设置
  dateTimeCanvas.setTextSize(1);
  dateTimeCanvas.setTextColor(WHITE);
  
  // 当前时间组件
  int year = 2025;  // 默认年份
  int month = 10;    // 默认月份
  int day = 16;      // 默认日期
  int hour = 14;    // 默认小时
  int minute = 30;   // 默认分钟
  int second = 30;   // 默认秒数
  int currentField = 0;  // 0:year, 1:month, 2:day, 3:hour, 4:minute, 5:second
  
  bool settingDone = false;
  const unsigned long debounceDelay = 200;
  unsigned long lastKeyPressMillis = 0;
  int prevYear = -1, prevMonth = -1, prevDay = -1;
  int prevHour = -1, prevMinute = -1, prevSecond = -1;
  int prevField = -1;
  
  // 初始清屏
  dateTimeCanvas.fillScreen(BLACK);
  dateTimeCanvas.setCursor(10, 20);
  // 使用英文替代中文，避免字体问题
  dateTimeCanvas.print("Set Date & Time");
  
  // 更新提示信息，反映新的操作方式（分成两行，移到更高位置）
  dateTimeCanvas.setCursor(10, 90);
  dateTimeCanvas.setTextColor(GREEN);
  dateTimeCanvas.print(",:<-- /:--> ;:Increase -:Decrease");
  dateTimeCanvas.setCursor(10, 105);
  dateTimeCanvas.print("TAB:Next ENTER:Confirm");
  
  // 初始推送到屏幕
  dateTimeCanvas.pushSprite(0, 0);
  
  while (!settingDone) {
    bool needsUpdate = false;
    
    // 检查是否需要更新显示
    if (year != prevYear || month != prevMonth || day != prevDay || 
        hour != prevHour || minute != prevMinute || second != prevSecond || 
        currentField != prevField) {
      needsUpdate = true;
      
      // 更新前一次的值
      prevYear = year; prevMonth = month; prevDay = day;
      prevHour = hour; prevMinute = minute; prevSecond = second;
      prevField = currentField;
    }
    
    if (needsUpdate) {
      // 扩大清除区域，确保完全清除旧的焦点高亮
      dateTimeCanvas.fillRect(0, 0, 240, 240, BLACK);
      
      // 重新绘制标题
      dateTimeCanvas.setCursor(80, 20);
      dateTimeCanvas.setTextColor(WHITE);
      dateTimeCanvas.print("Set Date & Time");
      
      // 重新绘制提示信息，分成两行以确保完整显示
      dateTimeCanvas.setCursor(10, 90);
      dateTimeCanvas.setTextColor(GREEN);
      dateTimeCanvas.print(",:<-- /:--> ;:Increase -:Decrease");
      dateTimeCanvas.setCursor(10, 105);
      dateTimeCanvas.print("TAB:Next ENTER:Confirm");
      
      // 绘制年月日（向上调整位置）
      dateTimeCanvas.setCursor(20, 45);
      dateTimeCanvas.setTextColor(currentField == 0 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%04d", year);
      dateTimeCanvas.setTextColor(WHITE);
      dateTimeCanvas.print("-");
      
      dateTimeCanvas.setTextColor(currentField == 1 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%02d", month);
      dateTimeCanvas.setTextColor(WHITE);
      dateTimeCanvas.print("-");
      
      dateTimeCanvas.setTextColor(currentField == 2 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%02d", day);
      
      // 绘制时分秒（向上调整位置）
      dateTimeCanvas.setCursor(20, 65);
      dateTimeCanvas.setTextColor(currentField == 3 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%02d", hour);
      dateTimeCanvas.setTextColor(WHITE);
      dateTimeCanvas.print(":");
      
      dateTimeCanvas.setTextColor(currentField == 4 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%02d", minute);
      dateTimeCanvas.setTextColor(WHITE);
      dateTimeCanvas.print(":");
      
      dateTimeCanvas.setTextColor(currentField == 5 ? YELLOW : WHITE);
      dateTimeCanvas.printf("%02d", second);
      
      // 使用pushSprite一次性更新屏幕，减少闪烁
      dateTimeCanvas.pushSprite(0, 0);
    }
    
    // 处理按键输入
    M5Cardputer.update();
    if (M5Cardputer.Keyboard.isChange() && millis() - lastKeyPressMillis >= debounceDelay) {
      lastKeyPressMillis = millis();
      
      Keyboard_Class::KeysState keyState = M5Cardputer.Keyboard.keysState();
      
      for (auto c : keyState.word) {
        if (c == ',') {
          // 向左切换输入焦点
          currentField = (currentField - 1 + 6) % 6;
        } else if (c == '/') {
          // 向右切换输入焦点
          currentField = (currentField + 1) % 6;
        } else if (c == ';') {
          // 增加当前字段的值
          switch (currentField) {
            case 0: year = min(2030, year + 1); break;
            case 1: month = min(12, month + 1); break;
            case 2: day = min(31, day + 1); break;
            case 3: hour = (hour + 1) % 24; break;
            case 4: minute = (minute + 1) % 60; break;
            case 5: second = (second + 1) % 60; break;
          }
        } else if (c == '.') {
          // 减少当前字段的值
          switch (currentField) {
            case 0: year = max(2020, year - 1); break;
            case 1: month = max(1, month - 1); break;
            case 2: day = max(1, day - 1); break;
            case 3: hour = (hour - 1 + 24) % 24; break;
            case 4: minute = (minute - 1 + 60) % 60; break;
            case 5: second = (second - 1 + 60) % 60; break;
          }
        }
      }
      
      if (keyState.tab) {
        // 保留tab键向右切换功能
        currentField = (currentField + 1) % 6;
      }
      
      if (keyState.enter) {
        // 确认设置，设置系统时间
        struct tm timeinfo;
        timeinfo.tm_year = year - 1900;
        timeinfo.tm_mon = month - 1;
        timeinfo.tm_mday = day;
        timeinfo.tm_hour = hour;
        timeinfo.tm_min = minute;
        timeinfo.tm_sec = second;
        timeinfo.tm_isdst = -1;  // 不使用夏令时
        
        time_t epoch = mktime(&timeinfo);
        if (epoch > 0) {
          struct timeval tv;
          tv.tv_sec = epoch;
          tv.tv_usec = 0;
          settimeofday(&tv, NULL);
          // 使用英文日志信息
          logMessage("System time set: " + String(year) + "-" + String(month) + "-" + String(day) + " " + String(hour) + ":" + String(minute) + ":" + String(second));
        }
        
        settingDone = true;
      }
    }
    
    delay(10);
  }
  
  // 释放临时画布资源
  dateTimeCanvas.deleteSprite();
}

void setup()
{
  USBSerial.begin(115200);
  auto cfg = M5.config();
  M5Cardputer.begin(cfg, true);

  M5Cardputer.Display.init();
  M5Cardputer.Display.setRotation(1);
  
  // 初始化时间库
  time_t now = time(nullptr);
  if (now < 1000000000) {  // 如果时间无效（1970年前）
    setupDateTime();  // 运行时间设置
  }

  canvas = new M5Canvas(&M5Cardputer.Display);
  canvas->createSprite(ww, wh);
  canvasSystemBar = new M5Canvas(&M5Cardputer.Display);
  canvasSystemBar->createSprite(sw, sh);
  canvasTabBar = new M5Canvas(&M5Cardputer.Display);
  canvasTabBar->createSprite(tw, th);

  chatTab[0] = {0, {}, "", 0};
  chatTab[1] = {1, {}, "", 0};
  chatTab[2] = {2, {}, "", 0};
  activeTabIndex = 0;
  activeSettingIndex = 0;

  readConfigFromSd();
  // 读取配置后立即应用亮度设置
  M5Cardputer.Display.setBrightness(brightness);

  drawSystemBar();
  drawTabBar();
  drawMainWindow();

  if (espNowMode)
    espNowInit();
  else
    loraInit();

  xTaskCreateUniversal(pingTask, "pingTask", 8192, NULL, 1, NULL, APP_CPU_NUM);
  xTaskCreateUniversal(keyboardInputTask, "keyboardInputTask", 8192, NULL, 1, NULL, APP_CPU_NUM);
}

void loop()
{
  uint8_t redrawFlags = RedrawFlags::None;

  if (keyboardRedrawFlags)
  {
    redrawFlags |= keyboardRedrawFlags;
    keyboardRedrawFlags = RedrawFlags::None;
  }

  if (receivedMessage)
  {
    redrawFlags |= RedrawFlags::MainWindow;
    receivedMessage = false;
  }

  // redraw occasionally for system bar updates and user info tab
  if (millis() > updateDelay)
  {
    bool redraw = false;
    updateDelay = millis() + 5000;

    int newBatteryPct = M5Cardputer.Power.getBatteryLevel();
    if (newBatteryPct != batteryPct)
    {
      batteryPct = newBatteryPct;
      redrawFlags |= RedrawFlags::SystemBar;
    }

    int newRssi = getPresenceRssi();
    if (newRssi != maxRssi)
    {
      maxRssi = newRssi;
      redrawFlags |= RedrawFlags::SystemBar;
    }

    if (millis() - lastRx < RxTxShowDelay * 2 || millis() - lastTx < RxTxShowDelay * 2)
    {
      updateDelay = millis() + RxTxShowDelay / 2;
      redrawFlags |= RedrawFlags::SystemBar;
    }

    // redraw every second to update last seen times
    if (activeTabIndex == UserInfoTabIndex)
    {
      updateDelay = millis() + 1000;
      redrawFlags |= RedrawFlags::MainWindow;
    }
  }

  if (redrawFlags & RedrawFlags::TabBar)
    drawTabBar();
  if (redrawFlags & RedrawFlags::SystemBar)
    drawSystemBar();
  if (redrawFlags & RedrawFlags::MainWindow)
    drawMainWindow();

  delay(10);
}