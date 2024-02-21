import asyncio
import time

import pyautogui
import win32gui
from PIL import Image as PILImage
from pynput.keyboard import Key
from PyQt6.QtCore import QObject, QSettings, pyqtSignal

from config.character_scan import CHARACTER_NAV_DATA
from enums.increment_type import IncrementType
from enums.scan_mode import ScanMode
from models.game_data import GameData
from utils.data import resource_path
from utils.navigation import Navigation
from utils.ocr import image_to_string, preprocess_char_count_img, preprocess_uid_img
from utils.screenshot import Screenshot

from .parsers.character_parser import CharacterParser
from .parsers.light_cone_strategy import LightConeStrategy
from .parsers.relic_strategy import RelicStrategy

SUPPORTED_ASPECT_RATIOS = ["16:9"]


class HSRScanner(QObject):
    """HSRScanner class is responsible for scanning the game for light cones, relics, and characters"""

    update_signal = pyqtSignal(int)
    log_signal = pyqtSignal(str)
    complete_signal = pyqtSignal()

    def __init__(self, config: dict, game_data: GameData, scan_mode: int = 0):
        """Constructor

        :param config: The config dict
        :param game_data: The GameData class instance
        :raises Exception: Thrown if the game is not found
        :raises Exception: Thrown if no scan options are selected
        """
        super().__init__()
        for i, game_name in enumerate(
            [
                "Honkai: Star Rail",
                "崩坏：星穹铁道",
                "崩壞：星穹鐵道",
                "붕괴:\u00A0스타레일",
                "崩壊：スターレイル",
                "Honkai\u00A0: Star Rail",
            ]
        ):
            self._hwnd = win32gui.FindWindow("UnityWndClass", game_name)
            if self._hwnd:
                self._is_en = i == 0
                break
        if not self._hwnd:
            raise Exception(
                "Honkai: Star Rail not found. Please open the game and try again."
            )
        self._config = config
        self._game_data = game_data
        self._scan_mode = scan_mode

        self._nav = Navigation(self._hwnd)

        self._aspect_ratio = self._nav.get_aspect_ratio()
        if self._aspect_ratio not in SUPPORTED_ASPECT_RATIOS:
            raise Exception(
                f"Aspect ratio {self._aspect_ratio} not supported. Supported aspect ratios: {SUPPORTED_ASPECT_RATIOS}"
            )

        self._screenshot = Screenshot(
            self._hwnd,
            self.log_signal,
            self._aspect_ratio,
            config["debug"],
            config["debug_output_location"],
        )
        self._databank_img = PILImage.open(resource_path("assets/images/databank.png"))

        self._interrupt_event = asyncio.Event()

    async def start_scan(self) -> dict:
        """Starts the scan

        :return: The scan results
        """
        if not self._is_en:
            self.log_signal.emit(
                "WARNING: Non-English game name detected. The scanner only works with English text."
            )
        self._nav.bring_window_to_foreground()

        uid = None
        if self._config["include_uid"] and not self._interrupt_event.is_set():
            self._nav_sleep(1)
            uid_img = self._screenshot.screenshot_uid()
            uid = image_to_string(uid_img, "0123456789", 7, False, preprocess_uid_img)
            if len(uid) != 9:
                uid = image_to_string(
                    uid_img, "0123456789", 7, True, preprocess_uid_img
                )
            if len(uid) != 9:
                self.log_signal.emit(f"Failed to parse UID. Got '{uid}' instead.")
                uid = None
            else:
                self.log_signal.emit(f"UID: {uid}.")

        light_cones = []
        if self._config["scan_light_cones"] and not self._interrupt_event.is_set():
            self.log_signal.emit("Scanning light cones...")
            light_cones = self.scan_inventory(
                LightConeStrategy(
                    self._game_data,
                    self.log_signal,
                    self.update_signal,
                    self._interrupt_event,
                )
            )
            (
                self.log_signal.emit("Finished scanning light cones.")
                if not self._interrupt_event.is_set()
                else None
            )

        relics = []
        if self._config["scan_relics"] and not self._interrupt_event.is_set():
            self.log_signal.emit("Scanning relics...")
            relics = self.scan_inventory(
                RelicStrategy(
                    self._game_data,
                    self.log_signal,
                    self.update_signal,
                    self._interrupt_event,
                )
            )
            (
                self.log_signal.emit("Finished scanning relics.")
                if not self._interrupt_event.is_set()
                else None
            )

        characters = []
        if self._config["scan_characters"] and not self._interrupt_event.is_set():
            self.log_signal.emit("Scanning characters...")
            characters = self.scan_characters()
            (
                self.log_signal.emit("Finished scanning characters.")
                if not self._interrupt_event.is_set()
                else None
            )

        if self._interrupt_event.is_set():
            await asyncio.gather(*light_cones, *relics, *characters)
            return

        self.complete_signal.emit()
        self.log_signal.emit("Starting OCR process. Please wait...")

        return {
            "source": "HSR-Scanner",
            "version": 3,
            "metadata": {
                "uid": int(uid) if uid else None,
                "trailblazer": (
                    "Stelle"
                    if QSettings("kel-z", "HSR-Scanner").value("is_stelle", True)
                    == "true"
                    else "Caelus"
                ),
            },
            "light_cones": await asyncio.gather(*light_cones),
            "relics": await asyncio.gather(*relics),
            "characters": await asyncio.gather(*characters),
        }

    def stop_scan(self) -> None:
        """Stops the scan"""
        self._interrupt_event.set()

    def scan_inventory(
        self, strategy: LightConeStrategy | RelicStrategy
    ) -> set[asyncio.Task]:
        """Scans the inventory for light cones or relics

        :param strategy: The strategy to use
        :raises ValueError: Thrown if the quantity could not be parsed
        :return: The tasks to await
        """
        nav_data = strategy.NAV_DATA[self._aspect_ratio]

        # Navigate to correct tab from cellphone menu
        self._nav_sleep(1)
        self._nav.key_tap(Key.esc)
        self._nav_sleep(2)
        if self._interrupt_event.is_set():
            return []
        self._nav.key_tap(self._config["inventory_key"])
        self._nav_sleep(1.5)
        if self._interrupt_event.is_set():
            return []
        self._nav.move_cursor_to(*nav_data["inv_tab"])
        time.sleep(0.05)
        self._nav.click()
        self._nav_sleep(1.5)

        # TODO: using quantity to know when to scan the bottom row is not ideal
        #       because it will not work for tabs that do not have a quantity
        #       (i.e. materials).
        #
        #       for now, it will work for light cones and relics.
        quantity = self._screenshot.screenshot_quantity()
        quantity = image_to_string(quantity, "0123456789/", 7)

        try:
            self.log_signal.emit(f"Quantity: {quantity}.")
            quantity = quantity_remaining = int(quantity.split("/")[0])
        except ValueError:
            raise ValueError(
                "Failed to parse quantity."
                + (f' Got "{quantity}" instead.' if quantity else "")
            )

        current_sort_method = self._screenshot.screenshot_sort(strategy.SCAN_TYPE)
        current_sort_method = image_to_string(
            current_sort_method, "RarityLvDate obtained", 7
        )
        optimal_sort_method = "Date obtained"
        if self._scan_mode != ScanMode.RECENT_RELICS.value:
            optimal_sort_method = strategy.get_optimal_sort_method(
                self._config["filters"]
            )

        if optimal_sort_method != current_sort_method:
            self.log_signal.emit(
                f"Sorting by {optimal_sort_method} (was {current_sort_method})."
            )
            self._nav.move_cursor_to(*nav_data["sort"]["button"])
            time.sleep(0.05)
            self._nav.click()
            self._nav_sleep(0.5)
            self._nav.move_cursor_to(*nav_data["sort"][optimal_sort_method])
            self._nav.click()
            current_sort_method = optimal_sort_method
            self._nav_sleep(0.5)

        tasks = set()
        scanned_per_scroll = nav_data["rows"] * nav_data["cols"]
        num_times_scrolled = 0
        scanned = 0

        def should_stop():
            if self._scan_mode == ScanMode.RECENT_RELICS.value:
                return (
                    quantity_remaining <= 0
                    or scanned >= self._config["recent_relics_num"]
                )
            return quantity_remaining <= 0

        while not should_stop():
            if (
                quantity_remaining <= scanned_per_scroll
                and not quantity <= scanned_per_scroll
            ):
                x, y = nav_data["row_start_bottom"]
                todo_rows = self._ceildiv(quantity_remaining, nav_data["cols"]) - 1
                y -= todo_rows * nav_data["offset_y"]
            else:
                x, y = nav_data["row_start_top"]

            for r in range(nav_data["rows"]):
                for c in range(nav_data["cols"]):
                    if should_stop():
                        break

                    if self._interrupt_event.is_set():
                        return tasks

                    # Next item
                    self._nav.move_cursor_to(x, y)
                    time.sleep(0.05)
                    self._nav.click()
                    self._scan_sleep(0.1)
                    quantity_remaining -= 1

                    # Get stats
                    stats_dict = self._screenshot.screenshot_stats(strategy.SCAN_TYPE)
                    item_id = quantity - quantity_remaining
                    x += nav_data["offset_x"]

                    # Check if item satisfies filters
                    if "filters" in self._config:
                        filter_results, stats_dict = strategy.check_filters(
                            stats_dict,
                            self._config["filters"],
                            item_id,
                        )
                        if (
                            current_sort_method == "Lv"
                            and "min_level" in filter_results
                            and not filter_results["min_level"]
                        ):
                            quantity_remaining = 0
                            self.log_signal.emit(
                                f"Reached minimum level filter (got level {stats_dict['level']})."
                            )
                            break
                        if (
                            current_sort_method == "Rarity"
                            and "min_rarity" in filter_results
                            and not filter_results["min_rarity"]
                        ):
                            quantity_remaining = 0
                            self.log_signal.emit(
                                f"Reached minimum rarity filter (got rarity {stats_dict['rarity']})."
                            )
                            break
                        if (
                            current_sort_method == "Date obtained"
                            and "min_rarity" in filter_results
                            and filter_results["min_rarity"]
                        ):
                            scanned += 1
                        if not all(filter_results.values()):
                            continue

                    # Update UI count
                    self.update_signal.emit(strategy.SCAN_TYPE.value)

                    task = asyncio.to_thread(strategy.parse, stats_dict, item_id)
                    tasks.add(task)

                # Next row
                x = nav_data["row_start_top"][0]
                y += nav_data["offset_y"]

            if should_stop():
                break

            self._nav.scroll_page_down(num_times_scrolled)
            num_times_scrolled += 1

            self._scan_sleep(0.5)

        self._nav.key_tap(Key.esc)
        self._nav_sleep(1.5)
        self._nav.key_tap(Key.esc)
        return tasks

    def scan_characters(self) -> set[asyncio.Task]:
        """Scans the characters

        :raises ValueError: Thrown if the character count could not be parsed
        :return: The tasks to await
        """
        char_parser = CharacterParser(
            self._game_data, self.log_signal, self.update_signal, self._interrupt_event
        )
        nav_data = CHARACTER_NAV_DATA[self._aspect_ratio]

        # Assume ESC menu is open
        self._nav.bring_window_to_foreground()
        self._nav_sleep(1)
        if self._interrupt_event.is_set():
            return []

        # Locate and click databank button
        haystack = self._screenshot.screenshot_screen()
        needle = self._databank_img.resize(
            # Scale image to match capture size
            (
                int(haystack.size[0] * 0.0296875),
                int(haystack.size[1] * 0.05625),
            )
        )
        self._nav.move_cursor_to_image(haystack, needle)
        time.sleep(0.05)
        self._nav.click()
        self._nav_sleep(1)

        # Get character count
        max_retry = 5
        retry = 0
        while True:
            character_total = self._screenshot.screenshot_character_count()
            character_total = image_to_string(
                character_total, "0123456789/", 7, True, preprocess_char_count_img
            )
            try:
                self.log_signal.emit(f"Character total: {character_total}.")
                character_total = character_total.split("/")[0]
                character_count = character_total = int(character_total)
                break
            except ValueError:
                retry += 1
                if retry > max_retry:
                    raise ValueError(
                        "Failed to parse character count from Data Bank screen."
                        + (
                            f' Got "{character_total}" instead.'
                            if character_total
                            else ""
                        )
                    )
                else:
                    self.log_signal.emit(
                        f"Failed to parse character count. Retrying... ({max_retry}/5)"
                    )
                self._nav_sleep(1)

        # Update UI count
        for _ in range(character_count):
            self.update_signal.emit(IncrementType.CHARACTER_ADD.value)

        # Navigate to characters menu
        self._nav.key_tap(Key.esc)
        self._nav_sleep(1)
        if self._interrupt_event.is_set():
            return []
        self._nav.key_tap(Key.esc)
        self._nav_sleep(1.5)
        self._nav.key_tap("1")
        self._nav_sleep(0.2)
        self._nav.key_tap(self._config["characters_key"])
        self._nav_sleep(1)

        tasks = set()
        characters_seen = set()
        while character_count > 0:
            if self._interrupt_event.is_set():
                return tasks

            if character_count > nav_data["chars_per_scan"]:
                character_x, character_y = nav_data["char_start"]
            else:
                character_x, character_y = nav_data["char_end"]
                character_x -= nav_data["offset_x"] * (character_count - 1)

            i_stop = min(character_count, nav_data["chars_per_scan"])
            curr_page_res = [{} for _ in range(i_stop)]

            # Details tab
            i = 0
            self._nav.move_cursor_to(*nav_data["details_button"])
            time.sleep(0.05)
            self._nav.click()
            self._nav_sleep(0.5)
            prev_trailblazer = False  # https://github.com/kel-z/HSR-Scanner/issues/49#issuecomment-1936613741
            while i < i_stop:
                if self._interrupt_event.is_set():
                    return tasks
                self._nav.move_cursor_to(
                    character_x + i * nav_data["offset_x"], character_y
                )
                time.sleep(0.05)
                self._nav.click()
                self._scan_sleep(0.3)

                # Get ascension by counting ascension stars
                ascension_pos = nav_data["ascension_start"]
                ascension = 0
                for _ in range(6):
                    pixel = pyautogui.pixel(
                        *self._nav.translate_percent_to_coords(*ascension_pos)
                    )
                    dist = sum([(a - b) ** 2 for a, b in zip(pixel, (255, 222, 152))])
                    if dist > 100:
                        break

                    ascension += 1
                    ascension_pos = (
                        ascension_pos[0] + nav_data["ascension_offset_x"],
                        ascension_pos[1],
                    )

                character_name = ""

                max_retry = 5
                retry = 0
                while retry < max_retry and (
                    not character_name or character_name in characters_seen
                ):
                    try:
                        (self._scan_sleep(0.7) if prev_trailblazer else None)
                        character_name = (
                            # this has a small delay, can basically be treated as a sleep
                            self._get_character_name()
                        )
                        character_img = self._screenshot.screenshot_character()

                        # Trailblazer is the most prone to errors, need to ensure
                        # that all the elements have loaded before taking screenshots
                        # at the cost of small delay on Trailblazer
                        is_trailblazer = char_parser.is_trailblazer(character_img)
                        if char_parser.is_trailblazer(character_img):
                            self._scan_sleep(0.7)
                            character_name = self._get_character_name()

                        path, character_name = map(
                            str.strip, character_name.split("/")[:2]
                        )
                        character_name, path = char_parser.get_closest_name_and_path(
                            character_name, path, is_trailblazer
                        )

                        if character_name in characters_seen:
                            self.log_signal.emit(
                                f"Parsed duplicate character '{character_name}'. Retrying... ({retry + 1}/{max_retry})"
                            )
                            self._scan_sleep(1)
                    except Exception:
                        self.log_signal.emit(
                            f"Failed to parse character name. Retrying... ({retry + 1}/{max_retry})"
                        )
                        character_name = ""
                        self._scan_sleep(1)
                    retry += 1

                if not character_name:
                    self.log_signal.emit(
                        f"Failed to parse character name. Got '{character_name}' instead. Ending scan early."
                    )
                    return tasks

                if character_name in characters_seen:
                    self.log_signal.emit(
                        f"WARNING: Duplicate character '{path} / {character_name}' scanned. Continuing scan anyway."
                    )
                characters_seen.add(character_name)
                prev_trailblazer = character_name.startswith("Trailblazer")

                curr_page_res[i] = {
                    "name": character_name,
                    "ascension": ascension,
                    "path": path,
                    "level": self._screenshot.screenshot_character_level(),
                }
                i += 1

            self.log_signal.emit(
                f"Page {self._ceildiv(len(characters_seen), nav_data['chars_per_scan'])}: {', '.join([c['name'] for c in curr_page_res])}"
            )

            # Traces tab
            i = 0
            self._nav.move_cursor_to(*nav_data["traces_button"])
            time.sleep(0.05)
            self._nav.click()
            self._nav_sleep(0.4)
            while i < i_stop:
                if self._interrupt_event.is_set():
                    return tasks
                self._nav.move_cursor_to(
                    character_x + i * nav_data["offset_x"], character_y
                )
                time.sleep(0.05)
                self._nav.click()
                self._scan_sleep(0.6)
                path_key = curr_page_res[i]["path"].split(" ")[-1].lower()
                traces_dict = self._screenshot.screenshot_character_traces(path_key)
                curr_page_res[i]["traces"] = {
                    "levels": traces_dict,
                    "unlocks": {},
                }
                for k, v in nav_data["traces"][path_key].items():
                    # Trace is unlocked if pixel is white
                    pixel = pyautogui.pixel(*self._nav.translate_percent_to_coords(*v))
                    dist = min(
                        sum([(a - b) ** 2 for a, b in zip(pixel, (255, 255, 255))]),
                        sum([(a - b) ** 2 for a, b in zip(pixel, (178, 200, 255))]),
                    )
                    curr_page_res[i]["traces"]["unlocks"][k] = dist < 3000
                i += 1

            # Eidolons tab
            i = 0
            self._nav.move_cursor_to(*nav_data["eidolons_button"])
            time.sleep(0.05)
            self._nav.click()
            self._nav_sleep(1.5 if character_total == character_count else 0.9)
            while i < i_stop:
                if self._interrupt_event.is_set():
                    return tasks
                self._nav.move_cursor_to(
                    character_x + i * nav_data["offset_x"], character_y
                )
                time.sleep(0.05)
                self._nav.click()
                self._scan_sleep(0.5)
                curr_page_res[i][
                    "eidolon_images"
                ] = self._screenshot.screenshot_character_eidolons()
                i += 1

            for stats_dict in curr_page_res:
                character_count -= 1
                task = asyncio.to_thread(char_parser.parse, stats_dict)
                tasks.add(task)

            # Drag to next page
            if character_count > 0:
                character_x, character_y = nav_data["char_start"]
                character_x += nav_data["offset_x"] * nav_data["chars_per_scan"]
                self._nav.move_cursor_to(character_x, character_y)
                time.sleep(0.05)
                self._nav.click()
                time.sleep(0.05)
                self._nav.drag_scroll(
                    character_x,
                    character_y,
                    nav_data["char_start"][0] - 0.031,
                    character_y,
                )

        self._nav_sleep(1)
        self._nav.key_tap(Key.esc)
        self._nav_sleep(1.5)
        self._nav.key_tap(Key.esc)
        return tasks

    def _get_character_name(self) -> str:
        """Gets the character name

        :return: The character name
        """
        character_name_img = self._screenshot.screenshot_character_name()
        return image_to_string(
            character_name_img,
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz/7&",
            7,
        )

    def _nav_sleep(self, seconds: float) -> None:
        """Sleeps for the specified amount of time with navigation delay

        :param seconds: The amount of time to sleep
        """
        time.sleep(seconds + self._config["nav_delay"])

    def _scan_sleep(self, seconds: float) -> None:
        """Sleeps for the specified amount of time with scan delay

        :param seconds: The amount of time to sleep
        """
        time.sleep(seconds + self._config["scan_delay"])

    def _ceildiv(self, a, b) -> int:
        """Divides a by b and rounds up

        :param a: The dividend
        :param b: The divisor
        :return: The quotient
        """
        return -(a // -b)
