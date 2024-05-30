import asyncio
import datetime
import os
import sys
import traceback
import winsound

import pytesseract
from pynput.keyboard import Key, Listener
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import QSettings, QThread, QUrl, pyqtSignal

from enums.increment_type import IncrementType
from enums.log_level import LogLevel
from enums.scan_mode import ScanMode
from models.game_data import GameData
from services.scanner.scanner import HSRScanner, InterruptedScanException
from ui.hsr_scanner import Ui_MainWindow
from utils.conversion import convert_to_sro
from utils.data import (
    create_debug_folder,
    executable_path,
    resource_path,
    save_to_json,
    save_to_txt,
)
from utils.window import bring_window_to_foreground, flash_window

# set environment variables for Tesseract
os.environ["TESSDATA_PREFIX"] = resource_path("assets/tesseract/tessdata")
pytesseract.pytesseract.tesseract_cmd = resource_path("assets/tesseract/tesseract.exe")


class HSRScannerUI(QtWidgets.QMainWindow, Ui_MainWindow):
    """HSRScannerUI handles the UI for the HSR Scanner application"""

    def __init__(self) -> None:
        """Constructor"""
        super().__init__()
        self._hwnd = None
        self._scanner_thread = None
        self._listener = InterruptListener()
        self._is_running = False
        self._settings = QSettings("kel-z", "HSRScanner")

        # fetch game data
        self._fetch_game_data_thread = FetchGameDataThread()
        self._fetch_game_data_thread.result_signal.connect(self.handle_game_data)
        self._fetch_game_data_thread.error_signal.connect(self.handle_game_data_error)
        self._fetch_game_data_thread.start()

    def handle_game_data(self, game_data: GameData) -> None:
        """Handle on game data loaded

        :param game_data: The game data
        """
        self.game_data = game_data
        self.log("加载的数据库版本：" + self.game_data.version)

        try:
            self.pushButtonStartScan.clicked.disconnect()
            self.pushButtonStartScanRecentRelics.clicked.disconnect()
        except Exception:
            pass

        self.pushButtonStartScan.clicked.connect(self.start_scan)
        self.pushButtonStartScan.setEnabled(True)
        self.pushButtonStartScan.setText("开始扫描")

        self.pushButtonStartScanRecentRelics.clicked.connect(
            self.start_scan_recent_relics
        )
        self.pushButtonStartScanRecentRelics.setEnabled(True)
        self.pushButtonStartScanRecentRelics.setText("扫描")

        self._fetch_game_data_thread.deleteLater()

    def handle_game_data_error(self, e: Exception) -> None:
        """Handle on game data error

        :param e: The error
        """
        self.log(
            (
                f"游戏数据加载失败：{e} （防火墙或防病毒软件可能会阻止连接。）",
                LogLevel.ERROR,
            )
        )

        try:
            self.pushButtonStartScan.clicked.disconnect()
            self.pushButtonStartScanRecentRelics.clicked.disconnect()
        except Exception:
            pass

        self.pushButtonStartScan.clicked.connect(self._fetch_game_data_thread.start)
        self.pushButtonStartScan.setEnabled(True)
        self.pushButtonStartScan.setText("Retry")

        self.pushButtonStartScanRecentRelics.clicked.connect(
            self._fetch_game_data_thread.start
        )
        self.pushButtonStartScanRecentRelics.setEnabled(True)
        self.pushButtonStartScanRecentRelics.setText("Retry")

    def setup_ui(self, MainWindow: QtWidgets.QMainWindow) -> None:
        """Sets up the UI for the application

        :param MainWindow: The main window of the application
        """
        super().setupUi(MainWindow)

        self._hwnd = MainWindow.winId().__int__()
        self.pushButtonChangeLocation.clicked.connect(self.change_output_location)
        self.pushButtonOpenLocation.clicked.connect(self.open_output_location)
        self.pushButtonRestoreDefaults.clicked.connect(self.reset_settings)

        # delete the Advanced tab for now
        self.tabWidget.removeTab(1)

        self.load_settings()

    def change_output_location(self) -> None:
        """Opens a dialog to change the output location of the scan"""
        new_output_location = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Output Location", self.lineEditOutputLocation.text()
        )
        if new_output_location:
            self.lineEditOutputLocation.setText(new_output_location)

    def open_output_location(self) -> None:
        """Opens the output location of the scan in the file explorer"""
        output_location = self.lineEditOutputLocation.text()
        if output_location:
            try:
                QtGui.QDesktopServices.openUrl(QUrl.fromLocalFile(output_location))
            except Exception as e:
                self.log((f"无法打开导出位置：{e}", LogLevel.ERROR))

    def load_settings(self) -> None:
        """Loads the settings for the scan"""
        self.lineEditOutputLocation.setText(
            self._settings.value("output_location", executable_path("StarRailData"))
        )
        self.lineEditInventoryKey.setText(
            self._settings.value("inventory_key", "b").upper()
        )
        self.lineEditCharactersKey.setText(
            self._settings.value("characters_key", "c").upper()
        )
        self.spinBoxLightConeMinLevel.setValue(
            self._settings.value("min_light_cone_level", 1)
        )
        self.spinBoxLightConeMinRarity.setValue(
            self._settings.value("min_light_cone_rarity", 3)
        )
        self.spinBoxRelicMinLevel.setValue(self._settings.value("min_relic_level", 0))
        self.spinBoxRelicMinRarity.setValue(self._settings.value("min_relic_rarity", 2))
        self.spinBoxCharacterMinLevel.setValue(
            self._settings.value("min_character_level", 1)
        )
        self.checkBoxScanLightCones.setChecked(
            self._settings.value("scan_light_cones", False) == "true"
        )
        self.checkBoxScanRelics.setChecked(
            self._settings.value("scan_relics", False) == "true"
        )
        self.checkBoxScanChars.setChecked(
            self._settings.value("scan_characters", False) == "true"
        )
        self.checkBoxSroFormat.setChecked(
            self._settings.value("sro_format", False) == "true"
        )
        self.checkBoxDebugMode.setChecked(
            self._settings.value("debug_mode", False) == "true"
        )
        self.spinBoxNavDelay.setValue(self._settings.value("nav_delay", 0))
        self.spinBoxScanDelay.setValue(self._settings.value("scan_delay", 0))
        self.spinBoxRecentRelics.setValue(self._settings.value("recent_relics_num", 5))
        self.checkBoxRecentRelicsFiveStar.setChecked(
            self._settings.value("recent_relics_five_star", False) == "true"
        )
        self.checkBoxIncludeUid.setChecked(
            self._settings.value("include_uid", False) == "true"
        )
        self.checkBoxPlaySound.setChecked(
            self._settings.value("play_sound", True) == "true"
        )

    def save_settings(self) -> None:
        """Saves the settings for the scan"""
        self._settings.setValue("output_location", self.lineEditOutputLocation.text())
        self._settings.setValue("inventory_key", self.lineEditInventoryKey.text())
        self._settings.setValue("characters_key", self.lineEditCharactersKey.text())
        self._settings.setValue(
            "min_light_cone_level", self.spinBoxLightConeMinLevel.value()
        )
        self._settings.setValue(
            "min_light_cone_rarity", self.spinBoxLightConeMinRarity.value()
        )
        self._settings.setValue("min_relic_level", self.spinBoxRelicMinLevel.value())
        self._settings.setValue("min_relic_rarity", self.spinBoxRelicMinRarity.value())
        self._settings.setValue(
            "scan_light_cones", self.checkBoxScanLightCones.isChecked()
        )
        self._settings.setValue(
            "min_character_level", self.spinBoxCharacterMinLevel.value()
        )
        self._settings.setValue("scan_relics", self.checkBoxScanRelics.isChecked())
        self._settings.setValue("scan_characters", self.checkBoxScanChars.isChecked())
        self._settings.setValue("sro_format", self.checkBoxSroFormat.isChecked())
        self._settings.setValue("debug_mode", self.checkBoxDebugMode.isChecked())
        self._settings.setValue("nav_delay", self.spinBoxNavDelay.value())
        self._settings.setValue("scan_delay", self.spinBoxScanDelay.value())
        self._settings.setValue("recent_relics_num", self.spinBoxRecentRelics.value())
        self._settings.setValue(
            "recent_relics_five_star", self.checkBoxRecentRelicsFiveStar.isChecked()
        )
        self._settings.setValue("include_uid", self.checkBoxIncludeUid.isChecked())
        self._settings.setValue("play_sound", self.checkBoxPlaySound.isChecked())

    def reset_settings(self) -> None:
        """Resets the settings for the scan"""
        self._settings.setValue("output_location", executable_path("StarRailData"))
        self._settings.setValue("inventory_key", "b")
        self._settings.setValue("characters_key", "c")
        self._settings.setValue("min_light_cone_level", 1)
        self._settings.setValue("min_light_cone_rarity", 3)
        self._settings.setValue("min_relic_level", 0)
        self._settings.setValue("min_relic_rarity", 2)
        self._settings.setValue("min_character_level", 1)
        self._settings.setValue("scan_light_cones", False)
        self._settings.setValue("scan_relics", False)
        self._settings.setValue("scan_characters", False)
        self._settings.setValue("sro_format", False)
        self._settings.setValue("nav_delay", 0)
        self._settings.setValue("scan_delay", 0)
        self._settings.setValue("recent_relics_num", 8)
        self._settings.setValue("recent_relics_five_star", True)
        self._settings.setValue("debug_mode", False)
        self._settings.setValue("include_uid", False)
        self._settings.setValue("play_sound", True)
        self.load_settings()

    def reset_fields(self) -> None:
        """Resets the fields on the UI"""
        for label in [
            self.labelLightConeCount,
            self.labelRelicCount,
            self.labelCharacterCount,
            self.labelLightConeProcessed,
            self.labelRelicProcessed,
            self.labelCharacterProcessed,
        ]:
            label.setText("0")
        self.textEditLog.clear()

    def start_scan(self) -> None:
        """Starts the scan"""
        if self._is_running:
            return
        self.save_settings()
        self.reset_fields()

        config = self.get_config()

        # initialize scanner
        try:
            if not any(
                [
                    config["scan_light_cones"],
                    config["scan_relics"],
                    config["scan_characters"],
                ]
            ):
                raise Exception("未选择扫描选项。请至少选择一项。")
            scanner = HSRScanner(config, self.game_data)
        except Exception as e:
            self.log((e, LogLevel.ERROR))
            return

        self.log("开始扫描...")

        self.to_scanner_thread(
            scanner, config["debug_output_location"] if config["debug"] else None
        )

    def start_scan_recent_relics(self) -> None:
        """Starts the scan for recent relics"""
        if self._is_running:
            return
        self.save_settings()
        self.reset_fields()
        self.tabWidget.setCurrentIndex(0)

        config = self.get_config()
        config["scan_light_cones"] = False
        config["scan_characters"] = False
        config["scan_relics"] = True
        config["filters"] = {
            "relic": {
                "min_rarity": 5 if config["recent_relics_five_star"] else 0,
            }
        }

        # initialize scanner
        try:
            if config["recent_relics_num"] < 1:
                raise Exception("At least one relic must be scanned.")
            scanner = HSRScanner(
                config, self.game_data, scan_mode=ScanMode.RECENT_RELICS.value
            )
        except Exception as e:
            self.log((e, LogLevel.ERROR))
            return

        self.log(
            f"Starting recent relics scan for {config['recent_relics_num']} relics..."
        )
        self.to_scanner_thread(
            scanner, config["debug_output_location"] if config["debug"] else None
        )

    def to_scanner_thread(
        self, scanner: HSRScanner, debug_output_location: str = None
    ) -> None:
        """Starts the scanner thread

        :param scanner: The HSRScanner class instance
        :param debug_output_location: The debug output location
        """
        self.disable_start_scan_button()

        # connect signals
        scanner.log_signal.connect(self.log)
        scanner.update_signal.connect(self.increment_progress)
        scanner.complete_signal.connect(self._listener.stop)
        scanner.complete_signal.connect(lambda: bring_window_to_foreground(self._hwnd))

        # initialize thread
        self._scanner_thread = ScannerThread(scanner)
        self._scanner_thread.log_signal.connect(self.log)

        self._scanner_thread.result_signal.connect(
            lambda data: self.handle_result(data, debug_output_location)
        )
        self._scanner_thread.result_signal.connect(self._scanner_thread.deleteLater)
        self._scanner_thread.result_signal.connect(self.enable_start_scan_button)

        self._scanner_thread.error_signal.connect(
            lambda msg: self.handle_error(msg, debug_output_location)
        )
        self._scanner_thread.error_signal.connect(self._scanner_thread.deleteLater)
        self._scanner_thread.error_signal.connect(self.enable_start_scan_button)
        self._scanner_thread.error_signal.connect(self._listener.stop)

        self._listener.interrupt_signal.connect(self._scanner_thread.interrupt_scan)

        # start thread
        self._scanner_thread.started.connect(self._listener.start)
        self._scanner_thread.start()

    def get_config(self) -> dict:
        """Gets the configuration for the scan

        Side effect: Creates a debug folder if debug mode is enabled

        :return: The configuration for the scan
        """
        # scan options
        config = {}
        config["include_uid"] = self.checkBoxIncludeUid.isChecked()
        config["scan_light_cones"] = self.checkBoxScanLightCones.isChecked()
        config["scan_relics"] = self.checkBoxScanRelics.isChecked()
        config["scan_characters"] = self.checkBoxScanChars.isChecked()

        # recent relics scan options
        config["recent_relics_num"] = self.spinBoxRecentRelics.value()
        config["recent_relics_five_star"] = (
            self.checkBoxRecentRelicsFiveStar.isChecked()
        )

        # filters
        config["filters"] = {
            "light_cone": {
                "min_level": self.spinBoxLightConeMinLevel.value(),
                "min_rarity": self.spinBoxLightConeMinRarity.value(),
            },
            "relic": {
                "min_level": self.spinBoxRelicMinLevel.value(),
                "min_rarity": self.spinBoxRelicMinRarity.value(),
            },
            "character": {
                "min_level": self.spinBoxCharacterMinLevel.value(),
            },
        }

        # hotkeys
        config["inventory_key"] = self.lineEditInventoryKey.text()
        config["characters_key"] = self.lineEditCharactersKey.text()
        if not config["inventory_key"]:
            raise Exception("Inventory key is not set.")
        if not config["characters_key"]:
            raise Exception("Characters key is not set.")

        # delays
        config["nav_delay"] = self.spinBoxNavDelay.value() / 1000
        config["scan_delay"] = self.spinBoxScanDelay.value() / 1000

        # debug mode
        config["debug"] = self.checkBoxDebugMode.isChecked()
        config["debug_output_location"] = None

        if config["debug"]:
            config["debug_output_location"] = create_debug_folder(
                self.lineEditOutputLocation.text()
            )
            self.log(
                "调试模式已启用。调试输出将保存到"
                + config["debug_output_location"]
            )

        return config

    def handle_result(self, data: dict, debug_output_location: str = None) -> None:
        """Handles the result of the scan

        :param data: The data from the scan
        :param debug_output_location: The debug output location
        """
        output_location = self.lineEditOutputLocation.text()
        file_name = (
            f"HSRScanData_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        save_to_json(data, output_location, file_name)

        if self.checkBoxSroFormat.isChecked():
            self.log("Creating accompanying export in SRO format...")
            try:
                file_name = f"HSRScanData_SRO_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                save_to_json(
                    convert_to_sro(data, self.game_data), output_location, file_name
                )
            except Exception as e:
                self.log(("Failed to convert to SRO format: " + str(e), LogLevel.ERROR))
        self.log("扫描完成。数据已保存至" + output_location)

        if debug_output_location:
            self.log(f"将日志保存到{debug_output_location}。")
            save_to_txt(
                self.textEditLog.toPlainText(), debug_output_location, "log.txt"
            )
        self.notify()

    def handle_error(self, msg: str, debug_output_location: str = None) -> None:
        """Post-scan error operations

        :param msg: The error message
        :param debug_output_location: The debug output location
        """
        self.log((msg, LogLevel.FATAL))
        if debug_output_location:
            self.log(f"将日志保存到{debug_output_location}。")
            save_to_txt(
                self.textEditLog.toPlainText(), debug_output_location, "log.txt"
            )
        self.notify()
        bring_window_to_foreground(self._hwnd)

    def notify(self) -> None:
        """Flashes the taskbar icon and plays a sound to notify the user"""

        flash_window(self._hwnd)
        if self.checkBoxPlaySound.isChecked():
            winsound.MessageBeep()

    def increment_progress(self, enum: IncrementType) -> None:
        """Increments the number on the UI based on the enum

        :param enum: The enum to increment the progress for
        """
        match IncrementType(enum):
            case IncrementType.LIGHT_CONE_ADD:
                self.labelLightConeCount.setText(
                    str(int(self.labelLightConeCount.text()) + 1)
                )
            case IncrementType.RELIC_ADD:
                self.labelRelicCount.setText(str(int(self.labelRelicCount.text()) + 1))
            case IncrementType.CHARACTER_ADD:
                self.labelCharacterCount.setText(
                    str(int(self.labelCharacterCount.text()) + 1)
                )
            case IncrementType.LIGHT_CONE_SUCCESS:
                self.labelLightConeProcessed.setText(
                    str(int(self.labelLightConeProcessed.text()) + 1)
                )
            case IncrementType.RELIC_SUCCESS:
                self.labelRelicProcessed.setText(
                    str(int(self.labelRelicProcessed.text()) + 1)
                )
            case IncrementType.CHARACTER_SUCCESS:
                self.labelCharacterProcessed.setText(
                    str(int(self.labelCharacterProcessed.text()) + 1)
                )

    def disable_start_scan_button(self) -> None:
        """Disables the start scan button and sets the text to Processing"""
        self._is_running = True

        self.pushButtonStartScan.setText("Processing...")
        self.pushButtonStartScan.setEnabled(False)

        self.pushButtonStartScanRecentRelics.setText("Processing...")
        self.pushButtonStartScanRecentRelics.setEnabled(False)

    def enable_start_scan_button(self) -> None:
        """Enables the start scan button and sets the text to Start Scan"""
        self._is_running = False

        self.pushButtonStartScan.setText("开始扫描")
        self.pushButtonStartScan.setEnabled(True)

        self.pushButtonStartScanRecentRelics.setText("Scan")
        self.pushButtonStartScanRecentRelics.setEnabled(True)

    def log(self, log: tuple[str, LogLevel] | str) -> None:
        """Logs a message to the log box

        :param log: The log message and log level
        """
        if isinstance(log, tuple):
            message, log_level = log
        else:
            message = log
            log_level = LogLevel.INFO

        self.textEditLog.appendPlainText(
            f"[{datetime.datetime.now().strftime('%H:%M:%S')}] [{log_level.value}] > {str(message)}"
        )
        self.textEditLog.verticalScrollBar().setValue(
            self.textEditLog.verticalScrollBar().maximum()
        )


