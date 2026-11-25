# -*- coding: utf-8 -*-
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from novelcast.pronunciation import annotate_word, apply_pronunciation  # noqa: E402


class PronunciationTest(unittest.TestCase):
    def test_annotate_word_per_char(self):
        self.assertEqual(annotate_word("重庆", "CHONG2 QING4"), "<重|CHONG2><庆|QING4>")

    def test_annotate_single(self):
        self.assertEqual(annotate_word("行", "XING2"), "<行|XING2>")

    def test_apply_longest_first(self):
        text = "他走在重庆的夜里"
        out = apply_pronunciation(text, {"重庆": "CHONG2 QING4", "重": "ZHONG4"})
        self.assertEqual(out, "他走在<重|CHONG2><庆|QING4>的夜里")

    def test_apply_keeps_existing_annotation(self):
        text = "<重|CHONG2>庆"
        out = apply_pronunciation(text, {"重庆": "CHONG2 QING4"})
        self.assertIn("<重|CHONG2>", out)

    def test_empty_mapping_noop(self):
        self.assertEqual(apply_pronunciation("重庆", {}), "重庆")

    def test_builtin_polyphone_table(self):
        from novelcast.pronunciation import load_mapping

        words = load_mapping()
        self.assertEqual(words.get("银行"), "YIN2 HANG2")
        self.assertEqual(words.get("重担"), "ZHONG4 DAN4")
        self.assertEqual(words.get("扒手"), "PA2 SHOU3")
        out = apply_pronunciation("他去银行取钱")
        self.assertIn("<银|YIN2><行|HANG2>", out)

    def test_neutral_words_not_annotated(self):
        from novelcast.pronunciation import load_mapping

        words = load_mapping()
        for w in ("什么", "那个", "这个", "意思", "时候"):
            self.assertNotIn(w, words)
        self.assertEqual(apply_pronunciation("你什么意思"), "你什么意思")
        self.assertEqual(apply_pronunciation("切，拽什么拽啊"), "切，拽什么拽啊")


if __name__ == "__main__":
    unittest.main()
