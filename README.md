# LED Control

基于 MediaPipe、OpenCV 和 ESP32-S3 的三指手势 LED 控制项目。电脑通过外接摄像头识别食指、中指、无名指的伸展状态，再通过 USB 串口向 ESP32-S3 发送三位控制命令。

## 控制规则

| 手指状态 | 串口掩码 | ESP32 引脚 | LED 状态 |
| --- | --- | --- | --- |
| 食指伸展（绿色） | `100` | GPIO4 | 食指灯亮 |
| 中指伸展（绿色） | `010` | GPIO5 | 中指灯亮 |
| 无名指伸展（绿色） | `001` | GPIO7 | 无名指灯亮 |
| 三指全部伸展 | `111` | GPIO4/5/7 | 全亮，界面显示 `OPEN` |
| 没有检测到手 | `000` | GPIO4/5/7 | 全灭，界面显示 `CLOSE` |

三指没有全部伸展时，界面显示 `CLOSE`；已经伸展的手指仍会单独点亮对应 LED。

## 硬件

- ESP32-S3-N16R8 开发板
- USB 摄像头
- 3 个普通 LED
- 3 个 200Ω 或 220Ω 限流电阻
- 面包板和杜邦线
- USB Type-C 数据线

接线：

```text
GPIO4 ── 电阻 ── 食指LED长脚    LED短脚 ── GND
GPIO5 ── 电阻 ── 中指LED长脚    LED短脚 ── GND
GPIO7 ── 电阻 ── 无名指LED长脚  LED短脚 ── GND
```

开发板上的任意 GND 引脚都可以连接到面包板公共地。

## 目录

```text
led-control/
├── firmware/esp32_led_control/esp32_led_control.ino
├── models/README.md
├── pc/main.py
├── requirements.txt
└── README.md
```

## 1. 烧录 ESP32 固件

在 Arduino IDE 中安装 **esp32 by Espressif Systems**，打开：

```text
firmware/esp32_led_control/esp32_led_control.ino
```

选择：

```text
Tools → Board → ESP32 Arduino → ESP32S3 Dev Module
Tools → Port → 开发板对应的 CH340/CH343 串口
```

点击 **Upload**。固件启动后默认关闭三盏灯，并接收 `LED 000` 到 `LED 111` 命令。

中国大陆网络可按照 [Espressif 官方安装说明](https://docs.espressif.com/projects/arduino-esp32/en/latest/installing.html) 使用 `-cn` 镜像包。

## 2. 安装电脑端依赖

在仓库根目录打开 PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 3. 运行

确保 Arduino Serial Monitor 已关闭，然后执行：

```powershell
python pc\main.py
```

首次运行会从 MediaPipe 官方地址下载约 8 MB 的手势识别模型，并校验 SHA-256；以后会直接使用本地模型。程序会自动寻找 CH340/CH343 串口。按 `Q` 退出，退出时会向 ESP32 发送关灯命令。

当前摄像头编号在 `pc/main.py` 中设置为 `1`，对应开发时使用的外接 USB 摄像头。如果设备顺序发生变化，可将 `cv2.VideoCapture(1, cv2.CAP_DSHOW)` 中的编号改为检测到的摄像头编号。

## 使用的开源组件

- [MediaPipe](https://github.com/google-ai-edge/mediapipe)：手部关键点和手势识别
- [OpenCV](https://github.com/opencv/opencv)：摄像头读取和界面显示
- [pySerial](https://github.com/pyserial/pyserial)：电脑与 ESP32 串口通信
- [Arduino-ESP32](https://github.com/espressif/arduino-esp32)：ESP32-S3 Arduino 支持

运行所需的 `models/gesture_recognizer.task` 会在首次启动时自动下载，因此不存入 Git 仓库。

