"""Phase 7 — pi's length-prefixed CBOR framing.

The encoder is checked byte-for-byte against pi's own TypeScript
implementation (see `test_matches_pi_byte_for_byte`); the rest of the file is
about the failure mode a hand-rolled reader always has, which is assuming one
read is one frame.
"""

from __future__ import annotations

import binascii
import struct

import cbor2
import pytest

from agent.integration.pi_framing import (
    DEFAULT_MAX_FRAME_LENGTH,
    HEADER_LENGTH,
    FrameDecoder,
    FrameError,
    decode_messages,
    encode_frame,
    encode_message,
)

#: Produced by pi itself:
#:
#:     import { encodeCbor } from "packages/protocol/src/cbor/index.ts";
#:     import { encodeFrame } from "packages/protocol/src/framing.ts";
#:     encodeFrame(encodeCbor({ type: "hello", version: 1 }))
#:
#: Pinned rather than recomputed, so a change on either side shows up here
#: instead of in a silent handshake failure against a real pi.
PI_HELLO_FRAME = binascii.unhexlify(
    "00000015a264747970656568656c6c6f6776657273696f6e01"
)


class TestAgreementWithPi:

    def test_matches_pi_byte_for_byte(self):
        assert encode_message({"type": "hello", "version": 1}) == PI_HELLO_FRAME

    def test_pis_own_frame_decodes(self):
        decoder = FrameDecoder()
        assert decode_messages(decoder, PI_HELLO_FRAME) == [
            {"type": "hello", "version": 1}
        ]

    def test_the_prefix_is_four_bytes_big_endian(self):
        frame = encode_frame(b"abc")
        assert frame[:HEADER_LENGTH] == b"\x00\x00\x00\x03"
        assert frame[HEADER_LENGTH:] == b"abc"


class TestStreamReassembly:
    """A socket hands over arbitrary slices. Every assertion here is a shape
    the reader will actually see."""

    def test_a_frame_split_across_reads_is_reassembled(self):
        frame = encode_message({"hello": "world"})
        decoder = FrameDecoder()
        for i in range(len(frame) - 1):
            assert decoder.feed(frame[i:i + 1]) == [], "emitted before complete"
        got = decoder.feed(frame[-1:])
        assert [cbor2.loads(f) for f in got] == [{"hello": "world"}]

    def test_several_frames_in_one_read(self):
        blob = encode_message({"n": 1}) + encode_message({"n": 2}) + encode_message({"n": 3})
        decoder = FrameDecoder()
        assert [cbor2.loads(f) for f in decoder.feed(blob)] == [{"n": 1}, {"n": 2}, {"n": 3}]

    def test_a_partial_header_holds(self):
        """Three bytes cannot say how long anything is."""
        decoder = FrameDecoder()
        assert decoder.feed(b"\x00\x00\x00") == []
        assert decoder.pending == 3

    def test_a_trailing_partial_frame_waits_for_the_rest(self):
        whole = encode_message({"a": 1})
        partial = encode_message({"b": 2})[:5]
        decoder = FrameDecoder()
        got = decoder.feed(whole + partial)
        assert [cbor2.loads(f) for f in got] == [{"a": 1}]
        assert decoder.pending == 5

    def test_an_empty_read_changes_nothing(self):
        decoder = FrameDecoder()
        decoder.feed(encode_message({"a": 1})[:2])
        before = decoder.pending
        assert decoder.feed(b"") == []
        assert decoder.pending == before

    def test_a_zero_length_frame_is_a_frame(self):
        decoder = FrameDecoder()
        assert decoder.feed(struct.pack(">I", 0)) == [b""]


class TestLimits:
    """A length prefix is a promise from the other side. Believing it before
    checking is how a four-byte message asks for four gigabytes."""

    def test_an_over_long_announcement_is_refused_before_allocating(self):
        decoder = FrameDecoder(max_frame_length=1024)
        with pytest.raises(FrameError, match="over the"):
            decoder.feed(struct.pack(">I", 99_999_999))

    def test_a_huge_announcement_does_not_consume_memory_first(self):
        """The refusal has to happen on the header alone — four bytes in,
        nothing allocated."""
        decoder = FrameDecoder(max_frame_length=64)
        with pytest.raises(FrameError):
            decoder.feed(struct.pack(">I", MAX := 0xFFFF_FFFF))

    def test_encoding_past_the_limit_is_refused_too(self):
        with pytest.raises(FrameError):
            encode_frame(b"x" * 100, max_frame_length=99)

    def test_the_default_limit_matches_pis(self):
        assert DEFAULT_MAX_FRAME_LENGTH == 16 * 1024 * 1024

    def test_a_frame_at_exactly_the_limit_is_allowed(self):
        """Off-by-one here rejects a legal message."""
        payload = b"x" * 64
        frame = encode_frame(payload, max_frame_length=64)
        decoder = FrameDecoder(max_frame_length=64)
        assert decoder.feed(frame) == [payload]


class TestRoundTrip:

    @pytest.mark.parametrize("message", [
        {"type": "hello", "version": 1},
        {"type": "request", "id": "abc", "request": {"command": "list"}},
        {"text": "你好 world", "n": 42, "ok": True, "none": None, "arr": [1, 2, 3]},
        {"nested": {"deep": {"deeper": [{"x": 1}]}}},
        {},
    ])
    def test_encode_then_decode_is_identity(self, message):
        decoder = FrameDecoder()
        assert decode_messages(decoder, encode_message(message)) == [message]

    def test_cjk_survives_the_round_trip(self):
        """UTF-8 through a byte-length prefix: a length counted in characters
        instead of bytes truncates every non-ASCII message."""
        message = {"text": "你好世界" * 100}
        decoder = FrameDecoder()
        assert decode_messages(decoder, encode_message(message)) == [message]
