

import atexit
import hashlib
import math
import time
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import serial
from serial.tools import list_ports


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = PROJECT_ROOT / "models" / "gesture_recognizer.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)
MODEL_SHA256 = "97952348cf6a6a4915c2ea1496b4b37ebabc50cbbf80571435643c455f2b0482"

# ESP32-S3 通过 CH340/CH343 连接到电脑后的串口参数
SERIAL_BAUD_RATE = 115200
SERIAL_STARTUP_SECONDS = 2.0

# 手指状态确认参数。缩短确认时间并略微降低角度阈值，提高响应速度。
FINGER_CONFIRM_SECONDS = 0.15
FINGER_STRAIGHT_ANGLE = 145.0

# MediaPipe 手指关键点编号：MCP、PIP、DIP、TIP
FINGER_LANDMARK_IDS = {
    "INDEX": (5, 6, 7, 8),
    "MIDDLE": (9, 10, 11, 12),
    "RING": (13, 14, 15, 16),
}


def joint_angle(point_a, point_b, point_c):
    """计算以 point_b 为顶点的三维夹角，返回角度值。"""
    vector_ba = (
        point_a.x - point_b.x,
        point_a.y - point_b.y,
        point_a.z - point_b.z,
    )
    vector_bc = (
        point_c.x - point_b.x,
        point_c.y - point_b.y,
        point_c.z - point_b.z,
    )

    dot_product = sum(a * c for a, c in zip(vector_ba, vector_bc))
    length_ba = math.sqrt(sum(value * value for value in vector_ba))
    length_bc = math.sqrt(sum(value * value for value in vector_bc))

    if length_ba == 0 or length_bc == 0:
        return 0.0

    cosine = dot_product / (length_ba * length_bc)
    cosine = max(-1.0, min(1.0, cosine))
    return math.degrees(math.acos(cosine))


def get_finger_state(hand_landmarks, landmark_ids):
    """根据 PIP 和 DIP 两个关节角判断一根手指是否伸展。"""
    mcp_id, pip_id, dip_id, tip_id = landmark_ids
    mcp = hand_landmarks[mcp_id]
    pip = hand_landmarks[pip_id]
    dip = hand_landmarks[dip_id]
    tip = hand_landmarks[tip_id]

    pip_angle = joint_angle(mcp, pip, dip)
    dip_angle = joint_angle(pip, dip, tip)
    is_extended = (
        pip_angle >= FINGER_STRAIGHT_ANGLE
        and dip_angle >= FINGER_STRAIGHT_ANGLE
    )
    return is_extended, pip_angle, dip_angle


def draw_finger(frame, hand_landmarks, landmark_ids, color):
    """在画面中标出一根手指的 MCP、PIP、DIP 和 TIP。"""
    height, width = frame.shape[:2]
    points = []

    for landmark_id in landmark_ids:
        landmark = hand_landmarks[landmark_id]
        point = (int(landmark.x * width), int(landmark.y * height))
        points.append(point)

    for start, end in zip(points, points[1:]):
        cv2.line(frame, start, end, color, 3)

    for point in points:
        cv2.circle(frame, point, 7, color, cv2.FILLED)


def send_light_command(connection, command):
    """向 ESP32 发送灯光命令。"""
    try:
        connection.write(f"{command}\n".encode("ascii"))
        connection.flush()
    except serial.SerialException as error:
        raise RuntimeError(
            f"向 ESP32 发送 {command} 失败，请检查 USB 连接。"
        ) from error

    print(f"已发送到 ESP32：{command}")


def find_esp32_port():
    """自动查找使用 CH340 或 CH343 USB 转串口芯片的开发板。"""
    matches = []

    for port in list_ports.comports():
        description = f"{port.description} {port.manufacturer} {port.hwid}".upper()
        if "CH340" in description or "CH343" in description:
            matches.append(port.device)

    if not matches:
        raise RuntimeError(
            "没有找到 ESP32 的 CH340/CH343 串口。请连接开发板的 USB 转串口接口。"
        )

    selected_port = sorted(matches)[0]
    print(f"找到 ESP32 串口：{selected_port}")
    return selected_port


board = None


def shutdown_hardware():
    """退出程序时尽量关闭全部 LED，并释放串口。"""
    if board is None or not board.is_open:
        return

    try:
        board.write(b"OFF\n")
        board.flush()
    except serial.SerialException:
        pass
    finally:
        board.close()


atexit.register(shutdown_hardware)


BaseOptions = mp.tasks.BaseOptions
GestureRecognizer = mp.tasks.vision.GestureRecognizer
GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
RunningMode = mp.tasks.vision.RunningMode


options = GestureRecognizerOptions(
    base_options=BaseOptions(model_asset_path=str(MODEL_PATH)),
    running_mode=RunningMode.IMAGE,
    num_hands=1,
    min_hand_detection_confidence=0.5,
    min_hand_presence_confidence=0.5,
    min_tracking_confidence=0.5,
)

# 诊断结果：编号 0 是电脑前置摄像头，编号 1 是外接 USB Camera。
# DirectShow 对普通 UVC 摄像头兼容性较好。
camera = cv2.VideoCapture(1, cv2.CAP_DSHOW)

if not camera.isOpened():
    raise RuntimeError("无法打开摄像头，请检查摄像头权限或设备编号。")

# 设置摄像头分辨率
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

serial_port = find_esp32_port()

try:
    board = serial.Serial(
        serial_port,
        SERIAL_BAUD_RATE,
        timeout=1,
        write_timeout=1,
    )
except serial.SerialException as error:
    camera.release()
    raise RuntimeError(
        f"无法打开 ESP32 串口 {serial_port}。请关闭 Arduino Serial Monitor，"
        "并检查开发板的 USB 连接。"
    ) from error

