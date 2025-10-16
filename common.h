#include <Arduino.h>

enum RedrawFlags
{
  MainWindow = 0b001,
  SystemBar = 0b010,
  TabBar = 0b100,
  None = 0b000
};

// TODO: refine message format
struct Message
{
  uint8_t nonce : 6;
  uint8_t channel : 2; // 4 channels, 0b01,0b10,0b11 channels, 0b11 reserved for pings
  String username;     // use MAC or something tied to device?
  bool isEspNow;
  int rssi;
  String text;
};

// track presence of other users
struct Presence
{
  String username;
  bool isEspNow;
  int rssi;
  unsigned long lastSeenMillis;
};
std::vector<Presence> presence;

struct ChatTab
{
  unsigned char channel;
  // TODO: access in thread-safe way
  std::vector<Message> messages;
  String messageBuffer;
  int viewIndex;
};

enum Settings
{
  Username = 0,
  Brightness = 1,
  PingMode = 2,
  RepeatMode = 3,
  EspNowMode = 4,
  WriteConfig = 5,
  LoRaSettings = 6
};

const int SettingsCount = 7;
const String SettingsNames[SettingsCount] = {"Username", "Brightness", "Ping Mode", "Repeat Mode", "ESP-NOW Mode", "App Config", "LoRa Config"};
const String SettingsFilename = "/LoRaChat/LoRaChat.conf";

// hack
typedef struct {
    uint16_t frame_head;
    uint16_t duration;
    uint8_t destination_address[6];
    uint8_t source_address[6];
    uint8_t broadcast_address[6];
    uint16_t sequence_control;

    uint8_t category_code;
    uint8_t organization_identifier[3]; // 0x18fe34
    uint8_t random_values[4];
    struct {
        uint8_t element_id;                 // 0xdd
        uint8_t lenght;
        uint8_t organization_identifier[3]; // 0x18fe34
        uint8_t type;                       // 4
        uint8_t version;
        uint8_t body[0];
    } vendor_specific_content;
} __attribute__ ((packed)) espnow_frame_format_t;

// Log related constants and variables
#define LOG_FILE_PATH "/LoRaChat/logs.txt"
#define LOG_INDEX_PATH "/LoRaChat/logs.index"

// Maximum number of log lines per page
#define MAX_LOG_LINES_PER_PAGE 4

// Maximum number of cached log lines
#define MAX_CACHED_LOG_LINES 200

// Index of the log tab
#define LogTabIndex 3

// Structure for log lines
struct LogEntry {
    String timestamp;
    String content;
};

// Global variables for log functionality
extern bool logTabActive;
extern int currentLogPage;
extern int totalLogPages;
extern std::vector<LogEntry> cachedLogEntries;
extern bool sdCardAvailable;