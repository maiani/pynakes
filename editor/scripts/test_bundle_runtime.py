"""Offline packaging checks, run with python -m unittest discover -s scripts."""

import unittest

from packaging.tags import Tag
from pynakes_launcher import select_variant


class NativeSelectionTests(unittest.TestCase):
    def test_selects_platform_and_abi_together(self):
        variants = [
            {"wheel": "pydantic_core-2.50.4-cp312-cp312-win_amd64.whl", "path": "windows"},
            {
                "wheel": "pydantic_core-2.50.4-cp313-cp313-manylinux2014_x86_64.whl",
                "path": "wrong-python",
            },
            {
                "wheel": "pydantic_core-2.50.4-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl",
                "path": "linux",
            },
        ]
        self.assertEqual(
            select_variant(variants, [Tag("cp312", "cp312", "manylinux_2_17_x86_64")]), "linux"
        )
        self.assertIsNone(
            select_variant(variants, [Tag("cp312", "cp312t", "manylinux_2_17_x86_64")])
        )
        self.assertIsNone(select_variant(variants, [Tag("cp312", "cp312", "musllinux_1_2_x86_64")]))

    def test_prefers_interpreter_tag_order(self):
        variants = [
            {"wheel": "pydantic_core-2.50.4-cp312-cp312-macosx_10_12_x86_64.whl", "path": "older"},
            {"wheel": "pydantic_core-2.50.4-cp312-cp312-macosx_11_0_x86_64.whl", "path": "newer"},
        ]
        self.assertEqual(
            select_variant(
                variants,
                [
                    Tag("cp312", "cp312", "macosx_11_0_x86_64"),
                    Tag("cp312", "cp312", "macosx_10_12_x86_64"),
                ],
            ),
            "newer",
        )


if __name__ == "__main__":
    unittest.main()
