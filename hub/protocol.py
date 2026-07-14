"""UART RPC v1 framing: COBS, CRC-16/CCITT-FALSE, and JSON payloads."""

from .compat import json_dumps, json_loads

VERSION = 1

KIND_CALL = 1
KIND_RETURN = 2
KIND_EVENT = 3

STATUS_OK = 0
STATUS_ACCEPTED = 1
STATUS_BAD_REQUEST = 2
STATUS_NOT_FOUND = 3
STATUS_BUSY = 4
STATUS_FAILED = 5
STATUS_UNAVAILABLE = 6

FLAG_NO_REPLY = 0x01
FLAG_RETRY = 0x02

HEADER_SIZE = 8
CRC_SIZE = 2
MAX_PAYLOAD_SIZE = 256
MAX_RAW_SIZE = HEADER_SIZE + MAX_PAYLOAD_SIZE + CRC_SIZE
MAX_ENCODED_SIZE = MAX_RAW_SIZE + ((MAX_RAW_SIZE + 253) // 254)


class ProtocolError(Exception):
    pass


def crc16_ccitt(data):
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xffff, no final xor."""
    crc = 0xffff
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xffff
            else:
                crc = (crc << 1) & 0xffff
    return crc


def cobs_encode(data):
    """Encode bytes without zero bytes using Consistent Overhead Byte Stuffing."""
    output = bytearray()
    code_index = 0
    output.append(0)
    code = 1

    for byte in data:
        if byte == 0:
            output[code_index] = code
            code_index = len(output)
            output.append(0)
            code = 1
        else:
            output.append(byte)
            code += 1
            if code == 0xff:
                output[code_index] = code
                code_index = len(output)
                output.append(0)
                code = 1

    output[code_index] = code
    return bytes(output)


def cobs_decode(encoded):
    """Decode one COBS packet, excluding its trailing zero delimiter."""
    if not encoded:
        raise ProtocolError("empty COBS packet")
    if 0 in encoded:
        raise ProtocolError("zero byte inside COBS packet")

    output = bytearray()
    index = 0
    length = len(encoded)
    while index < length:
        code = encoded[index]
        index += 1
        if code == 0:
            raise ProtocolError("invalid COBS code")
        end = index + code - 1
        if end > length:
            raise ProtocolError("truncated COBS packet")
        output.extend(encoded[index:end])
        index = end
        if code != 0xff and index < length:
            output.append(0)
    return bytes(output)


def _u16le(value):
    return bytes((value & 0xff, (value >> 8) & 0xff))


def _read_u16le(data, offset):
    return data[offset] | (data[offset + 1] << 8)


def encode_packet(kind, request_id=0, body=None, status=STATUS_OK, flags=0):
    """Build a complete COBS-delimited UART RPC packet."""
    if kind not in (KIND_CALL, KIND_RETURN, KIND_EVENT):
        raise ProtocolError("invalid kind")
    if not 0 <= request_id <= 0xffff:
        raise ProtocolError("request id outside uint16")
    if not 0 <= status <= 0xff or not 0 <= flags <= 0xff:
        raise ProtocolError("invalid status or flags")

    payload = b"" if body is None else json_dumps(body)
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ProtocolError("JSON payload exceeds %d bytes" % MAX_PAYLOAD_SIZE)

    header = bytearray()
    header.append(VERSION)
    header.append(kind)
    header.append(flags)
    header.append(status)
    header.extend(_u16le(request_id))
    header.extend(_u16le(len(payload)))
    raw_without_crc = bytes(header) + payload
    raw = raw_without_crc + _u16le(crc16_ccitt(raw_without_crc))
    return cobs_encode(raw) + b"\x00"


def decode_packet(encoded):
    """Decode one COBS packet excluding its zero delimiter."""
    raw = cobs_decode(encoded)
    if len(raw) < HEADER_SIZE + CRC_SIZE:
        raise ProtocolError("packet shorter than header and CRC")
    if len(raw) > MAX_RAW_SIZE:
        raise ProtocolError("raw packet exceeds maximum size")
    if raw[0] != VERSION:
        raise ProtocolError("unsupported protocol version")
    if raw[1] not in (KIND_CALL, KIND_RETURN, KIND_EVENT):
        raise ProtocolError("invalid packet kind")

    payload_len = _read_u16le(raw, 6)
    expected_size = HEADER_SIZE + payload_len + CRC_SIZE
    if payload_len > MAX_PAYLOAD_SIZE or len(raw) != expected_size:
        raise ProtocolError("payload length mismatch")

    supplied_crc = _read_u16le(raw, len(raw) - CRC_SIZE)
    calculated_crc = crc16_ccitt(raw[:-CRC_SIZE])
    if supplied_crc != calculated_crc:
        raise ProtocolError("CRC mismatch")

    payload = raw[HEADER_SIZE:-CRC_SIZE]
    if payload:
        try:
            body = json_loads(payload)
        except (ValueError, TypeError, UnicodeError):
            raise ProtocolError("invalid JSON payload")
    else:
        body = None

    return {
        "kind": raw[1],
        "flags": raw[2],
        "status": raw[3],
        "request_id": _read_u16le(raw, 4),
        "body": body,
    }


class FrameDecoder:
    """Incrementally decode a byte stream while resynchronizing on zero bytes."""

    def __init__(self):
        self._encoded = bytearray()
        self._discarding = False
        self.errors = 0

    def feed(self, data):
        frames = []
        for byte in data:
            if byte == 0:
                if self._discarding:
                    self._discarding = False
                    self._encoded = bytearray()
                    continue
                if not self._encoded:
                    continue
                try:
                    frames.append(decode_packet(bytes(self._encoded)))
                except ProtocolError:
                    self.errors += 1
                self._encoded = bytearray()
                continue

            if self._discarding:
                continue
            if len(self._encoded) >= MAX_ENCODED_SIZE:
                self.errors += 1
                self._encoded = bytearray()
                self._discarding = True
                continue
            self._encoded.append(byte)
        return frames
