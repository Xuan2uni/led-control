// ESP32-S3 三指手势灯串口控制程序
// 接收 "LED 000" 到 "LED 111"，按食指/中指/无名指分别控制三盏灯。

const int INDEX_LED_PIN = 4;
const int MIDDLE_LED_PIN = 5;
const int RING_LED_PIN = 7;

void setAllLights(bool enabled) {
  const int level = enabled ? HIGH : LOW;
  digitalWrite(INDEX_LED_PIN, level);
  digitalWrite(MIDDLE_LED_PIN, level);
  digitalWrite(RING_LED_PIN, level);
}

bool isBinaryDigit(char value) {
  return value == '0' || value == '1';
}

void setFingerLights(const String &mask) {
  digitalWrite(INDEX_LED_PIN, mask[0] == '1' ? HIGH : LOW);
  digitalWrite(MIDDLE_LED_PIN, mask[1] == '1' ? HIGH : LOW);
  digitalWrite(RING_LED_PIN, mask[2] == '1' ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);

  pinMode(INDEX_LED_PIN, OUTPUT);
  pinMode(MIDDLE_LED_PIN, OUTPUT);
  pinMode(RING_LED_PIN, OUTPUT);

  setAllLights(false);
  Serial.println("READY");
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String command = Serial.readStringUntil('\n');
  command.trim();

  if (
    command.length() == 7
    && command.startsWith("LED ")
    && isBinaryDigit(command[4])
    && isBinaryDigit(command[5])
    && isBinaryDigit(command[6])
  ) {
    String mask = command.substring(4);
    setFingerLights(mask);
    Serial.print("ACK LED ");
    Serial.println(mask);
  } else if (command == "ON") {
    setAllLights(true);
    Serial.println("ACK ON");
  } else if (command == "OFF") {
    setAllLights(false);
    Serial.println("ACK OFF");
  } else if (command.length() > 0) {
    Serial.print("UNKNOWN ");
    Serial.println(command);
  }
}
