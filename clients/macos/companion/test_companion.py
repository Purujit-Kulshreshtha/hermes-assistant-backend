import unittest

from companion import extract_after_wake_word


class WakeWordTests(unittest.TestCase):
    def test_wake_word_with_command(self):
        self.assertEqual(
            extract_after_wake_word("Nancy, create a Personal board", "Nancy"),
            (True, "create a Personal board"),
        )

    def test_wake_word_alone(self):
        self.assertEqual(extract_after_wake_word("Nancy!", "Nancy"), (True, ""))

    def test_ignores_partial_word(self):
        self.assertEqual(extract_after_wake_word("Nancys task", "Nancy"), (False, ""))


if __name__ == "__main__":
    unittest.main()
