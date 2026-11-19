import unittest

try:
    from .image_resolution import LOCAL_SIZES, STANDARD_SIZES, allowed, nearest16
except ImportError:
    from image_resolution import LOCAL_SIZES, STANDARD_SIZES, allowed, nearest16


class NativeImageResolutionTest(unittest.TestCase):
    def test_exact_standard_sizes_and_landscape_portrait(self):
        self.assertEqual(STANDARD_SIZES, (
            (1024,1024),(2048,2048),(1536,1024),(1024,1536),
            (1536,864),(2560,1440),(3840,2160),(2160,3840)))
        self.assertTrue(all(allowed("standard",w,h) for w,h in STANDARD_SIZES))
        self.assertFalse(allowed("standard",3840,3840))
    def test_custom_and_local(self):
        self.assertEqual(LOCAL_SIZES,(384,512,768,1024))
        self.assertFalse(allowed("all",1536,1024))
        self.assertTrue(allowed("custom",1008,1504))
        self.assertFalse(allowed("custom",1000,1504))
        self.assertFalse(allowed("custom",True,1504))
        self.assertEqual(nearest16(1000),1008)
        self.assertEqual(nearest16(1025),1024)


if __name__ == "__main__":
    unittest.main()
