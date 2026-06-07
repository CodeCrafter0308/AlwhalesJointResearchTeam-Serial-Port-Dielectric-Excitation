from decimal import Decimal, InvalidOperation

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget


class RealtimePlot(QWidget):
    """Lightweight realtime line chart for multiple sensor channels."""

    COLOR_PALETTE = (
        "#0f766e",
        "#2563eb",
        "#dc2626",
        "#9333ea",
        "#ca8a04",
        "#0891b2",
        "#16a34a",
        "#ea580c",
    )
    DEFAULT_LINE_STYLE = Qt.PenStyle.SolidLine
    DEFAULT_LINE_WIDTH = 2
    TICK_FONT_POINT_SIZE = 10
    LEGEND_FONT_POINT_SIZE = 12
    LEGEND_SAMPLE_LENGTH = 42
    LEGEND_ITEM_GAP = 34

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series = {}
        self.next_sequence = {}
        self.channel_styles = {}
        self.title = "等待选择键"
        self.y_min_override = None
        self.y_max_override = None
        self.x_mode = "Scaling"
        self.x_min = 0.0
        self.x_max = 100.0
        self.x_margin = 5.0
        self.visible_points = 100
        self.setMinimumHeight(300)
        self.setAutoFillBackground(False)

    def set_title(self, title):
        self.title = title
        self.update()

    def set_channels(self, channel_ids):
        for channel_index, channel_id in enumerate(channel_ids):
            self.series.setdefault(channel_id, [])
            self.next_sequence.setdefault(channel_id, 0)
            self.channel_styles.setdefault(channel_id, self._default_channel_style(channel_index))

        allowed = set(channel_ids)
        for channel_id in list(self.series):
            if channel_id not in allowed:
                del self.series[channel_id]
                self.next_sequence.pop(channel_id, None)
                self.channel_styles.pop(channel_id, None)
        self.update()

    def set_channel_style(self, channel_id, color=None, line_style=None, width=None):
        style = self.channel_styles.setdefault(channel_id, self._default_channel_style(len(self.channel_styles)))
        if color is not None:
            style["color"] = color
        if line_style is not None:
            style["line_style"] = line_style
        if width is not None:
            style["width"] = max(1, int(width))
        self.update()

    def channel_style(self, channel_id, channel_index=0):
        return self.channel_styles.setdefault(channel_id, self._default_channel_style(channel_index)).copy()

    def add_point(self, channel_id, x_value, y_value):
        self.series.setdefault(channel_id, [])
        sequence = self.next_sequence.get(channel_id, 0)
        self.series[channel_id].append((sequence, x_value, y_value))
        self.next_sequence[channel_id] = sequence + 1
        self.update()

    def set_channel_points(self, channel_points):
        self.series.clear()
        self.next_sequence.clear()
        for channel_id, points in channel_points.items():
            self.series[channel_id] = []
            for index, (x_value, y_value) in enumerate(points):
                self.series[channel_id].append((index, x_value, y_value))
            self.next_sequence[channel_id] = len(points)
        self.update()

    def set_axis_config(
        self,
        y_min=None,
        y_max=None,
        x_mode="Scaling",
        x_min=0.0,
        x_max=100.0,
        x_margin=5.0,
        visible_points=100,
    ):
        self.y_min_override = y_min
        self.y_max_override = y_max
        self.x_mode = x_mode
        self.x_min = x_min
        self.x_max = x_max
        self.x_margin = max(0.0, x_margin)
        self.visible_points = max(1, visible_points)
        self.update()

    def clear(self):
        for points in self.series.values():
            points.clear()
        self.next_sequence = {channel_id: 0 for channel_id in self.series}
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        base_font = painter.font()
        base_font.setPointSize(self.TICK_FONT_POINT_SIZE)
        painter.setFont(base_font)

        rect = self.rect().adjusted(78, 28, -28, -54)
        painter.fillRect(self.rect(), QColor("#f7f8fa"))

        axis_pen = QPen(QColor("#8b95a1"), 1)
        grid_pen = QPen(QColor("#d9dee7"), 1, Qt.PenStyle.DotLine)
        text_pen = QPen(QColor("#374151"))

        painter.setPen(axis_pen)
        painter.drawRect(rect)

        data_by_channel = {
            channel_id: list(points)
            for channel_id, points in self.series.items()
            if points
        }
        if not data_by_channel:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "等待可绘制的数值数据")
            return

        x_min, x_max, visible_by_channel = self._x_range_and_visible_series(data_by_channel)
        y_source = [
            y
            for points in visible_by_channel.values()
            for _, _, y in points
        ] or [
            y
            for points in data_by_channel.values()
            for _, _, y in points
        ]
        y_min, y_max = self._y_range(y_source)

        self._draw_ticks(painter, rect, x_min, x_max, y_min, y_max, grid_pen, axis_pen, text_pen)

        if not any(visible_by_channel.values()):
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "当前坐标范围内无数据")
            return

        painter.save()
        painter.setClipRect(rect)
        for channel_index, (channel_id, channel_points) in enumerate(visible_by_channel.items()):
            if not channel_points:
                continue

            line_pen = self._channel_pen(channel_id, channel_index)
            painter.setPen(line_pen)
            mapped_points = [
                (
                    self._map_x(x_value, x_min, x_max, rect),
                    self._map_y(y_value, y_min, y_max, rect),
                )
                for _, x_value, y_value in channel_points
            ]

            if len(mapped_points) == 1:
                x, y = mapped_points[0]
                painter.drawEllipse(x - 3, y - 3, 6, 6)
                continue

            path = QPainterPath()
            path.moveTo(mapped_points[0][0], mapped_points[0][1])
            for x, y in mapped_points[1:]:
                path.lineTo(x, y)
            painter.drawPath(path)
        painter.restore()

        self._draw_legend(painter, rect, visible_by_channel)

    def _x_range_and_visible_series(self, data_by_channel):
        if self.x_mode == "Fixed":
            x_min = self.x_min
            x_max = self.x_max
            visible_by_channel = {
                channel_id: [point for point in points if x_min <= point[1] <= x_max]
                for channel_id, points in data_by_channel.items()
            }
        elif self.x_mode == "Flexible":
            visible_by_channel = {
                channel_id: points[-self.visible_points :]
                for channel_id, points in data_by_channel.items()
            }
            x_values = [
                x
                for points in visible_by_channel.values()
                for _, x, _ in points
            ]
            x_min = min(x_values)
            x_max = max(x_values) + self.x_margin
        else:
            x_min = 0.0
            x_max = max(
                x
                for points in data_by_channel.values()
                for _, x, _ in points
            ) + self.x_margin
            visible_by_channel = {
                channel_id: [point for point in points if x_min <= point[1] <= x_max]
                for channel_id, points in data_by_channel.items()
            }

        if x_min == x_max:
            x_max = x_min + 1.0
        return x_min, x_max, visible_by_channel

    def visible_plot_points(self):
        data_by_channel = {
            channel_id: list(points)
            for channel_id, points in self.series.items()
            if points
        }
        if not data_by_channel:
            return []

        _, _, visible_by_channel = self._x_range_and_visible_series(data_by_channel)
        rows = []
        for channel_id, points in visible_by_channel.items():
            for _, x_value, y_value in points:
                if self.y_min_override is not None and self.y_max_override is not None:
                    if not self.y_min_override <= y_value <= self.y_max_override:
                        continue
                rows.append((channel_id, x_value, y_value))
        return rows

    def _y_range(self, values):
        min_value = self.y_min_override if self.y_min_override is not None else min(values)
        max_value = self.y_max_override if self.y_max_override is not None else max(values)
        if min_value == max_value:
            min_value -= 1.0
            max_value += 1.0
        return min_value, max_value

    def _draw_ticks(self, painter, rect, x_min, x_max, y_min, y_max, grid_pen, axis_pen, text_pen):
        tick_length = 5
        for index in range(5):
            ratio = index / 4

            x = int(rect.left() + rect.width() * ratio)
            x_value = x_min + (x_max - x_min) * ratio
            painter.setPen(grid_pen)
            painter.drawLine(x, rect.top(), x, rect.bottom())
            painter.setPen(axis_pen)
            painter.drawLine(x, rect.bottom(), x, rect.bottom() + tick_length)
            painter.setPen(text_pen)
            painter.drawText(
                x - 34,
                rect.bottom() + 22,
                68,
                18,
                Qt.AlignmentFlag.AlignCenter,
                self._format_x_number(x_value),
            )

            y = int(rect.bottom() - rect.height() * ratio)
            y_value = y_min + (y_max - y_min) * ratio
            painter.setPen(grid_pen)
            painter.drawLine(rect.left(), y, rect.right(), y)
            painter.setPen(axis_pen)
            painter.drawLine(rect.left() - tick_length, y, rect.left(), y)
            painter.setPen(text_pen)
            painter.drawText(
                2,
                y - 9,
                rect.left() - 10,
                18,
                Qt.AlignmentFlag.AlignRight,
                self._format_number(y_value),
            )

        painter.setPen(axis_pen)
        painter.drawRect(rect)

    def _draw_legend(self, painter, rect, visible_by_channel):
        painter.save()
        legend_font = QFont(painter.font())
        legend_font.setPointSize(self.LEGEND_FONT_POINT_SIZE)
        legend_font.setBold(True)
        painter.setFont(legend_font)
        metrics = painter.fontMetrics()

        painter.setPen(QPen(QColor("#374151")))
        x = rect.left() + 18
        y = rect.top() + 18
        for channel_index, channel_id in enumerate(visible_by_channel):
            text = f"ID={channel_id}"
            text_width = metrics.horizontalAdvance(text)
            item_width = self.LEGEND_SAMPLE_LENGTH + 10 + text_width + self.LEGEND_ITEM_GAP
            if x + item_width > rect.right():
                break
            painter.setPen(self._channel_pen(channel_id, channel_index))
            painter.drawLine(x, y, x + self.LEGEND_SAMPLE_LENGTH, y)
            painter.setPen(QPen(QColor("#374151")))
            painter.drawText(x + self.LEGEND_SAMPLE_LENGTH + 10, y + metrics.ascent() // 2, text)
            x += item_width
        painter.restore()

    def _channel_color(self, channel_index):
        return self.COLOR_PALETTE[channel_index % len(self.COLOR_PALETTE)]

    def _default_channel_style(self, channel_index):
        return {
            "color": self._channel_color(channel_index),
            "line_style": self.DEFAULT_LINE_STYLE,
            "width": self.DEFAULT_LINE_WIDTH,
        }

    def _channel_pen(self, channel_id, channel_index):
        style = self.channel_style(channel_id, channel_index)
        pen = QPen(QColor(style["color"]), style["width"])
        pen.setStyle(style["line_style"])
        return pen

    @staticmethod
    def _format_x_number(value):
        return f"{value:.1f}"

    @staticmethod
    def _format_number(value):
        try:
            text = format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            text = str(value)

        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text if text and text != "-0" else "0"

    @staticmethod
    def _map_x(value, min_value, max_value, rect):
        ratio = (value - min_value) / (max_value - min_value)
        return int(rect.left() + ratio * rect.width())

    @staticmethod
    def _map_y(value, min_value, max_value, rect):
        ratio = (value - min_value) / (max_value - min_value)
        return int(rect.bottom() - ratio * rect.height())
