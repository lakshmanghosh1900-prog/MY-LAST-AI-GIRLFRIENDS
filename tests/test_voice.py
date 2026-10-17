from __future__ import annotations

import unittest

from my_last_ai_girlfriends.voice import VoiceError, normalize_transcript, unsupported_voice_capability


class VoiceTests(unittest.TestCase):
    def test_transcript_is_normalized_and_bounded(self):
        self.assertEqual(normalize_transcript("  hello\n world "), "hello world")
        self.assertEqual(len(normalize_transcript("x" * 20000)), 12000)

    def test_empty_transcript_and_unsupported_capability_are_truthful(self):
        with self.assertRaisesRegex(VoiceError, "transcript"):
            normalize_transcript(" ")
        capability = unsupported_voice_capability()
        self.assertFalse(capability.input_supported)
        self.assertFalse(capability.output_supported)
        self.assertEqual(capability.provider, "none")


if __name__ == "__main__":
    unittest.main()
