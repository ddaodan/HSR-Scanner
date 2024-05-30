from enum import Enum


class LogLevel(Enum):
    """LogLevel enum for logging the events"""

    INFO = "信息"
    ERROR = "错误"
    WARNING = "警告"
    DEBUG = "调试"
    TRACE = "TRACE"
    FATAL = "致命"
