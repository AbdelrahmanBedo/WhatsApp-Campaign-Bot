"""Message engine — multi-template rotation, personalization, and humanization."""

from __future__ import annotations

import random
import re

from excel_handler import Contact


class MessageEngine:
    """Renders personalized, humanized messages from templates.

    Supports multiple templates (randomly selected per contact),
    placeholder substitution, greeting rotation, synonym replacement,
    punctuation variation, and light invisible variation.
    """

    GREETING_GROUPS: list[list[str]] = [
        ["Hi", "Hey", "Hello", "Hola"],
        ["Good morning", "Morning", "GM"],
        ["Good evening", "Evening"],
        ["Dear", "Hey there"],
    ]

    SYNONYM_MAP: dict[str, list[str]] = {
        "exclusive": ["special", "unique", "premium"],
        "offer": ["deal", "promotion", "opportunity"],
        "amazing": ["great", "fantastic", "wonderful"],
        "check out": ["take a look at", "have a look at", "explore"],
        "new": ["latest", "brand new", "fresh"],
        "free": ["complimentary", "no-cost", "on the house"],
        "limited": ["restricted", "exclusive", "time-sensitive"],
        "discount": ["savings", "price cut", "reduced price"],
        "today": ["right now", "this very day", "as we speak"],
        "important": ["essential", "crucial", "vital"],
    }

    def __init__(self, templates: list[str]):
        if not templates:
            raise ValueError("At least one message template is required")
        self._templates = templates

    def render(self, contact: Contact) -> str:
        """Produce a personalized, humanized message for *contact*.

        Steps:
        1. Randomly select a template
        2. Substitute placeholders
        3. Randomize greeting
        4. Apply synonym replacement (~15% per eligible word)
        5. Vary punctuation
        6. Optionally add light invisible variation
        """
        template = random.choice(self._templates)
        text = self._substitute_placeholders(template, contact)
        text = self._randomize_greeting(text)
        text = self._apply_synonym_replacement(text)
        text = self._vary_punctuation(text)
        text = self._add_light_invisible_variation(text)
        return text

    # ── Placeholder Substitution ────────────────────────────────

    @staticmethod
    def _substitute_placeholders(template: str, contact: Contact) -> str:
        """Replace ``{{field}}`` placeholders with contact data."""

        def _replacer(match: re.Match) -> str:
            key = match.group(1).strip().lower()
            if key == "name":
                return contact.name or ""
            if key == "phone_number":
                return contact.phone_number
            return contact.custom_fields.get(key, "")

        return re.sub(r"\{\{(\s*\w+\s*)\}\}", _replacer, template)

    # ── Greeting Rotation ───────────────────────────────────────

    @classmethod
    def _randomize_greeting(cls, text: str) -> str:
        """If the text starts with a known greeting, swap it randomly."""
        for group in cls.GREETING_GROUPS:
            for greeting in group:
                if text.startswith(greeting):
                    replacement = random.choice(group)
                    return replacement + text[len(greeting):]
        return text

    # ── Synonym Replacement ─────────────────────────────────────

    @classmethod
    def _apply_synonym_replacement(cls, text: str) -> str:
        """Replace known words/phrases with synonyms at ~15% probability."""
        for word, synonyms in cls.SYNONYM_MAP.items():
            if word.lower() in text.lower() and random.random() < 0.15:
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                replacement = random.choice(synonyms)
                text = pattern.sub(replacement, text, count=1)
        return text

    # ── Punctuation Variation ───────────────────────────────────

    @staticmethod
    def _vary_punctuation(text: str) -> str:
        """Randomly adjust trailing punctuation."""
        if not text:
            return text

        if text.endswith("!"):
            choice = random.random()
            if choice < 0.2:
                text = text[:-1] + "!!"
            elif choice < 0.35:
                text = text[:-1] + "."
        elif text.endswith("."):
            if random.random() < 0.15:
                text = text[:-1] + "!"

        return text

    # ── Light Invisible Variation ───────────────────────────────

    @staticmethod
    def _add_light_invisible_variation(text: str) -> str:
        """Occasionally (30% chance) insert ONE zero-width space at a random word boundary."""
        if random.random() > 0.30 or len(text) < 10:
            return text

        # Find word boundary positions (spaces)
        positions = [i for i, c in enumerate(text) if c == " "]
        if not positions:
            return text

        pos = random.choice(positions)
        return text[:pos] + "\u200b" + text[pos:]
