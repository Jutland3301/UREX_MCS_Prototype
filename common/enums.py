from enum import Enum


class MessageType(str, Enum):
    TELEMETRY = "TELEMETRY"
    EVENT = "EVENT"
    WARNING = "WARNING"
    ERROR = "ERROR"
    COMMAND = "COMMAND"
    ACK = "ACK"
    NACK = "NACK"
    HEARTBEAT = "HEARTBEAT"
    RAW = "RAW"


class LinkStatus(str, Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    DEGRADED = "DEGRADED"
    RECONNECTING = "RECONNECTING"
    UNKNOWN = "UNKNOWN"


class ProcessStatus(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class RadioState(str, Enum):
    OFF = "OFF"
    IDLE = "IDLE"
    RX = "RX"
    TX = "TX"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


class SDRStatus(str, Enum):
    OFFLINE = "OFFLINE"
    IDLE = "IDLE"
    RECEIVING = "RECEIVING"
    TRANSMITTING = "TRANSMITTING"
    ERROR = "ERROR"


class CANStatus(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    ERROR = "ERROR"
    BUS_OFF = "BUS_OFF"
    UNKNOWN = "UNKNOWN"


class CRCStatus(str, Enum):
    OK = "OK"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


class ParseStatus(str, Enum):
    OK = "OK"
    INVALID_HEADER = "INVALID_HEADER"
    INVALID_LENGTH = "INVALID_LENGTH"
    INVALID_FIELD = "INVALID_FIELD"
    UNSUPPORTED = "UNSUPPORTED"


class CommandStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    EXECUTING = "EXECUTING"
    ACK = "ACK"
    NACK = "NACK"
    TIMEOUT = "TIMEOUT"
    FAILED = "FAILED"


class LogSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"
