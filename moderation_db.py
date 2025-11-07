#!/usr/bin/env python3
"""
Database module for tracking moderation reports.

Stores kind 1984 reports and provides queries for the strfry plugin.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class ModerationDB:
    """Database for tracking moderation reports."""

    def __init__(self, db_path: str):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Table for moderation reports
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_event_id TEXT NOT NULL,
                    reported_event_id TEXT NOT NULL,
                    reported_event_kind INTEGER,
                    reporter_pubkey TEXT NOT NULL,
                    report_type TEXT,
                    report_content TEXT,
                    timestamp INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(report_event_id)
                )
            """)

            # Indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reported_event
                ON reports(reported_event_id, timestamp)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reporter
                ON reports(reporter_pubkey)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON reports(timestamp)
            """)

            # Table for WoT cache
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS wot_cache (
                    pubkey TEXT PRIMARY KEY,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")

    @contextmanager
    def _get_conn(self):
        """Get database connection context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def add_report(
        self,
        report_event_id: str,
        reported_event_id: str,
        reported_event_kind: Optional[int],
        reporter_pubkey: str,
        report_type: Optional[str],
        report_content: str,
        timestamp: int,
    ) -> bool:
        """
        Add a moderation report to the database.

        Args:
            report_event_id: ID of the kind 1984 report event
            reported_event_id: ID of the event being reported
            reported_event_kind: Kind of the reported event
            reporter_pubkey: Pubkey of the reporter
            report_type: Type of report (spam, illegal, etc.)
            report_content: Content/description of the report
            timestamp: Unix timestamp of the report

        Returns:
            True if added, False if duplicate
        """
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO reports (
                        report_event_id,
                        reported_event_id,
                        reported_event_kind,
                        reporter_pubkey,
                        report_type,
                        report_content,
                        timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_event_id,
                        reported_event_id,
                        reported_event_kind,
                        reporter_pubkey,
                        report_type,
                        report_content,
                        timestamp,
                    ),
                )
                conn.commit()
                logger.info(
                    f"Added report: {reported_event_id} by {reporter_pubkey[:8]}... "
                    f"type={report_type}"
                )
                return True
        except sqlite3.IntegrityError:
            logger.debug(f"Duplicate report ignored: {report_event_id}")
            return False
        except Exception as e:
            logger.error(f"Error adding report: {e}")
            return False

    def get_report_count(
        self,
        event_id: str,
        wot_pubkeys: Optional[Set[str]] = None,
        time_window_days: Optional[int] = None,
        report_type: Optional[str] = None,
    ) -> int:
        """
        Get count of unique reporters for an event.

        Args:
            event_id: Event ID to check
            wot_pubkeys: Set of trusted pubkeys (WoT). If None, count all reports.
            time_window_days: Only count reports within this many days. If None, count all.
            report_type: Only count specific report type. If None, count all types.

        Returns:
            Number of unique reporters
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            query = """
                SELECT COUNT(DISTINCT reporter_pubkey)
                FROM reports
                WHERE reported_event_id = ?
            """
            params = [event_id]

            # Filter by time window
            if time_window_days is not None:
                cutoff_timestamp = int(
                    (datetime.now() - timedelta(days=time_window_days)).timestamp()
                )
                query += " AND timestamp >= ?"
                params.append(cutoff_timestamp)

            # Filter by report type
            if report_type is not None:
                query += " AND report_type = ?"
                params.append(report_type)

            # Filter by WoT
            if wot_pubkeys is not None and len(wot_pubkeys) > 0:
                placeholders = ",".join("?" * len(wot_pubkeys))
                query += f" AND reporter_pubkey IN ({placeholders})"
                params.extend(wot_pubkeys)

            cursor.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else 0

    def get_report_details(
        self,
        event_id: str,
        wot_pubkeys: Optional[Set[str]] = None,
        time_window_days: Optional[int] = None,
    ) -> List[Dict]:
        """
        Get detailed report information for an event.

        Args:
            event_id: Event ID to check
            wot_pubkeys: Set of trusted pubkeys (WoT)
            time_window_days: Only get reports within this many days

        Returns:
            List of report dictionaries
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            query = """
                SELECT
                    report_event_id,
                    reporter_pubkey,
                    report_type,
                    report_content,
                    timestamp,
                    created_at
                FROM reports
                WHERE reported_event_id = ?
            """
            params = [event_id]

            # Filter by time window
            if time_window_days is not None:
                cutoff_timestamp = int(
                    (datetime.now() - timedelta(days=time_window_days)).timestamp()
                )
                query += " AND timestamp >= ?"
                params.append(cutoff_timestamp)

            # Filter by WoT
            if wot_pubkeys is not None and len(wot_pubkeys) > 0:
                placeholders = ",".join("?" * len(wot_pubkeys))
                query += f" AND reporter_pubkey IN ({placeholders})"
                params.extend(wot_pubkeys)

            query += " ORDER BY timestamp DESC"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return [
                {
                    "report_event_id": row["report_event_id"],
                    "reporter_pubkey": row["reporter_pubkey"],
                    "report_type": row["report_type"],
                    "report_content": row["report_content"],
                    "timestamp": row["timestamp"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ]

    def get_reports_by_type(
        self,
        event_id: str,
        wot_pubkeys: Optional[Set[str]] = None,
        time_window_days: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Get report counts grouped by type.

        Args:
            event_id: Event ID to check
            wot_pubkeys: Set of trusted pubkeys (WoT)
            time_window_days: Only count reports within this many days

        Returns:
            Dictionary mapping report type to unique reporter count
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            query = """
                SELECT report_type, COUNT(DISTINCT reporter_pubkey) as count
                FROM reports
                WHERE reported_event_id = ?
            """
            params = [event_id]

            # Filter by time window
            if time_window_days is not None:
                cutoff_timestamp = int(
                    (datetime.now() - timedelta(days=time_window_days)).timestamp()
                )
                query += " AND timestamp >= ?"
                params.append(cutoff_timestamp)

            # Filter by WoT
            if wot_pubkeys is not None and len(wot_pubkeys) > 0:
                placeholders = ",".join("?" * len(wot_pubkeys))
                query += f" AND reporter_pubkey IN ({placeholders})"
                params.extend(wot_pubkeys)

            query += " GROUP BY report_type"

            cursor.execute(query, params)
            rows = cursor.fetchall()

            return {row["report_type"]: row["count"] for row in rows}

    def cleanup_old_reports(self, days: int):
        """
        Remove reports older than specified days.

        Args:
            days: Remove reports older than this many days
        """
        cutoff_timestamp = int(
            (datetime.now() - timedelta(days=days)).timestamp()
        )

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM reports WHERE timestamp < ?", (cutoff_timestamp,)
            )
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old reports")

    def update_wot_cache(self, pubkeys: Set[str]):
        """
        Update WoT cache with current trusted pubkeys.

        Args:
            pubkeys: Set of pubkeys in the WoT
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Clear existing cache
            cursor.execute("DELETE FROM wot_cache")

            # Insert new pubkeys
            for pubkey in pubkeys:
                cursor.execute(
                    "INSERT INTO wot_cache (pubkey) VALUES (?)", (pubkey,)
                )

            conn.commit()
            logger.info(f"Updated WoT cache with {len(pubkeys)} pubkeys")

    def get_wot_cache(self) -> Set[str]:
        """
        Get cached WoT pubkeys.

        Returns:
            Set of pubkeys from cache
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pubkey FROM wot_cache")
            rows = cursor.fetchall()
            return {row["pubkey"] for row in rows}

    def get_wot_cache_age(self) -> Optional[datetime]:
        """
        Get age of WoT cache.

        Returns:
            Datetime of last update, or None if cache is empty
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT MAX(last_updated) as last_update FROM wot_cache"
            )
            row = cursor.fetchone()
            if row and row["last_update"]:
                return datetime.fromisoformat(row["last_update"])
            return None

    def get_stats(self) -> Dict:
        """
        Get database statistics.

        Returns:
            Dictionary with stats
        """
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # Total reports
            cursor.execute("SELECT COUNT(*) as count FROM reports")
            total_reports = cursor.fetchone()["count"]

            # Unique reported events
            cursor.execute(
                "SELECT COUNT(DISTINCT reported_event_id) as count FROM reports"
            )
            unique_events = cursor.fetchone()["count"]

            # Unique reporters
            cursor.execute(
                "SELECT COUNT(DISTINCT reporter_pubkey) as count FROM reports"
            )
            unique_reporters = cursor.fetchone()["count"]

            # WoT cache size
            cursor.execute("SELECT COUNT(*) as count FROM wot_cache")
            wot_size = cursor.fetchone()["count"]

            return {
                "total_reports": total_reports,
                "unique_reported_events": unique_events,
                "unique_reporters": unique_reporters,
                "wot_cache_size": wot_size,
            }
