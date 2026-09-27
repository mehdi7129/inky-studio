import unittest

from protocol import Assembly, fragments


class ProtocolTests(unittest.TestCase):
    def test_fragmented_echo_payload_and_duplicate(self):
        source = bytes(index % 251 for index in range(600))
        parts = fragments(source, 7)
        self.assertEqual(len(parts), 50)
        parser = Assembly()
        self.assertIsNone(parser.accept(parts[0]))
        self.assertIsNone(parser.accept(parts[0]))
        for part in parts[1:-1]:
            self.assertIsNone(parser.accept(part))
        self.assertEqual(parser.accept(parts[-1]), (7, source))
        self.assertIsNone(parser.accept(parts[-1]))

    def test_rejects_missing_or_conflicting_fragment(self):
        parts = fragments(b"a" * 40, 8)
        parser = Assembly()
        with self.assertRaises(ValueError):
            parser.accept(parts[1])
        parser.accept(parts[0])
        with self.assertRaises(ValueError):
            parser.accept(parts[0][:-1] + b"b")
        with self.assertRaises(ValueError):
            parser.accept(parts[2])

    def test_rejects_bounds_and_version(self):
        with self.assertRaises(ValueError):
            fragments(b"a" * 769, 9)
        part = bytearray(fragments(b"hello", 9)[0])
        part[2] = 2
        with self.assertRaises(ValueError):
            Assembly().accept(part)

    def test_stale_partial_transaction_expires(self):
        parser = Assembly()
        parts = fragments(b"a" * 40, 10)
        parser.accept(parts[0])
        parser.started -= 16
        with self.assertRaises(ValueError):
            parser.accept(parts[1])
        self.assertIsNone(parser.accept(parts[0]))


if __name__ == "__main__":
    unittest.main()
