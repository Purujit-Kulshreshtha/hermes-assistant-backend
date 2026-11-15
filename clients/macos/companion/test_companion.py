import unittest

from companion import extract_after_wake_word, matches_stop_phrase


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

    def test_matches_natural_stop_phrase(self):
        self.assertTrue(
            matches_stop_phrase("Okay, that'll be all!", ["That'll be all"])
        )

    def test_does_not_stop_on_unrelated_speech(self):
        self.assertFalse(matches_stop_phrase("Create another task", ["That's all"]))


if __name__ == "__main__":
    unittest.main()
