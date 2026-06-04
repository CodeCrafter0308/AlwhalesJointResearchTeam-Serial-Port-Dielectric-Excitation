import sys

from PyQt6.QtWidgets import QApplication

from serial_window import SerialWindow


def main():
    app = QApplication(sys.argv)
    window = SerialWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
