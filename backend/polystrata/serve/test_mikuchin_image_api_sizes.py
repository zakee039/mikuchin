"""Resolution validation for provider calls and chat-image global presets.

Run: python -m serve.test_mikuchin_image_api_sizes
"""
import unittest

from serve.image_api_services import STANDARD_SIZES, LOCAL_SIZES, allowed_image_size
from serve.character_cards import CharacterStore


class ImageSizePolicyTest(unittest.TestCase):
    def test_standard_presets_are_exact_and_directional(self):
        self.assertEqual(STANDARD_SIZES, (
            (1024,1024), (1536,1536), (2048,2048), (1536,1024), (1024,1536),
            (1536,864), (2560,1440), (3840,2160), (2160,3840)))
        for width,height in STANDARD_SIZES:
            with self.subTest(width=width,height=height):
                self.assertTrue(allowed_image_size("standard",width,height))
        for width,height in [(1024,864),(864,1536),(3840,3840),(1440,2560)]:
            self.assertFalse(allowed_image_size("standard",width,height))

    def test_local_and_legacy_square(self):
        self.assertEqual(LOCAL_SIZES, (384,512,768,1024))
        self.assertTrue(allowed_image_size("all",384,1024))
        self.assertFalse(allowed_image_size("all",1536,1024))
        self.assertTrue(allowed_image_size("square",1024,1024))
        self.assertFalse(allowed_image_size("square",1024,1536))

    def test_custom_requires_16_multiple_independently(self):
        for width,height in [(1008,1504),(1536,864),(4096,4096),(256,256)]:
            self.assertTrue(allowed_image_size("custom",width,height))
        for width,height in [(1000,1504),(1008,1500),(240,256),(256,4112)]:
            self.assertFalse(allowed_image_size("custom",width,height))

    def test_chat_image_profile_uses_same_width_height_contract(self):
        base = CharacterStore.default_chat_image_settings()
        for mode,width,height in [("standard",1536,1024),("standard",2160,3840),
                                  ("custom",1008,1504),("all",512,1024)]:
            item={**base,"width":width,"height":height}
            self.assertEqual(CharacterStore.validate_chat_image_settings(
                item,{"family":"api","sizes":mode,"max_side":4096})["width"],width)
        for mode,width,height in [("standard",1008,1504),("custom",1000,1504),
                                  ("all",1536,1024)]:
            with self.assertRaises(ValueError):
                CharacterStore.validate_chat_image_settings(
                    {**base,"width":width,"height":height},
                    {"family":"api","sizes":mode,"max_side":4096})


if __name__ == "__main__":
    unittest.main()