# 打开串口会使部分 ESP32 开发板复位，等待固件完成启动。
time.sleep(SERIAL_STARTUP_SECONDS)
board.reset_input_buffer()
send_light_command(board, "LED 000")

light_state = "CLOSE"
message = "Extend index, middle and ring fingers"
last_sent_finger_mask = "000"

finger_candidates = {name: None for name in FINGER_LANDMARK_IDS}
finger_candidate_starts = {name: None for name in FINGER_LANDMARK_IDS}
finger_states = {name: "UNKNOWN" for name in FINGER_LANDMARK_IDS}
finger_messages = {
    name: f"{name}: NO HAND" for name in FINGER_LANDMARK_IDS
}
finger_colors = {
    name: (200, 200, 200) for name in FINGER_LANDMARK_IDS
}


def calculate_sha256(file_path):
    """分块计算文件的 SHA-256，避免把整个模型读入内存。"""
    digest = hashlib.sha256()
    with file_path.open("rb") as model_file:
        for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model():
    """首次运行时下载官方模型，并检查文件是否完整。"""
    if MODEL_PATH.exists() and calculate_sha256(MODEL_PATH) == MODEL_SHA256:
        return

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = MODEL_PATH.with_suffix(".task.part")
    temporary_path.unlink(missing_ok=True)

    print("正在下载 MediaPipe 手势识别模型，请稍候……")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            with temporary_path.open("wb") as model_file:
                while chunk := response.read(1024 * 1024):
                    model_file.write(chunk)
    except Exception as error:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError(
            "模型下载失败，请检查网络后重新运行程序。"
        ) from error

    if calculate_sha256(temporary_path) != MODEL_SHA256:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("模型校验失败，请重新运行程序下载。")

    temporary_path.replace(MODEL_PATH)
    print(f"模型已保存到：{MODEL_PATH}")


ensure_model()


with GestureRecognizer.create_from_options(options) as recognizer:
    while True:
        success, frame = camera.read()

        if not success:
            print("读取摄像头画面失败")
            break

        # 镜像画面，使操作体验接近照镜子
        frame = cv2.flip(frame, 1)

        # OpenCV 使用 BGR，MediaPipe 需要 RGB
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_image = mp.Image(
            image_format=mp.ImageFormat.SRGB,
            data=rgb_frame,
        )

        result = recognizer.recognize(mp_image)

        # 检测食指、中指和无名指的伸展状态
        if result.hand_landmarks:
            hand_landmarks = result.hand_landmarks[0]
            now = time.perf_counter()

            for finger_name, landmark_ids in FINGER_LANDMARK_IDS.items():
                is_extended, pip_angle, dip_angle = get_finger_state(
                    hand_landmarks,
                    landmark_ids,
                )
                raw_state = "EXTENDED" if is_extended else "FOLDED"

                if raw_state != finger_candidates[finger_name]:
                    finger_candidates[finger_name] = raw_state
                    finger_candidate_starts[finger_name] = now

                stable_time = now - finger_candidate_starts[finger_name]
                progress = min(
                    stable_time / FINGER_CONFIRM_SECONDS,
                    1.0,
                )

                if stable_time >= FINGER_CONFIRM_SECONDS:
                    finger_states[finger_name] = raw_state

                if finger_states[finger_name] == "EXTENDED":
                    finger_colors[finger_name] = (0, 255, 0)
                elif finger_states[finger_name] == "FOLDED":
                    finger_colors[finger_name] = (0, 165, 255)
                else:
                    finger_colors[finger_name] = (200, 200, 200)

                draw_finger(
                    frame,
                    hand_landmarks,
                    landmark_ids,
                    finger_colors[finger_name],
                )
                finger_messages[finger_name] = (
                    f"{finger_name}: {finger_states[finger_name]}  "
                    f"PIP: {pip_angle:.0f}  DIP: {dip_angle:.0f}  "
                    f"Confirm: {progress * 100:.0f}%"
                )
        else:
            for finger_name in FINGER_LANDMARK_IDS:
                finger_candidates[finger_name] = None
                finger_candidate_starts[finger_name] = None
                finger_states[finger_name] = "UNKNOWN"
                finger_colors[finger_name] = (200, 200, 200)
                finger_messages[finger_name] = f"{finger_name}: NO HAND"

        # 三位掩码依次对应食指、中指、无名指及 GPIO4、GPIO5、GPIO7。
        finger_mask = "".join(
            "1" if finger_states[name] == "EXTENDED" else "0"
            for name in FINGER_LANDMARK_IDS
        )

        if finger_mask != last_sent_finger_mask:
            send_light_command(board, f"LED {finger_mask}")
            last_sent_finger_mask = finger_mask

        if finger_mask == "111":
            light_state = "OPEN"
            message = "All three fingers are extended"
        else:
            light_state = "CLOSE"
            message = f"Finger LED mask: {finger_mask}"

        # 根据灯光状态选择显示颜色
        if light_state == "OPEN":
            state_color = (0, 255, 0)
        else:
            state_color = (0, 0, 255)

        cv2.putText(
            frame,
            f"STATE: {light_state}",
            (30, 60),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.4,
            state_color,
            3,
        )

        cv2.putText(
            frame,
            message,
            (30, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        cv2.putText(
            frame,
            "Press Q to quit",
            (30, 150),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (200, 200, 200),
            2,
        )

        for row, finger_name in enumerate(FINGER_LANDMARK_IDS):
            cv2.putText(
                frame,
                finger_messages[finger_name],
                (30, 205 + row * 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                finger_colors[finger_name],
                2,
            )

        cv2.imshow("Gesture Light Controller", frame)

        # 按 Q 退出
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break


camera.release()
cv2.destroyAllWindows()
shutdown_hardware()
