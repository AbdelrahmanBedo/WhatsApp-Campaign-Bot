"""WhatsApp Web automation via Selenium."""

from __future__ import annotations

import random
import time
from enum import Enum
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from anti_ban import AntiBanGuard
from config import DelayConfig


class SendStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    NUMBER_INVALID = "number_invalid"
    BLOCKED = "blocked"
    DISCONNECTED = "disconnected"
    TIMEOUT = "timeout"


class WhatsAppBot:
    """Controls Chrome to send messages through WhatsApp Web."""

    WHATSAPP_URL = "https://web.whatsapp.com"

    # Centralized selectors — update here when WhatsApp changes its DOM
    SEL = {
        "side_panel": (By.ID, "side"),
        "message_input": (By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]'),
        "send_button": (By.XPATH, '//span[@data-icon="send"]'),
        "attach_menu": (By.XPATH, '//div[@title="Attach"]'),
        "media_input": (By.XPATH, '//input[@accept="image/*,video/mp4,video/3gpp,video/quicktime"]'),
        "caption_input": (By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]'),
        "send_media_btn": (By.XPATH, '//span[@data-icon="send"]'),
        "msg_check": (By.XPATH, '(//span[@data-icon="msg-check" or @data-icon="msg-dblcheck"])[last()]'),
        "invalid_number": (By.XPATH, '//*[contains(text(),"Phone number shared via url is invalid")]'),
        "popup_ok": (By.XPATH, '//div[@role="button" and contains(text(),"OK")]'),
        "disconnected_banner": (By.XPATH, '//*[contains(text(),"Phone not connected")]'),
        "chat_list": (By.XPATH, '//div[@id="pane-side"]'),
        "chat_items": (By.XPATH, '//div[@id="pane-side"]//div[@role="listitem"]'),
        "search_box": (By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]'),
    }

    def __init__(
        self,
        chrome_profile: str = "",
        headless: bool = False,
        delay_config: DelayConfig | None = None,
    ):
        self._driver: webdriver.Chrome | None = None
        self._chrome_profile = chrome_profile
        self._headless = headless
        self._delay = delay_config or DelayConfig()
        self._wait: WebDriverWait | None = None

    # ── Session Management ──────────────────────────────────────

    def start_session(self) -> bool:
        """Launch Chrome, navigate to WhatsApp Web, wait for login.

        Returns ``True`` when the side panel is visible (logged in).
        """
        options = Options()
        if self._chrome_profile:
            options.add_argument(f"--user-data-dir={self._chrome_profile}")
        if self._headless:
            options.add_argument("--headless=new")

        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        # Reduce automation fingerprint
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument("--disable-blink-features=AutomationControlled")

        try:
            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)
            # Remove webdriver flag
            self._driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
            )
            self._driver.get(self.WHATSAPP_URL)
            self._wait = WebDriverWait(self._driver, 120)

            print("\nWaiting for WhatsApp Web login...")
            print("Scan the QR code if prompted (timeout: 120s).\n")

            self._wait.until(EC.presence_of_element_located(self.SEL["side_panel"]))
            print("WhatsApp Web session active.\n")
            return True

        except TimeoutException:
            print("\nLogin timed out. Please scan the QR code faster.")
            return False
        except WebDriverException as exc:
            print(f"\nFailed to start Chrome: {exc}")
            return False

    def is_connected(self) -> bool:
        """Check if WhatsApp Web is still connected."""
        if not self._driver:
            return False
        try:
            self._driver.find_element(*self.SEL["side_panel"])
            # Check for disconnection banner
            try:
                self._driver.find_element(*self.SEL["disconnected_banner"])
                return False
            except NoSuchElementException:
                return True
        except (NoSuchElementException, WebDriverException):
            return False

    def close(self) -> None:
        """Quit the driver safely."""
        if self._driver:
            try:
                self._driver.quit()
            except WebDriverException:
                pass
            self._driver = None

    # ── Sending Messages ────────────────────────────────────────

    def send_message(self, phone: str, message: str) -> SendStatus:
        """Send a text message to *phone* via the URL scheme."""
        if not self._driver:
            return SendStatus.DISCONNECTED

        if not self._navigate_to_chat(phone):
            return SendStatus.NUMBER_INVALID

        try:
            # Wait for message input
            msg_box = WebDriverWait(self._driver, 15).until(
                EC.presence_of_element_located(self.SEL["message_input"])
            )

            # Type with simulation
            self._type_with_simulation(msg_box, message)

            # Press Enter to send (more reliable than clicking the send button)
            time.sleep(random.uniform(0.3, 0.8))
            msg_box = self._driver.find_element(*self.SEL["message_input"])
            msg_box.send_keys(Keys.ENTER)

            # Verify delivery
            if self._wait_for_delivery():
                return SendStatus.SUCCESS
            else:
                if self._detect_block():
                    return SendStatus.BLOCKED
                return SendStatus.FAILED

        except TimeoutException:
            return SendStatus.TIMEOUT
        except WebDriverException:
            if not self.is_connected():
                return SendStatus.DISCONNECTED
            return SendStatus.FAILED

    def send_media(self, phone: str, media_path: str, caption: str = "") -> SendStatus:
        """Send an image/video with optional caption."""
        if not self._driver:
            return SendStatus.DISCONNECTED

        if not self._navigate_to_chat(phone):
            return SendStatus.NUMBER_INVALID

        try:
            # Click the attach button
            attach_btn = WebDriverWait(self._driver, 10).until(
                EC.element_to_be_clickable(self.SEL["attach_menu"])
            )
            attach_btn.click()
            time.sleep(random.uniform(0.5, 1.0))

            # Upload file via hidden input
            file_input = self._driver.find_element(
                By.XPATH, '//input[@type="file"]'
            )
            file_input.send_keys(str(Path(media_path).resolve()))
            time.sleep(random.uniform(1.5, 3.0))

            # Type caption if provided
            if caption:
                try:
                    caption_box = WebDriverWait(self._driver, 10).until(
                        EC.presence_of_element_located(
                            (By.XPATH, '//div[@contenteditable="true"][@role="textbox"]')
                        )
                    )
                    self._type_with_simulation(caption_box, caption)
                except TimeoutException:
                    pass

            # Press Enter to send media
            time.sleep(random.uniform(0.3, 0.8))
            ActionChains(self._driver).send_keys(Keys.ENTER).perform()

            if self._wait_for_delivery(timeout=30):
                return SendStatus.SUCCESS
            return SendStatus.FAILED

        except TimeoutException:
            return SendStatus.TIMEOUT
        except WebDriverException:
            if not self.is_connected():
                return SendStatus.DISCONNECTED
            return SendStatus.FAILED

    # ── Behavior Simulation ─────────────────────────────────────

    def perform_idle_action(self) -> None:
        """Perform a random idle action to simulate human behavior."""
        if not self._driver:
            return

        actions = [
            self._idle_scroll_chats,
            self._idle_click_random_chat,
        ]
        action = random.choice(actions)
        try:
            action()
        except WebDriverException:
            pass

    def _idle_scroll_chats(self) -> None:
        """Scroll the chat list up and down randomly."""
        try:
            chat_list = self._driver.find_element(*self.SEL["chat_list"])
            action = ActionChains(self._driver)
            scroll_amount = random.randint(200, 600)
            direction = random.choice([-1, 1])
            action.move_to_element(chat_list).scroll_by_amount(0, scroll_amount * direction).perform()
            time.sleep(random.uniform(0.5, 2.0))
            # Scroll back
            action.scroll_by_amount(0, -scroll_amount * direction).perform()
            time.sleep(random.uniform(0.3, 1.0))
        except WebDriverException:
            pass

    def _idle_click_random_chat(self) -> None:
        """Open a random chat briefly and go back."""
        try:
            chats = self._driver.find_elements(*self.SEL["chat_items"])
            if len(chats) > 2:
                chat = random.choice(chats[:5])
                chat.click()
                time.sleep(random.uniform(1.0, 3.0))
                # Navigate back to main view
                self._driver.get(self.WHATSAPP_URL)
                time.sleep(random.uniform(1.0, 2.0))
        except WebDriverException:
            pass

    # ── Internal Helpers ────────────────────────────────────────

    def _navigate_to_chat(self, phone: str) -> bool:
        """Navigate to a chat via the URL scheme.

        Returns ``True`` if the chat opened successfully.
        """
        # Clean phone for URL (digits only, no +)
        clean_phone = phone.lstrip("+")
        url = f"{self.WHATSAPP_URL}/send?phone={clean_phone}"

        try:
            self._driver.get(url)
            time.sleep(random.uniform(2.0, 4.0))

            # Check for invalid number popup
            try:
                self._driver.find_element(*self.SEL["invalid_number"])
                # Try to close the popup
                try:
                    ok_btn = self._driver.find_element(*self.SEL["popup_ok"])
                    ok_btn.click()
                except NoSuchElementException:
                    pass
                return False
            except NoSuchElementException:
                pass  # No error popup = number is valid

            # Wait for the message input to be ready
            WebDriverWait(self._driver, 15).until(
                EC.presence_of_element_located(self.SEL["message_input"])
            )
            return True

        except TimeoutException:
            return False
        except WebDriverException:
            return False

    def _type_with_simulation(self, element, text: str) -> None:
        """Type text character by character with human-like delays."""
        actions = ActionChains(self._driver)
        element.click()
        time.sleep(random.uniform(0.2, 0.5))

        for char in text:
            if char == "\n":
                actions.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT).perform()
            else:
                actions.send_keys(char).perform()

            delay = self._get_typing_delay(char)
            time.sleep(delay)

        actions.reset_actions()

    def _get_typing_delay(self, char: str) -> float:
        """Per-character delay with variation by character type."""
        base = random.uniform(
            self._delay.typing_char_delay_min,
            self._delay.typing_char_delay_max,
        )
        if char == " ":
            base *= 1.5
        elif char in ".,!?:;":
            base *= 2.0
        elif char == "\n":
            base *= 3.0

        if random.random() < self._delay.typing_pause_probability:
            base += random.uniform(
                self._delay.typing_pause_duration_min,
                self._delay.typing_pause_duration_max,
            )
        return base

    def _wait_for_delivery(self, timeout: int = 15) -> bool:
        """Wait for the message delivery tick."""
        try:
            WebDriverWait(self._driver, timeout).until(
                EC.presence_of_element_located(self.SEL["msg_check"])
            )
            return True
        except TimeoutException:
            return False

    def _detect_block(self) -> bool:
        """Check for indicators that sending is blocked."""
        if not self._driver:
            return False

        block_indicators = [
            '//*[contains(text(),"could not be sent")]',
            '//*[contains(text(),"blocked")]',
            '//*[contains(text(),"restricted")]',
            '//*[contains(text(),"temporarily banned")]',
        ]
        for xpath in block_indicators:
            try:
                self._driver.find_element(By.XPATH, xpath)
                return True
            except NoSuchElementException:
                continue
        return False
