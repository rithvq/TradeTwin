"""Download/OAuth query credentials must not enter Uvicorn access logs."""

import logging


class RedactQuery(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                value.partition("?")[0] + "?[REDACTED]"
                if isinstance(value, str) and "?" in value
                else value
                for value in record.args
            )
        return True


def install():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, RedactQuery) for item in logger.filters):
        logger.addFilter(RedactQuery())
