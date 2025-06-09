#!/usr/bin/env python3
# -----------------------------------------------------------------------------
# Filename: redis_diagnostics.py
# Author: Rajaram Lakshmanan
# Description: Temporary diagnostics for Redis streams
# -----------------------------------------------------------------------------

import redis
import logging

logger = logging.getLogger("RedisDiagnostics")


def diagnose_redis_streams(host='localhost', port=6379, db=0):
    """
    Diagnose Redis streams and consumer groups.

    This function connects to Redis and prints information about all streams and
    their consumer groups, providing insight into potential issues with stream
    subscription and message delivery.

    Args:
        host (str): Redis host
        port (int): Redis port
        db (int): Redis database number
    """
    logger.info("Starting Redis stream diagnostics")

    # Get a Redis connection
    r = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    try:
        # List all streams
        streams = []
        cursor = '0'
        while True:
            cursor, keys = r.scan(cursor, match='*', count=1000)
            for key in keys:
                try:
                    # Check if this is a stream
                    if r.type(key) == 'stream':
                        streams.append(key)
                except Exception as e:
                    logger.error(f"Error checking type for key {key}: {e}")
            if cursor == '0':
                break

        logger.info(f"Found {len(streams)} Redis streams")

        # Print stream info
        for stream in streams:
            logger.info(f"Stream: {stream}")
            try:
                # Get stream info
                info = r.xinfo_stream(stream)
                logger.info(f"  Length: {info.get('length', 'unknown')}")
                logger.info(f"  Last generated ID: {info.get('last-generated-id', 'unknown')}")

                # Get consumer groups
                try:
                    groups = r.xinfo_groups(stream)
                    logger.info(f"  Found {len(groups)} consumer groups")

                    for group in groups:
                        logger.info(f"    Group: {group.get('name')}")
                        logger.info(f"      Last delivered ID: {group.get('last-delivered-id')}")
                        logger.info(f"      Pending: {group.get('pending')}")
                        logger.info(f"      Consumers: {group.get('consumers')}")

                        # Get pending messages
                        try:
                            pending = r.xpending_range(stream, group['name'], min='-', max='+', count=10)
                            if pending:
                                logger.info(f"      First few pending messages: {pending[:3]}")
                        except Exception as e:
                            logger.error(f"      Error getting pending for {group['name']}: {e}")
                except Exception as e:
                    logger.error(f"  Error getting consumer groups for {stream}: {e}")

                # Print some messages
                try:
                    messages = r.xrange(stream, count=5)
                    logger.info(f"  First few messages: {messages[:3]}")
                except Exception as e:
                    logger.error(f"  Error getting messages for {stream}: {e}")

            except Exception as e:
                logger.error(f"  Error getting info for stream {stream}: {e}")

    except Exception as e:
        logger.error(f"Error during Redis diagnostics: {e}")

    logger.info("Redis stream diagnostics complete")