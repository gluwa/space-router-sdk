import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)

class SQLiteClient:
    """SQLite implementation for local testing."""

    def __init__(self, db_path: str = "space_router.db"):
        self.db_path = db_path
        self._setup_db()

    def _setup_db(self) -> None:
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # API Keys table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            rate_limit_rpm INTEGER NOT NULL DEFAULT 60,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        ''')

        # Nodes table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            endpoint_url TEXT NOT NULL,
            node_type TEXT NOT NULL DEFAULT 'residential',
            status TEXT NOT NULL DEFAULT 'online',
            health_score REAL NOT NULL DEFAULT 1.0,
            region TEXT,
            label TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        ''')

        # Route outcomes table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS route_outcomes (
            id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            success INTEGER NOT NULL,
            latency_ms INTEGER NOT NULL,
            bytes_transferred INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (node_id) REFERENCES nodes (id) ON DELETE CASCADE
        )
        ''')

        # Request logs table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS request_logs (
            id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            api_key_id TEXT,
            node_id TEXT,
            method TEXT NOT NULL,
            target_host TEXT NOT NULL,
            status_code INTEGER,
            bytes_sent INTEGER NOT NULL DEFAULT 0,
            bytes_received INTEGER NOT NULL DEFAULT 0,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            error_type TEXT,
            created_at TEXT NOT NULL
        )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"SQLite database set up at {self.db_path}")

    async def select(
        self,
        table: str,
        *,
        params: Optional[Dict[str, str]] = None,
        single: bool = False,
    ) -> Union[List[Dict], Dict, None]:
        """Select data from a table. Handle Supabase-style query params."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = f"SELECT * FROM {table}"
        values = []
        
        # Special handling for select, order parameters
        select_fields = "*"
        order_by = ""
        
        if params:
            # Extract special parameters
            if "select" in params:
                select_fields = params.pop("select")
                query = f"SELECT {select_fields} FROM {table}"
            
            if "order" in params:
                order_clause = params.pop("order")
                # Convert PostgreSQL-style order to SQLite
                # e.g., created_at.desc -> created_at DESC
                if ".desc" in order_clause:
                    field = order_clause.replace(".desc", "")
                    order_by = f" ORDER BY {field} DESC"
                elif ".asc" in order_clause:
                    field = order_clause.replace(".asc", "")
                    order_by = f" ORDER BY {field} ASC"
                else:
                    order_by = f" ORDER BY {order_clause}"
            
            # Build WHERE clause from remaining parameters
            conditions = []
            for key, value in params.items():
                # Handle PostgreSQL-style operators (eq, gt, lt)
                if key.startswith("id.eq") or key.startswith("id:eq"):
                    # Remove the 'eq.' prefix for comparison
                    clean_value = value.replace("eq.", "")
                    conditions.append("id = ?")
                    values.append(clean_value)
                elif 'eq.' in value:
                    # Handle cases like {"id": "eq.123"}
                    clean_value = value.replace("eq.", "")
                    conditions.append(f"{key} = ?")
                    values.append(clean_value)
                else:
                    conditions.append(f"{key} = ?")
                    values.append(value)
            
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
        
        # Add order by clause
        query += order_by
        
        try:
            cursor.execute(query, values)
            rows = cursor.fetchall()
            result = [dict(row) for row in rows]
            
            if single:
                return result[0] if result else None
            return result
        except sqlite3.Error as e:
            logger.error(f"SQLite error: {e}")
            return [] if not single else None
        finally:
            conn.close()

    async def insert(self, table: str, data: Union[Dict, List[Dict]], *, return_rows: bool = True) -> Optional[List[Dict]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if not isinstance(data, list):
            data = [data]
        
        results = []
        
        for item in data:
            # Make a copy to avoid modifying the original
            item_copy = dict(item)
            
            # Ensure id is present
            if 'id' not in item_copy:
                item_copy['id'] = str(uuid.uuid4())
            
            # Add timestamps if not present
            now = datetime.now().isoformat()
            if 'created_at' not in item_copy:
                item_copy['created_at'] = now
            if table == 'nodes' and 'updated_at' not in item_copy:
                item_copy['updated_at'] = now
                
            # Build query
            columns = ', '.join(item_copy.keys())
            placeholders = ', '.join(['?' for _ in item_copy.keys()])
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
            
            try:
                cursor.execute(query, list(item_copy.values()))
                if return_rows:
                    results.append(item_copy)
            except sqlite3.Error as e:
                logger.error(f"SQLite insert error: {e}")
                conn.close()
                return None
        
        conn.commit()
        conn.close()
        
        return results if return_rows else None

    async def update(
        self,
        table: str,
        data: Dict,
        *,
        params: Dict[str, str],
        return_rows: bool = False,
    ) -> Optional[List[Dict]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Add updated_at for nodes table
        if table == 'nodes' and 'updated_at' not in data:
            data['updated_at'] = datetime.now().isoformat()
        
        # Process PostgreSQL-style parameters
        where_params = {}
        for key, value in params.items():
            if value.startswith("eq."):
                where_params[key] = value[3:]  # Remove 'eq.' prefix
            else:
                where_params[key] = value
        
        # Build update query
        set_clause = ', '.join([f"{k} = ?" for k in data.keys()])
        where_clause = ' AND '.join([f"{k} = ?" for k in where_params.keys()])
        query = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
        
        values = list(data.values()) + list(where_params.values())
        
        try:
            cursor.execute(query, values)
            conn.commit()
            
            if return_rows and cursor.rowcount > 0:
                # Get the updated rows
                where_clause = ' AND '.join([f"{k} = ?" for k in where_params.keys()])
                select_query = f"SELECT * FROM {table} WHERE {where_clause}"
                cursor.execute(select_query, list(where_params.values()))
                rows = cursor.fetchall()
                result = [dict(row) for row in rows]
                conn.close()
                return result
            conn.close()
            return None
        except sqlite3.Error as e:
            logger.error(f"SQLite update error: {e}")
            conn.close()
            return None

    async def delete(self, table: str, *, params: Dict[str, str]) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Process PostgreSQL-style parameters
        where_params = {}
        for key, value in params.items():
            if value.startswith("eq."):
                where_params[key] = value[3:]  # Remove 'eq.' prefix
            else:
                where_params[key] = value
        
        # Build delete query
        where_clause = ' AND '.join([f"{k} = ?" for k in where_params.keys()])
        query = f"DELETE FROM {table} WHERE {where_clause}"
        
        try:
            cursor.execute(query, list(where_params.values()))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"SQLite delete error: {e}")
        finally:
            conn.close()

    async def rpc(self, function_name: str, params: Optional[Dict] = None) -> Union[Dict, List]:
        """Simple mock for RPC - only implements a few functions."""
        if function_name == "get_node_stats":
            # Mock implementation of node stats
            return {"active_count": 1, "total_count": 1}
        return {}