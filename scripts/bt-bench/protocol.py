"""Non-secret diagnostic framing only. This is NOT an authentication protocol."""

import struct
import time

SERVICE_UUID = "713a0001-8890-4cc9-a2bf-26f32c43db22"
VERSION_UUID = "713a0002-8890-4cc9-a2bf-26f32c43db22"
RX_UUID = "713a0003-8890-4cc9-a2bf-26f32c43db22"
TX_UUID = "713a0004-8890-4cc9-a2bf-26f32c43db22"
VERSION_VALUE = b"INKY-BENCH/1"
HEADER = struct.Struct("!2sBBHBB")
MAX_PAYLOAD = 768
MAX_FRAGMENTS = 64


def fragments(payload, transaction, frame_size=20):
    if not payload or len(payload) > MAX_PAYLOAD or not 9 <= frame_size <= 512:
        raise ValueError("Invalid payload or frame size")
    chunk_size = frame_size - HEADER.size
    count = (len(payload) + chunk_size - 1) // chunk_size
    if count > MAX_FRAGMENTS:
        raise ValueError("Too many fragments")
    return [HEADER.pack(b"IK", 1, 0, transaction, index, count)
            + payload[index * chunk_size:(index + 1) * chunk_size]
            for index in range(count)]


class Assembly:
    """One bounded in-order transaction; matching retransmissions are harmless."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.transaction = None
        self.count = 0
        self.parts = []
        self.started = 0

    def accept(self, value):
        if len(value) <= HEADER.size or len(value) > 512:
            raise ValueError("Invalid frame length")
        magic, version, flags, transaction, index, count = HEADER.unpack(value[:HEADER.size])
        if magic != b"IK" or version != 1 or flags != 0 or not 1 <= count <= MAX_FRAGMENTS or index >= count:
            raise ValueError("Invalid header")
        now = time.monotonic()
        if self.transaction is not None and now - self.started > 15:
            self.reset()
        if self.transaction != transaction:
            if index != 0:
                raise ValueError("Missing first fragment")
            self.reset()
            self.transaction, self.count, self.started = transaction, count, now
        if count != self.count:
            raise ValueError("Fragment count changed")
        body = value[HEADER.size:]
        if index < len(self.parts):
            if self.parts[index] != body:
                raise ValueError("Conflicting duplicate")
            return None
        if index != len(self.parts):
            raise ValueError("Out-of-order fragment")
        if sum(map(len, self.parts)) + len(body) > MAX_PAYLOAD:
            raise ValueError("Payload limit")
        self.parts.append(body)
        if len(self.parts) == count:
            return transaction, b"".join(self.parts)
        return None
