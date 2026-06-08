import csv
import json
from collections import deque
from decimal import Decimal, InvalidOperation
from numbers import Real

from PyQt6.QtCore import QIODeviceBase, Qt, QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtSerialPort import QSerialPort, QSerialPortInfo
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from realtime_plot import RealtimePlot


class SerialWindow(QMainWindow):
    MAX_JSON_BUFFER_CHARS = 20000
    PLOT_REFRESH_INTERVAL_MS = 100
    PARSED_MESSAGE_LIMIT = 12
    LINE_COLORS = (
        ("Teal", "#0f766e"),
        ("Blue", "#2563eb"),
        ("Red", "#dc2626"),
        ("Purple", "#9333ea"),
        ("Amber", "#ca8a04"),
        ("Cyan", "#0891b2"),
        ("Green", "#16a34a"),
        ("Orange", "#ea580c"),
        ("Black", "#111827"),
        ("Gray", "#6b7280"),
    )
    LINE_STYLES = (
        ("Solid", Qt.PenStyle.SolidLine),
        ("Dash", Qt.PenStyle.DashLine),
        ("Dot", Qt.PenStyle.DotLine),
        ("Dash Dot", Qt.PenStyle.DashDotLine),
        ("Dash Dot Dot", Qt.PenStyle.DashDotDotLine),
    )
    LINE_WIDTHS = (1, 2, 3, 4, 5, 6)

    def __init__(self):
        super().__init__()
        self.serial = QSerialPort(self)
        self.serial.readyRead.connect(self.read_serial_data)
        self.serial.errorOccurred.connect(self.on_serial_error)

        self.json_decoder = json.JSONDecoder()
        self.json_buffer = ""
        self.records = []
        self.channel_sample_counts = {}
        self.plot_record_queues = {}
        self.plot_sample_index = 0
        self.parsed_latest_by_channel = {}
        self.parsed_messages = deque(maxlen=self.PARSED_MESSAGE_LIMIT)
        self.current_x_key = "timestamp"
        self.current_y_key = "Freq"
        self.channel_ids = ["0012"]
        self.channel_id_inputs = []
        self.channel_inputs_layout = None
        self.connection_dialog = None
        self.mode_dialog = None
        self.channel_dialog = None
        self.curve_dialog = None
        self.plot_option_combo = None
        self.plot_option_pages = None
        self.line_settings_layout = None
        self.line_style_inputs = {}

        self.setWindowTitle("串口数据接收与 JSON 解析绘图")
        self.resize(1180, 760)
        self.setStyleSheet(
            """
            QWidget {
                font-size: 11pt;
            }
            QLineEdit, QComboBox, QPushButton {
                min-height: 26px;
            }
            """
        )

        self.port_combo = QComboBox()
        self.baud_combo = QComboBox()
        self.stop_bits_combo = QComboBox()
        self.data_bits_combo = QComboBox()
        self.parity_combo = QComboBox()
        self.refresh_button = QPushButton("刷新串口")
        self.open_button = QPushButton("打开串口")
        self.close_button = QPushButton("关闭串口")
        self.clear_button = QPushButton("清空数据")
        self.status_label = QLabel("串口未打开")
        self.raw_view = QPlainTextEdit()
        self.parsed_view = QPlainTextEdit()
        self.connection_button = QPushButton("Connection")
        self.mode_setting_button = QPushButton("Mode Setting")
        self.channel_setting_button = QPushButton("Channel Setting")
        self.curve_setting_button = QComboBox()
        self.curve_setting_button.setPlaceholderText("Plot Options")
        self.curve_setting_button.addItems(("Coordinate Setting", "Line Setting"))
        self.curve_setting_button.setCurrentIndex(-1)
        self.scan_mode_combo = QComboBox()
        self.scan_mode_combo.addItem("扫频", 0)
        self.scan_mode_combo.addItem("定频", 1)
        self.fixed_frequency_input = QLineEdit("10000")
        self.sweep_lower_frequency_input = QLineEdit("5000")
        self.sweep_upper_frequency_input = QLineEdit("100000")
        self.sweep_step_frequency_input = QLineEdit("1000")
        self.apply_mode_button = QPushButton("Apply Mode")
        self.apply_mode_button.setEnabled(False)
        self.mode_status_label = QLabel("请先打开串口")
        self.x_key_input = QLineEdit(self.current_x_key)
        self.key_input = QLineEdit(self.current_y_key)
        self.plot_key_button = QPushButton("绘制曲线")
        self.clear_plot_button = QPushButton("清除曲线")
        self.save_data_button = QPushButton("保存数据")
        self.plot_status_label = QLabel("当前曲线：X=timestamp，Y=Freq")
        self.channel_count_input = QLineEdit("1")
        self.apply_channel_count_button = QPushButton("应用数量")
        self.apply_channels_button = QPushButton("应用 Channel")
        self.channel_status_label = QLabel("当前 Channel：0012")
        self.y_min_input = QLineEdit()
        self.y_max_input = QLineEdit()
        self.x_mode_combo = QComboBox()
        self.x_mode_combo.addItems(("Fixed", "Scaling", "Flexible"))
        self.x_mode_combo.setCurrentText("Scaling")
        self.x_min_input = QLineEdit("0")
        self.x_max_input = QLineEdit("100")
        self.x_margin_input = QLineEdit("5")
        self.visible_points_input = QLineEdit("100")
        self.apply_axis_button = QPushButton("应用坐标")
        self.apply_line_style_button = QPushButton("Apply Line Setting")
        self.axis_status_label = QLabel("纵轴自动；横轴 Scaling，右侧留白 5")
        self.plot = RealtimePlot()
        self.plot.set_channels(self.channel_ids)
        self.plot.set_title("Y=Freq / X=timestamp")
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(self.PLOT_REFRESH_INTERVAL_MS)
        self.plot_timer.timeout.connect(self.flush_plot_records)
        self.plot_timer.start()

        self._build_modular_ui()
        self._load_options()
        self.update_mode_input_state()
        self.update_axis_input_state()
        self.refresh_ports()

    def _build_legacy_ui(self):
        self.raw_view.setReadOnly(True)
        self.raw_view.setMaximumBlockCount(2000)
        self.parsed_view.setReadOnly(True)
        self.parsed_view.setMaximumBlockCount(4000)
        self.close_button.setEnabled(False)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.open_button.clicked.connect(self.open_serial)
        self.close_button.clicked.connect(self.close_serial)
        self.clear_button.clicked.connect(self.clear_data)
        self.plot_key_button.clicked.connect(self.apply_plot_key)
        self.clear_plot_button.clicked.connect(self.confirm_clear_plot)
        self.save_data_button.clicked.connect(self.save_plot_data)
        self.apply_channel_count_button.clicked.connect(self.rebuild_channel_inputs)
        self.apply_channels_button.clicked.connect(self.apply_channel_settings)
        self.key_input.returnPressed.connect(self.apply_plot_key)
        self.x_key_input.returnPressed.connect(self.apply_plot_key)
        self.apply_axis_button.clicked.connect(self.apply_axis_settings)
        self.x_mode_combo.currentTextChanged.connect(self.update_axis_input_state)

        settings_group = QGroupBox("串口设置")
        settings_layout = QGridLayout(settings_group)
        settings_layout.addWidget(QLabel("串口"), 0, 0)
        settings_layout.addWidget(self.port_combo, 0, 1)
        settings_layout.addWidget(self.refresh_button, 0, 2)
        settings_layout.addWidget(QLabel("波特率"), 1, 0)
        settings_layout.addWidget(self.baud_combo, 1, 1)
        settings_layout.addWidget(QLabel("停止位"), 2, 0)
        settings_layout.addWidget(self.stop_bits_combo, 2, 1)
        settings_layout.addWidget(QLabel("数据位"), 3, 0)
        settings_layout.addWidget(self.data_bits_combo, 3, 1)
        settings_layout.addWidget(QLabel("校验位"), 4, 0)
        settings_layout.addWidget(self.parity_combo, 4, 1)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.open_button)
        button_layout.addWidget(self.close_button)
        button_layout.addWidget(self.clear_button)
        button_layout.addStretch()
        button_layout.addWidget(self.status_label)

        raw_group = QGroupBox("串口接收原始信息")
        raw_layout = QVBoxLayout(raw_group)
        raw_layout.addWidget(self.raw_view)

        left_layout = QVBoxLayout()
        left_layout.addWidget(settings_group)
        left_layout.addLayout(button_layout)
        left_layout.addWidget(raw_group, 1)

        plot_control_group = QGroupBox("绘图控制")
        plot_control_layout = QVBoxLayout(plot_control_group)

        channel_group = QGroupBox("Channel 设置")
        channel_layout = QVBoxLayout(channel_group)
        channel_count_layout = QHBoxLayout()
        channel_count_layout.addWidget(QLabel("N_channel"))
        channel_count_layout.addWidget(self.channel_count_input)
        channel_count_layout.addWidget(self.apply_channel_count_button)
        channel_count_layout.addWidget(self.apply_channels_button)
        channel_layout.addLayout(channel_count_layout)
        self.channel_inputs_layout = QVBoxLayout()
        channel_layout.addLayout(self.channel_inputs_layout)
        channel_layout.addWidget(self.channel_status_label)
        plot_control_layout.addWidget(channel_group)
        self.rebuild_channel_inputs()

        key_layout = QGridLayout()
        key_layout.addWidget(QLabel("X 键"), 0, 0)
        key_layout.addWidget(self.x_key_input, 0, 1)
        key_layout.addWidget(QLabel("Y 键"), 1, 0)
        key_layout.addWidget(self.key_input, 1, 1)
        key_layout.addWidget(self.plot_key_button, 0, 2)
        key_layout.addWidget(self.clear_plot_button, 1, 2)
        key_layout.addWidget(self.save_data_button, 2, 2)
        key_layout.addWidget(self.plot_status_label, 2, 0, 1, 2)
        key_layout.setColumnStretch(1, 1)
        plot_control_layout.addLayout(key_layout)

        axis_group = QGroupBox("坐标轴范围")
        axis_layout = QGridLayout(axis_group)
        axis_layout.addWidget(QLabel("Y 下限"), 0, 0)
        axis_layout.addWidget(self.y_min_input, 0, 1)
        axis_layout.addWidget(QLabel("Y 上限"), 0, 2)
        axis_layout.addWidget(self.y_max_input, 0, 3)
        axis_layout.addWidget(QLabel("X 模式"), 1, 0)
        axis_layout.addWidget(self.x_mode_combo, 1, 1)
        axis_layout.addWidget(QLabel("右侧留白"), 1, 2)
        axis_layout.addWidget(self.x_margin_input, 1, 3)
        axis_layout.addWidget(QLabel("X 下限"), 2, 0)
        axis_layout.addWidget(self.x_min_input, 2, 1)
        axis_layout.addWidget(QLabel("X 上限"), 2, 2)
        axis_layout.addWidget(self.x_max_input, 2, 3)
        axis_layout.addWidget(QLabel("显示点数"), 3, 0)
        axis_layout.addWidget(self.visible_points_input, 3, 1)
        axis_layout.addWidget(self.axis_status_label, 4, 0, 1, 4)
        axis_layout.addWidget(self.apply_axis_button, 5, 0, 1, 4)
        axis_layout.setColumnStretch(1, 1)
        axis_layout.setColumnStretch(3, 1)
        plot_control_layout.addWidget(axis_group)

        parsed_group = QGroupBox("JSON 解析后的键-值对信息")
        parsed_layout = QVBoxLayout(parsed_group)
        parsed_layout.addWidget(self.parsed_view)

        right_layout = QVBoxLayout()
        right_layout.addWidget(plot_control_group)
        right_layout.addWidget(self.plot, 2)
        right_layout.addWidget(parsed_group, 3)

        main_layout = QHBoxLayout()
        main_layout.addLayout(left_layout, 2)
        main_layout.addLayout(right_layout, 3)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)

    def _build_modular_ui(self):
        self.raw_view.setReadOnly(True)
        self.raw_view.setMaximumBlockCount(2000)
        self.parsed_view.setReadOnly(True)
        self.parsed_view.setMaximumBlockCount(200)
        self.close_button.setEnabled(False)

        self.refresh_button.clicked.connect(self.refresh_ports)
        self.open_button.clicked.connect(self.open_serial)
        self.close_button.clicked.connect(self.close_serial)
        self.clear_button.clicked.connect(self.clear_data)
        self.plot_key_button.clicked.connect(self.apply_plot_key)
        self.clear_plot_button.clicked.connect(self.confirm_clear_plot)
        self.save_data_button.clicked.connect(self.save_plot_data)
        self.apply_channel_count_button.clicked.connect(self.rebuild_channel_inputs)
        self.apply_channels_button.clicked.connect(self.apply_channel_settings)
        self.key_input.returnPressed.connect(self.apply_plot_key)
        self.x_key_input.returnPressed.connect(self.apply_plot_key)
        self.apply_axis_button.clicked.connect(self.apply_axis_settings)
        self.apply_line_style_button.clicked.connect(self.apply_line_settings)
        self.x_mode_combo.currentTextChanged.connect(self.update_axis_input_state)
        self.connection_button.clicked.connect(self.show_connection_dialog)
        self.mode_setting_button.clicked.connect(self.show_mode_dialog)
        self.channel_setting_button.clicked.connect(self.show_channel_dialog)
        self.curve_setting_button.activated.connect(self.show_plot_option)
        self.scan_mode_combo.currentIndexChanged.connect(self.update_mode_input_state)
        self.apply_mode_button.clicked.connect(self.send_mode_setting)
        self.fixed_frequency_input.returnPressed.connect(self.send_mode_setting)
        self.sweep_lower_frequency_input.returnPressed.connect(self.send_mode_setting)
        self.sweep_upper_frequency_input.returnPressed.connect(self.send_mode_setting)
        self.sweep_step_frequency_input.returnPressed.connect(self.send_mode_setting)

        self.connection_dialog = QDialog(self)
        self.connection_dialog.setWindowTitle("Connection")
        self.connection_dialog.resize(520, 680)
        connection_layout = QVBoxLayout(self.connection_dialog)

        settings_group = QGroupBox("串口设置")
        settings_layout = QGridLayout(settings_group)
        settings_layout.addWidget(QLabel("串口"), 0, 0)
        settings_layout.addWidget(self.port_combo, 0, 1)
        settings_layout.addWidget(self.refresh_button, 0, 2)
        settings_layout.addWidget(QLabel("波特率"), 1, 0)
        settings_layout.addWidget(self.baud_combo, 1, 1)
        settings_layout.addWidget(QLabel("停止位"), 2, 0)
        settings_layout.addWidget(self.stop_bits_combo, 2, 1)
        settings_layout.addWidget(QLabel("数据位"), 3, 0)
        settings_layout.addWidget(self.data_bits_combo, 3, 1)
        settings_layout.addWidget(QLabel("校验位"), 4, 0)
        settings_layout.addWidget(self.parity_combo, 4, 1)

        serial_buttons = QHBoxLayout()
        serial_buttons.addWidget(self.open_button)
        serial_buttons.addWidget(self.close_button)
        serial_buttons.addWidget(self.clear_button)
        serial_buttons.addStretch()
        serial_buttons.addWidget(self.status_label)

        raw_group = QGroupBox("串口接收原始信息")
        raw_layout = QVBoxLayout(raw_group)
        raw_layout.addWidget(self.raw_view)

        connection_layout.addWidget(settings_group)
        connection_layout.addLayout(serial_buttons)
        connection_layout.addWidget(raw_group, 1)

        self.mode_dialog = QDialog(self)
        self.mode_dialog.setWindowTitle("Mode Setting")
        self.mode_dialog.resize(580, 180)
        mode_dialog_layout = QVBoxLayout(self.mode_dialog)
        mode_group = QGroupBox("Mode Setting")
        mode_layout = QGridLayout(mode_group)
        mode_layout.addWidget(QLabel("模式"), 0, 0)
        mode_layout.addWidget(self.scan_mode_combo, 0, 1)
        mode_layout.addWidget(QLabel("定频频率 (Hz)"), 0, 2)
        mode_layout.addWidget(self.fixed_frequency_input, 0, 3)
        mode_layout.addWidget(QLabel("扫频下限 (Hz)"), 1, 0)
        mode_layout.addWidget(self.sweep_lower_frequency_input, 1, 1)
        mode_layout.addWidget(QLabel("扫频上限 (Hz)"), 1, 2)
        mode_layout.addWidget(self.sweep_upper_frequency_input, 1, 3)
        mode_layout.addWidget(QLabel("扫频间隔 (Hz)"), 2, 0)
        mode_layout.addWidget(self.sweep_step_frequency_input, 2, 1)
        mode_layout.addWidget(self.apply_mode_button, 2, 2)
        mode_layout.addWidget(self.mode_status_label, 2, 3)
        mode_layout.setColumnStretch(1, 1)
        mode_layout.setColumnStretch(3, 1)
        mode_dialog_layout.addWidget(mode_group)
        mode_dialog_layout.addStretch()

        self.channel_dialog = QDialog(self)
        self.channel_dialog.setWindowTitle("Channel Setting")
        self.channel_dialog.resize(420, 260)
        channel_dialog_layout = QVBoxLayout(self.channel_dialog)
        channel_group = QGroupBox("Channel 设置")
        channel_layout = QVBoxLayout(channel_group)
        channel_count_layout = QHBoxLayout()
        channel_count_layout.addWidget(QLabel("N_channel"))
        channel_count_layout.addWidget(self.channel_count_input)
        channel_count_layout.addWidget(self.apply_channel_count_button)
        channel_count_layout.addWidget(self.apply_channels_button)
        channel_layout.addLayout(channel_count_layout)
        self.channel_inputs_layout = QVBoxLayout()
        channel_layout.addLayout(self.channel_inputs_layout)
        channel_layout.addWidget(self.channel_status_label)
        channel_dialog_layout.addWidget(channel_group)
        self.rebuild_channel_inputs()

        self.curve_dialog = QDialog(self)
        self.curve_dialog.setWindowTitle("Plot Options")
        self.curve_dialog.resize(640, 360)
        curve_dialog_layout = QVBoxLayout(self.curve_dialog)

        self.plot_option_pages = QStackedWidget()
        curve_dialog_layout.addWidget(self.plot_option_pages, 1)

        axis_page = QWidget()
        axis_page_layout = QVBoxLayout(axis_page)
        axis_group = QGroupBox("Coordinate Setting")
        axis_layout = QGridLayout(axis_group)
        axis_layout.addWidget(QLabel("Y 下限"), 0, 0)
        axis_layout.addWidget(self.y_min_input, 0, 1)
        axis_layout.addWidget(QLabel("Y 上限"), 0, 2)
        axis_layout.addWidget(self.y_max_input, 0, 3)
        axis_layout.addWidget(QLabel("X 模式"), 1, 0)
        axis_layout.addWidget(self.x_mode_combo, 1, 1)
        axis_layout.addWidget(QLabel("右侧留白"), 1, 2)
        axis_layout.addWidget(self.x_margin_input, 1, 3)
        axis_layout.addWidget(QLabel("X 下限"), 2, 0)
        axis_layout.addWidget(self.x_min_input, 2, 1)
        axis_layout.addWidget(QLabel("X 上限"), 2, 2)
        axis_layout.addWidget(self.x_max_input, 2, 3)
        axis_layout.addWidget(QLabel("显示点数"), 3, 0)
        axis_layout.addWidget(self.visible_points_input, 3, 1)
        axis_layout.addWidget(self.axis_status_label, 4, 0, 1, 4)
        axis_layout.addWidget(self.apply_axis_button, 5, 0, 1, 4)
        axis_layout.setColumnStretch(1, 1)
        axis_layout.setColumnStretch(3, 1)
        axis_page_layout.addWidget(axis_group)
        axis_page_layout.addStretch()
        self.plot_option_pages.addWidget(axis_page)

        line_page = QWidget()
        line_page_layout = QVBoxLayout(line_page)
        line_group = QGroupBox("Line Setting")
        self.line_settings_layout = QGridLayout(line_group)
        line_page_layout.addWidget(line_group)
        line_page_layout.addWidget(self.apply_line_style_button)
        line_page_layout.addStretch()
        self.plot_option_pages.addWidget(line_page)
        self.rebuild_line_setting_inputs()

        top_bar = QHBoxLayout()
        top_bar.addWidget(self.connection_button)
        top_bar.addWidget(self.mode_setting_button)
        top_bar.addWidget(self.channel_setting_button)
        top_bar.addWidget(self.curve_setting_button)
        top_bar.addStretch()

        key_row = QHBoxLayout()
        key_row.addWidget(QLabel("X 键"))
        key_row.addWidget(self.x_key_input)
        key_row.addWidget(QLabel("Y 键"))
        key_row.addWidget(self.key_input)
        key_row.addWidget(self.plot_key_button)
        key_row.addWidget(self.clear_plot_button)
        key_row.addWidget(self.save_data_button)
        key_row.setStretch(1, 1)
        key_row.setStretch(3, 1)

        parsed_group = QGroupBox("JSON 解析后的键-值对信息")
        parsed_layout = QVBoxLayout(parsed_group)
        parsed_layout.addWidget(self.parsed_view)

        main_layout = QVBoxLayout()
        main_layout.addLayout(top_bar)
        main_layout.addLayout(key_row)
        main_layout.addWidget(self.plot, 7)
        main_layout.addWidget(parsed_group, 2)

        central = QWidget()
        central.setLayout(main_layout)
        self.setCentralWidget(central)
        self._refresh_parsed_view()

    def update_mode_input_state(self):
        is_fixed = self.scan_mode_combo.currentData() == 1
        self.fixed_frequency_input.setEnabled(is_fixed)
        self.sweep_lower_frequency_input.setEnabled(not is_fixed)
        self.sweep_upper_frequency_input.setEnabled(not is_fixed)
        self.sweep_step_frequency_input.setEnabled(not is_fixed)

    def send_mode_setting(self):
        if not self.serial.isOpen():
            QMessageBox.warning(self, "串口未打开", "请先打开串口，再发送 Mode Setting。")
            return

        payload = self._mode_setting_payload()
        if payload is None:
            return

        command = f"{payload}\n".encode("utf-8")
        bytes_written = self.serial.write(command)
        if bytes_written == -1:
            QMessageBox.critical(self, "发送失败", self.serial.errorString())
            return

        self.serial.flush()
        self.mode_status_label.setText(f"已发送：{payload}")
        self.raw_view.appendPlainText(f"\n[TX] {payload}")

        if bytes_written != len(command):
            QMessageBox.warning(self, "发送未完成", f"仅写入 {bytes_written}/{len(command)} 字节。")

    def _mode_setting_payload(self):
        mode = self.scan_mode_combo.currentData()
        if mode == 1:
            frequency = self._parse_required_frequency_hz(self.fixed_frequency_input, "定频频率")
            if frequency is None:
                return None
            return f"1,{self._format_protocol_frequency(frequency)}"

        lower = self._parse_required_frequency_hz(self.sweep_lower_frequency_input, "扫频下限")
        upper = self._parse_required_frequency_hz(self.sweep_upper_frequency_input, "扫频上限")
        step = self._parse_required_frequency_hz(self.sweep_step_frequency_input, "扫频间隔")
        if lower is None or upper is None or step is None:
            return None
        if lower >= upper:
            QMessageBox.warning(self, "Mode Setting 错误", "扫频下限必须小于扫频上限。")
            return None

        return (
            f"0,{self._format_protocol_frequency(lower)},"
            f"{self._format_protocol_frequency(upper)},"
            f"{self._format_protocol_frequency(step)}"
        )

    @staticmethod
    def _parse_required_frequency_hz(input_widget, name):
        text = input_widget.text().strip()
        if not text:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 不能为空。")
            return None
        try:
            value = Decimal(text)
        except InvalidOperation:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 必须是数字。")
            return None
        if value <= 0:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 必须大于 0。")
            return None
        return value

    @staticmethod
    def _format_protocol_frequency(frequency_hz):
        return SerialWindow._format_csv_number(frequency_hz / Decimal("1000"))

    def show_connection_dialog(self):
        self._show_dialog(self.connection_dialog)

    def show_mode_dialog(self):
        self._show_dialog(self.mode_dialog)

    def show_channel_dialog(self):
        self._show_dialog(self.channel_dialog)

    def show_plot_option(self, index):
        if index < 0 or self.curve_dialog is None or self.plot_option_pages is None:
            return

        option_name = self.curve_setting_button.itemText(index)
        self.plot_option_pages.setCurrentIndex(index)
        self.curve_dialog.setWindowTitle(option_name)
        self._show_dialog(self.curve_dialog)
        self.curve_setting_button.setCurrentIndex(-1)

    @staticmethod
    def _show_dialog(dialog):
        if dialog is None:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _load_options(self):
        for baud in (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600):
            self.baud_combo.addItem(str(baud), baud)
        self.baud_combo.setCurrentText("115200")

        self.stop_bits_combo.addItem("1", QSerialPort.StopBits.OneStop)
        self.stop_bits_combo.addItem("1.5", QSerialPort.StopBits.OneAndHalfStop)
        self.stop_bits_combo.addItem("2", QSerialPort.StopBits.TwoStop)

        self.data_bits_combo.addItem("8", QSerialPort.DataBits.Data8)
        self.data_bits_combo.addItem("7", QSerialPort.DataBits.Data7)

        self.parity_combo.addItem("None", QSerialPort.Parity.NoParity)
        self.parity_combo.addItem("Odd", QSerialPort.Parity.OddParity)
        self.parity_combo.addItem("Even", QSerialPort.Parity.EvenParity)

    def rebuild_channel_inputs(self):
        count = self._parse_required_int(self.channel_count_input, "N_channel")
        if count is None:
            return
        if count < 1:
            QMessageBox.warning(self, "Channel 设置错误", "N_channel 必须大于等于 1。")
            return

        existing_ids = [input_widget.text().strip() for input_widget in self.channel_id_inputs]
        if not existing_ids:
            existing_ids = self.channel_ids[:]

        self._clear_layout(self.channel_inputs_layout)
        self.channel_id_inputs = []
        for index in range(count):
            input_widget = QLineEdit()
            if index < len(existing_ids) and existing_ids[index]:
                input_widget.setText(existing_ids[index])
            elif index == 0:
                input_widget.setText("0012")
            else:
                input_widget.setPlaceholderText(f"Channel {index + 1} ID")

            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(f"Channel {index + 1} ID"))
            row_layout.addWidget(input_widget)
            self.channel_inputs_layout.addLayout(row_layout)
            self.channel_id_inputs.append(input_widget)

    def apply_channel_settings(self):
        channel_ids = self._read_channel_ids_from_inputs()
        if channel_ids is None:
            return

        self.channel_ids = channel_ids
        self.plot.set_channels(self.channel_ids)
        self.rebuild_line_setting_inputs()
        self._reset_timestamp_counters()
        self.channel_status_label.setText(f"当前 Channel：{', '.join(self.channel_ids)}")
        self._refresh_parsed_view()
        self.apply_plot_key()

    def _read_channel_ids_from_inputs(self):
        channel_ids = []
        for index, input_widget in enumerate(self.channel_id_inputs, start=1):
            channel_id = input_widget.text().strip()
            if not channel_id:
                QMessageBox.warning(self, "Channel 设置错误", f"Channel {index} ID 不能为空。")
                return None
            if channel_id in channel_ids:
                QMessageBox.warning(self, "Channel 设置错误", f"Channel ID 重复：{channel_id}")
                return None
            channel_ids.append(channel_id)
        return channel_ids

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def rebuild_line_setting_inputs(self):
        if self.line_settings_layout is None:
            return

        self._clear_layout(self.line_settings_layout)
        self.line_style_inputs = {}
        headers = ("Channel", "Color", "Line Type", "Width")
        for column, header in enumerate(headers):
            self.line_settings_layout.addWidget(QLabel(header), 0, column)

        for row, channel_id in enumerate(self.channel_ids, start=1):
            style = self.plot.channel_style(channel_id, row - 1)
            color_combo = QComboBox()
            for color_name, color_value in self.LINE_COLORS:
                color_combo.addItem(f"{color_name} ({color_value})", color_value)
            self._set_combo_current_data(color_combo, style["color"])

            line_style_combo = QComboBox()
            for style_name, line_style in self.LINE_STYLES:
                line_style_combo.addItem(style_name, line_style)
            self._set_combo_current_data(line_style_combo, style["line_style"])

            width_combo = QComboBox()
            for width in self.LINE_WIDTHS:
                width_combo.addItem(str(width), width)
            self._set_combo_current_data(width_combo, style["width"])

            self.line_settings_layout.addWidget(QLabel(f"ID={channel_id}"), row, 0)
            self.line_settings_layout.addWidget(color_combo, row, 1)
            self.line_settings_layout.addWidget(line_style_combo, row, 2)
            self.line_settings_layout.addWidget(width_combo, row, 3)
            self.line_style_inputs[channel_id] = {
                "color": color_combo,
                "line_style": line_style_combo,
                "width": width_combo,
            }

        self.line_settings_layout.setColumnStretch(1, 1)
        self.line_settings_layout.setColumnStretch(2, 1)

    @staticmethod
    def _set_combo_current_data(combo, target_data):
        for index in range(combo.count()):
            if combo.itemData(index) == target_data:
                combo.setCurrentIndex(index)
                return

    def apply_line_settings(self):
        for channel_id, inputs in self.line_style_inputs.items():
            self.plot.set_channel_style(
                channel_id,
                color=inputs["color"].currentData(),
                line_style=inputs["line_style"].currentData(),
                width=inputs["width"].currentData(),
            )
        self.plot_status_label.setText("Line Setting 已应用，曲线和图例已同步更新")

    def update_axis_input_state(self, *_):
        mode = self.x_mode_combo.currentText()
        is_fixed = mode == "Fixed"
        is_flexible = mode == "Flexible"

        self.x_min_input.setEnabled(is_fixed)
        self.x_max_input.setEnabled(is_fixed)
        self.x_margin_input.setEnabled(not is_fixed)
        self.visible_points_input.setEnabled(is_flexible)

    def apply_axis_settings(self):
        y_min = self._parse_optional_float(self.y_min_input, "Y 下限")
        if y_min is False:
            return
        y_max = self._parse_optional_float(self.y_max_input, "Y 上限")
        if y_max is False:
            return
        if (y_min is None) != (y_max is None):
            QMessageBox.warning(self, "坐标设置错误", "Y 下限和 Y 上限需要同时填写，或同时留空使用自动范围。")
            return
        if y_min is not None and y_min >= y_max:
            QMessageBox.warning(self, "坐标设置错误", "Y 下限必须小于 Y 上限。")
            return

        mode = self.x_mode_combo.currentText()
        x_min = 0.0
        x_max = 100.0
        x_margin = 5.0
        visible_points = 100

        if mode == "Fixed":
            x_min = self._parse_required_float(self.x_min_input, "X 下限")
            if x_min is None:
                return
            x_max = self._parse_required_float(self.x_max_input, "X 上限")
            if x_max is None:
                return
            if x_min >= x_max:
                QMessageBox.warning(self, "坐标设置错误", "Fixed 模式下 X 下限必须小于 X 上限。")
                return
        else:
            x_margin = self._parse_optional_float(self.x_margin_input, "右侧留白", default=5.0)
            if x_margin is False:
                return
            if x_margin <= 0:
                QMessageBox.warning(self, "坐标设置错误", "右侧留白必须大于 0。")
                return

            if mode == "Flexible":
                visible_points = self._parse_required_int(self.visible_points_input, "显示点数")
                if visible_points is None:
                    return
                if visible_points < 1:
                    QMessageBox.warning(self, "坐标设置错误", "显示点数必须大于等于 1。")
                    return

        self.plot.set_axis_config(
            y_min=y_min,
            y_max=y_max,
            x_mode=mode,
            x_min=x_min,
            x_max=x_max,
            x_margin=x_margin,
            visible_points=visible_points,
        )
        self.axis_status_label.setText(self._axis_status_text(y_min, y_max, mode, x_min, x_max, x_margin, visible_points))

    @staticmethod
    def _parse_optional_float(input_widget, name, default=None):
        text = input_widget.text().strip()
        if not text:
            return default
        try:
            return float(text)
        except ValueError:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 必须是数字。")
            return False

    @staticmethod
    def _parse_required_float(input_widget, name):
        text = input_widget.text().strip()
        if not text:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 不能为空。")
            return None
        try:
            return float(text)
        except ValueError:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 必须是数字。")
            return None

    @staticmethod
    def _parse_required_int(input_widget, name):
        text = input_widget.text().strip()
        if not text:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 不能为空。")
            return None
        try:
            return int(text)
        except ValueError:
            QMessageBox.warning(input_widget, "输入错误", f"{name} 必须是整数。")
            return None

    @staticmethod
    def _axis_status_text(y_min, y_max, mode, x_min, x_max, x_margin, visible_points):
        y_text = (
            "纵轴自动"
            if y_min is None
            else f"Y=[{SerialWindow._format_csv_number(y_min)}, {SerialWindow._format_csv_number(y_max)}]"
        )
        if mode == "Fixed":
            x_text = (
                f"X Fixed=[{SerialWindow._format_csv_number(x_min)}, "
                f"{SerialWindow._format_csv_number(x_max)}]"
            )
        elif mode == "Flexible":
            x_text = (
                f"X Flexible，显示点数 {visible_points}，"
                f"右侧留白 {SerialWindow._format_csv_number(x_margin)}"
            )
        else:
            x_text = f"X Scaling，起点 0，右侧留白 {SerialWindow._format_csv_number(x_margin)}"
        return f"{y_text}；{x_text}"

    def refresh_ports(self):
        current = self.port_combo.currentData()
        self.port_combo.clear()

        for port in QSerialPortInfo.availablePorts():
            label = port.portName()
            if port.description():
                label += f" - {port.description()}"
            self.port_combo.addItem(label, port.portName())

        if self.port_combo.count() == 0:
            self.port_combo.addItem("未发现串口", None)
            self.open_button.setEnabled(False)
            self.status_label.setText("未发现可用串口")
            return

        self.open_button.setEnabled(not self.serial.isOpen())
        index = self.port_combo.findData(current)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        self.status_label.setText("串口未打开")

    def open_serial(self):
        port_name = self.port_combo.currentData()
        if not port_name:
            QMessageBox.warning(self, "无法打开串口", "请先选择一个有效串口。")
            return

        self.serial.setPortName(port_name)
        self.serial.setBaudRate(self.baud_combo.currentData())
        self.serial.setDataBits(self.data_bits_combo.currentData())
        self.serial.setParity(self.parity_combo.currentData())
        self.serial.setStopBits(self.stop_bits_combo.currentData())
        self.serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)

        if not self.serial.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            QMessageBox.critical(self, "打开串口失败", self.serial.errorString())
            return

        self._set_controls_enabled(False)
        self.open_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self.apply_mode_button.setEnabled(True)
        self.status_label.setText(f"已打开：{port_name}")
        self.raw_view.appendPlainText(f"[INFO] 已打开串口 {port_name}")

    def close_serial(self):
        if self.serial.isOpen():
            port_name = self.serial.portName()
            self.serial.close()
            self.raw_view.appendPlainText(f"\n[INFO] 已关闭串口 {port_name}")

        self._set_controls_enabled(True)
        self.open_button.setEnabled(self.port_combo.currentData() is not None)
        self.close_button.setEnabled(False)
        self.apply_mode_button.setEnabled(False)
        self.mode_status_label.setText("请先打开串口")
        self.status_label.setText("串口未打开")

    def read_serial_data(self):
        raw = bytes(self.serial.readAll())
        if not raw:
            return

        text = raw.decode("utf-8", errors="replace")
        self._append_raw_text(text)
        self.json_buffer += text
        self._consume_json_buffer()

    def _consume_json_buffer(self):
        while self.json_buffer:
            start = self.json_buffer.find("{")
            if start < 0:
                self.json_buffer = ""
                return
            if start > 0:
                self.json_buffer = self.json_buffer[start:]

            try:
                data, end = self.json_decoder.raw_decode(self.json_buffer)
            except json.JSONDecodeError as exc:
                newline_index = self._first_line_break_index(self.json_buffer)
                if newline_index >= 0 and exc.pos <= newline_index:
                    bad_line = self.json_buffer[:newline_index].strip()
                    if bad_line:
                        self._append_parsed_message(f"[解析失败] {bad_line}")
                    self.json_buffer = self.json_buffer[newline_index + 1 :]
                    continue

                if len(self.json_buffer) > self.MAX_JSON_BUFFER_CHARS:
                    self._append_parsed_message("[解析失败] JSON 缓冲区过长，已丢弃当前不完整数据")
                    self.json_buffer = ""
                return

            self.json_buffer = self.json_buffer[end:]
            self._handle_json_object(data)

    @staticmethod
    def _first_line_break_index(text):
        indexes = [index for index in (text.find("\n"), text.find("\r")) if index >= 0]
        return min(indexes) if indexes else -1

    def _handle_json_object(self, data):
        if not isinstance(data, dict):
            self._append_parsed_message(f"[忽略] 收到的 JSON 不是对象：{json.dumps(data, ensure_ascii=False)}")
            return

        channel_id = str(data.get("ID", ""))
        timestamp = self._assign_channel_timestamp(channel_id)
        record = {
            "timestamp": timestamp,
            "channel_id": channel_id,
            "data": data,
        }
        self.records.append(record)
        self._update_parsed_channel_data(data)
        self._queue_record_for_plot(record)

    def _assign_channel_timestamp(self, channel_id):
        if not self.channel_ids or channel_id not in self.channel_ids:
            return 0.0

        timestamp = self.channel_sample_counts.get(channel_id, 0)
        self.channel_sample_counts[channel_id] = timestamp + 1
        return float(timestamp)

    def _format_key_values_by_channel(self, data):
        channel_id = str(data.get("ID", "<无ID>"))
        parts = [f"ID={channel_id}"]
        for key, value in data.items():
            if key == "ID":
                continue
            parts.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
        return " | ".join(parts)

    def _update_parsed_channel_data(self, data):
        channel_id = str(data.get("ID", "<无ID>"))
        self.parsed_latest_by_channel[channel_id] = self._format_key_values_by_channel(data)
        self._refresh_parsed_view()

    def _append_parsed_message(self, message):
        self.parsed_messages.append(message)
        self._refresh_parsed_view()

    def _refresh_parsed_view(self):
        lines = []
        shown_channel_ids = set()

        for channel_id in self.channel_ids:
            shown_channel_ids.add(channel_id)
            lines.append(self.parsed_latest_by_channel.get(channel_id, f"ID={channel_id} | 等待数据"))

        extra_channel_ids = sorted(
            channel_id
            for channel_id in self.parsed_latest_by_channel
            if channel_id not in shown_channel_ids
        )
        for channel_id in extra_channel_ids:
            lines.append(self.parsed_latest_by_channel[channel_id])

        if self.parsed_messages:
            if lines:
                lines.append("")
            lines.extend(self.parsed_messages)

        self.parsed_view.setPlainText("\n".join(lines))
        self.parsed_view.moveCursor(QTextCursor.MoveOperation.End)

    def _queue_record_for_plot(self, record):
        channel_id = record["channel_id"]
        if channel_id not in self.channel_ids:
            self.plot_status_label.setText(f"ID={channel_id or '<无>'} 未配置为 Channel，未绘图")
            return

        self.plot_record_queues.setdefault(channel_id, deque()).append(record)
        self.flush_plot_records()

    def flush_plot_records(self):
        if not self.channel_ids:
            return

        while all(self.plot_record_queues.get(channel_id) for channel_id in self.channel_ids):
            batch = {
                channel_id: self.plot_record_queues[channel_id].popleft()
                for channel_id in self.channel_ids
            }
            self._append_synchronized_plot_batch(batch)

    def _append_synchronized_plot_batch(self, batch):
        sample_index = self.plot_sample_index
        points, missing = self._batch_plot_values(batch, self.current_x_key, self.current_y_key, sample_index)
        self.plot_sample_index += 1

        if missing:
            self.plot_status_label.setText(f"当前曲线：{', '.join(missing)} 不是可绘制数字")
            return

        for channel_id, x_value, y_value in points:
            self.plot.add_point(channel_id, x_value, y_value)

        self.plot_status_label.setText(
            f"同步绘图：Sample={sample_index}，Channel={len(points)}，"
            f"X={self.current_x_key}，Y={self.current_y_key}"
        )

    def _batch_plot_values(self, batch, x_key, y_key, sample_index):
        points = []
        missing = []
        for channel_id in self.channel_ids:
            record = batch[channel_id]
            x_value = self._record_numeric_value(record, x_key, sample_index)
            y_value = self._record_numeric_value(record, y_key, sample_index)

            if x_value is None:
                missing.append(f"ID={channel_id} X={x_key}")
            if y_value is None:
                missing.append(f"ID={channel_id} Y={y_key}")
            points.append((channel_id, x_value, y_value))

        if missing:
            return [], missing
        return points, []

    def _record_numeric_value(self, record, key, sample_index=None):
        normalized_key = key.strip()
        if normalized_key.lower() in ("timestamp", "time"):
            if sample_index is not None:
                return float(sample_index)
            return float(record["timestamp"])

        data = record["data"]
        if normalized_key not in data or not self._is_numeric_value(data[normalized_key]):
            return None
        return float(data[normalized_key])

    @staticmethod
    def _is_numeric_value(value):
        return isinstance(value, Real) and not isinstance(value, bool)

    def apply_plot_key(self):
        x_key = self.x_key_input.text().strip() or "timestamp"
        y_key = self.key_input.text().strip()
        if not y_key:
            QMessageBox.warning(self, "键名为空", "请输入要作为 Y 轴绘图的 JSON 键名。")
            return
        channel_ids = self._read_channel_ids_from_inputs()
        if channel_ids is None:
            return

        self.channel_ids = channel_ids
        self.current_x_key = x_key
        self.current_y_key = y_key
        self.x_key_input.setText(x_key)
        self.plot.set_channels(self.channel_ids)
        self.rebuild_line_setting_inputs()
        self.plot.set_title(f"Y={y_key} / X={x_key}")
        channel_points = self._synchronized_channel_points_from_records(x_key, y_key)
        self.plot.set_channel_points(channel_points)
        self.channel_status_label.setText(f"当前 Channel：{', '.join(self.channel_ids)}")
        total_points = sum(len(points) for points in channel_points.values())
        self.plot_status_label.setText(
            f"当前曲线：X={x_key}，Y={y_key}，Channel={len(self.channel_ids)}，历史点数：{total_points}"
        )

    def _synchronized_channel_points_from_records(self, x_key, y_key):
        record_queues = {channel_id: deque() for channel_id in self.channel_ids}
        for record in self.records:
            channel_id = record["channel_id"]
            if channel_id in record_queues:
                record_queues[channel_id].append(record)

        channel_points = {channel_id: [] for channel_id in self.channel_ids}
        sample_index = 0
        while all(record_queues[channel_id] for channel_id in self.channel_ids):
            batch = {
                channel_id: record_queues[channel_id].popleft()
                for channel_id in self.channel_ids
            }
            points, missing = self._batch_plot_values(batch, x_key, y_key, sample_index)
            if not missing:
                for channel_id, x_value, y_value in points:
                    channel_points[channel_id].append((x_value, y_value))
            sample_index += 1

        self.plot_record_queues = record_queues
        self.plot_sample_index = sample_index
        return channel_points

    def _normalize_record_timestamps(self):
        channel_sample_counts = {channel_id: 0 for channel_id in self.channel_ids}
        for record in self.records:
            channel_id = record["channel_id"]
            if channel_id not in self.channel_ids:
                record["timestamp"] = 0.0
                continue

            timestamp = channel_sample_counts[channel_id]
            record["timestamp"] = float(timestamp)
            channel_sample_counts[channel_id] = timestamp + 1

        self.channel_sample_counts = channel_sample_counts

    def _reset_timestamp_counters(self):
        self.channel_sample_counts = {channel_id: 0 for channel_id in self.channel_ids}

    def confirm_clear_plot(self):
        reply = QMessageBox.question(
            self,
            "确认清除曲线",
            "是否清除图像中的当前曲线和内部绘图历史？\n原始接收信息和解析后的 JSON 信息不会被清除。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._reset_plot_history()
        self.plot_status_label.setText(f"当前曲线已清除：X={self.current_x_key}，Y={self.current_y_key}")

    def save_plot_data(self):
        self.apply_plot_key()
        points = self.plot.visible_plot_points()
        if not points:
            QMessageBox.information(self, "没有可保存的数据", "当前图像上没有可保存的曲线数据。")
            return

        default_name = f"{self.current_y_key}_vs_{self.current_x_key}.csv"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存图像数据",
            default_name,
            "CSV 文件 (*.csv)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".csv"):
            file_path += ".csv"

        try:
            with open(file_path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(
                    [self.current_x_key]
                    + [f"{channel_id}_{self.current_y_key}" for channel_id in self.channel_ids]
                )
                for x_value, y_values_by_channel in self._wide_csv_rows(points):
                    writer.writerow(
                        [self._format_csv_number(x_value)]
                        + [
                            self._format_csv_number(y_values_by_channel[channel_id])
                            if channel_id in y_values_by_channel
                            else ""
                            for channel_id in self.channel_ids
                        ]
                    )
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", f"无法保存 CSV 文件：\n{exc}")
            return

        QMessageBox.information(self, "保存成功", f"已保存 {len(points)} 个数据点：\n{file_path}")

    def _wide_csv_rows(self, points):
        rows_by_x = {}
        raw_x_by_key = {}
        for channel_id, x_value, y_value in points:
            x_key = self._format_csv_number(x_value)
            raw_x_by_key.setdefault(x_key, x_value)
            rows_by_x.setdefault(x_key, {})[channel_id] = y_value

        return [
            (raw_x_by_key[x_key], rows_by_x[x_key])
            for x_key in sorted(raw_x_by_key, key=lambda key: raw_x_by_key[key])
        ]

    @staticmethod
    def _format_csv_number(value):
        try:
            text = format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            text = str(value)

        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text if text and text != "-0" else "0"

    def _append_raw_text(self, text):
        self.raw_view.moveCursor(QTextCursor.MoveOperation.End)
        self.raw_view.insertPlainText(text)
        self.raw_view.moveCursor(QTextCursor.MoveOperation.End)

    def on_serial_error(self, error):
        if error == QSerialPort.SerialPortError.NoError:
            return

        if self.serial.isOpen():
            message = self.serial.errorString()
            self.raw_view.appendPlainText(f"\n[ERROR] 串口错误：{message}")
            QMessageBox.warning(self, "串口错误", message)
            self.close_serial()

    def clear_data(self):
        self.raw_view.clear()
        self.parsed_latest_by_channel.clear()
        self.parsed_messages.clear()
        self._refresh_parsed_view()
        self.json_buffer = ""
        self._reset_plot_history()
        self.plot_status_label.setText(f"当前曲线：X={self.current_x_key}，Y={self.current_y_key}")

    def _reset_plot_history(self):
        self.records.clear()
        self._reset_timestamp_counters()
        self.plot_record_queues = {channel_id: deque() for channel_id in self.channel_ids}
        self.plot_sample_index = 0
        self.plot.clear()

    def _set_controls_enabled(self, enabled):
        self.port_combo.setEnabled(enabled)
        self.baud_combo.setEnabled(enabled)
        self.stop_bits_combo.setEnabled(enabled)
        self.data_bits_combo.setEnabled(enabled)
        self.parity_combo.setEnabled(enabled)
        self.refresh_button.setEnabled(enabled)

    def closeEvent(self, event):
        self.close_serial()
        event.accept()