class FetchGameDataThread(QThread):
    """FetchGameDataThread class handles fetching the game data in a separate thread"""

    result_signal = pyqtSignal(object)
    error_signal = pyqtSignal(object)

    def __init__(self) -> None:
        """Constructor"""
        super().__init__()

    def run(self) -> None:
        """Runs the fetch game data"""
        try:
            self.result_signal.emit(GameData())
            self.quit()
        except Exception as e:
            self.error_signal.emit(e)


class InterruptListener(QThread):
    """InterruptListener class listens for the enter key to interrupt the scan"""

    interrupt_signal = pyqtSignal()

    def __init__(self):
        """Constructor"""
        super().__init__()
        self._listener = None

    def run(self):
        """Runs the listener"""
        with Listener(on_press=self.on_press) as listener:
            self._listener = listener
            listener.join()

    def stop(self):
        """Stops the listener"""
        if self._listener:
            self._listener.stop()

    def on_press(self, key: Key) -> None:
        """Handles the key press. If the key is enter, emit the interrupt signal

        :param key: The key that was pressed
        """

        if key == Key.enter:
            self.interrupt_signal.emit()


class ScannerThread(QThread):
    """ScannerThread class handles the scanning in a separate thread"""

    result_signal = pyqtSignal(object)
    error_signal = pyqtSignal(str)
    log_signal = pyqtSignal(object)

    def __init__(self, scanner: HSRScanner) -> None:
        """Constructor

        :param scanner: The HSRScanner class instance
        """
        super().__init__()
        self._scanner = scanner
        self._interrupt_requested = False

    def run(self) -> None:
        """Runs the scan"""
        try:
            res = asyncio.run(self._scanner.start_scan())
            if self._interrupt_requested:
                self.error_signal.emit("扫描被用户取消。")
            else:
                self.result_signal.emit(res)
        except InterruptedScanException:
            self.error_signal.emit("扫描被用户取消。")
        except Exception as e:
            self.error_signal.emit(
                f'Scan aborted with error {e.__class__.__name__}: {e}\nStack trace: "{traceback.format_exc()}" (Try increasing nav/scan delay in the scanner settings, or scan with a different in-game background, window resolution, or fullscreen/windowed mode.)'
            )

    def interrupt_scan(self) -> None:
        """Interrupts the scan"""
        self._interrupt_requested = True
        self._scanner.stop_scan()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(resource_path("assets/images/app.ico")))
    MainWindow = QtWidgets.QMainWindow()
    ui = HSRScannerUI()
    ui.setup_ui(MainWindow)
    MainWindow.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
