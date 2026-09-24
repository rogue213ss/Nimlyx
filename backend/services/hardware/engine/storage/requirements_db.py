import sqlite3
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

class RequirementsDB:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "requirements.db")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Games Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    game_id TEXT PRIMARY KEY,
                    steam_app_id TEXT,
                    title TEXT,
                    last_updated DATETIME,
                    is_unknown BOOLEAN DEFAULT 0
                )
            """)
            
            # Sources Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    game_id TEXT PRIMARY KEY,
                    source_name TEXT,
                    source_url TEXT,
                    retrieved_at DATETIME,
                    parser_version TEXT,
                    confidence TEXT,
                    FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE CASCADE
                )
            """)
            
            # Requirements Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS requirements (
                    req_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    game_id TEXT,
                    requirement_type TEXT,
                    ram_gb REAL,
                    vram_gb REAL,
                    storage_gb REAL,
                    os TEXT,
                    FOREIGN KEY(game_id) REFERENCES games(game_id) ON DELETE CASCADE
                )
            """)
            
            # Hardware Table (Alternatives)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS requirement_hardware (
                    req_id INTEGER,
                    hardware_type TEXT,
                    group_index INTEGER,
                    hardware_id TEXT,
                    match_method TEXT,
                    confidence TEXT,
                    raw_name TEXT,
                    FOREIGN KEY(req_id) REFERENCES requirements(req_id) ON DELETE CASCADE
                )
            """)
            
            # Create indices for quick lookups
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_title ON games(title)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_req_hw ON requirement_hardware(hardware_id)")
            
            conn.commit()

    def upsert_game(self, game_id: str, steam_app_id: str, title: str, is_unknown: bool = False):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO games (game_id, steam_app_id, title, last_updated, is_unknown)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    title = excluded.title,
                    last_updated = excluded.last_updated,
                    is_unknown = excluded.is_unknown
            """, (game_id, steam_app_id, title, datetime.utcnow().isoformat() + "Z", is_unknown))
            conn.commit()

    def upsert_source(self, game_id: str, source_data: dict, overall_confidence: str):
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO sources (game_id, source_name, source_url, retrieved_at, parser_version, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    retrieved_at = excluded.retrieved_at,
                    parser_version = excluded.parser_version,
                    confidence = excluded.confidence
            """, (game_id, source_data.get("name"), source_data.get("url"), source_data.get("retrieved_at"), source_data.get("parser_version"), overall_confidence))
            conn.commit()

    def upsert_requirements(self, game_id: str, normalized_data: dict):
        with self.get_connection() as conn:
            # Delete old requirements for this game
            conn.execute("DELETE FROM requirements WHERE game_id = ?", (game_id,))
            
            for req_type in ["minimum", "recommended"]:
                reqs = normalized_data.get(req_type, {})
                
                cursor = conn.execute("""
                    INSERT INTO requirements (game_id, requirement_type, ram_gb, vram_gb, storage_gb, os)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    game_id, req_type, reqs.get("ram_gb"), reqs.get("vram_gb"), reqs.get("storage_gb"), reqs.get("os")
                ))
                req_id = cursor.lastrowid
                
                # Insert CPU / GPU alternatives
                for hw_type in ["cpu", "gpu"]:
                    groups = reqs.get(hw_type, [])
                    for g_idx, group in enumerate(groups):
                        alts = group.get("alternatives", [])
                        if not alts:
                            hw_id = group.get("id") or group.get("normalized_id")
                            if not hw_id and group.get("type", "").startswith("generic_"):
                                hw_id = f"generic_{hw_type}"
                                
                            if hw_id:
                                conn.execute("""
                                    INSERT INTO requirement_hardware (req_id, hardware_type, group_index, hardware_id, match_method, confidence, raw_name)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    req_id, hw_type, g_idx, hw_id,
                                    group.get("match_method"), group.get("confidence"),
                                    group.get("raw")
                                ))
                        else:
                            for alt in alts:
                                # alt is a string (hardware_id)
                                conn.execute("""
                                    INSERT INTO requirement_hardware (req_id, hardware_type, group_index, hardware_id, match_method, confidence, raw_name)
                                    VALUES (?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    req_id, hw_type, g_idx, alt,
                                    group.get("match_method"), group.get("confidence"),
                                    group.get("raw")
                                ))
            conn.commit()
            
    def get_game(self, game_id: str) -> Optional[dict]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
            return dict(row) if row else None
            
    def get_requirements(self, game_id: str) -> dict:
        """Returns the full unified JSON-like structure from the DB for compatibility evaluation."""
        result = {"minimum": {}, "recommended": {}}
        with self.get_connection() as conn:
            req_rows = conn.execute("SELECT * FROM requirements WHERE game_id = ?", (game_id,)).fetchall()
            for row in req_rows:
                rt = row["requirement_type"]
                result[rt] = {
                    "ram_gb": row["ram_gb"],
                    "vram_gb": row["vram_gb"],
                    "storage_gb": row["storage_gb"],
                    "os": row["os"],
                    "cpu": [],
                    "gpu": []
                }
                
                hw_rows = conn.execute("SELECT * FROM requirement_hardware WHERE req_id = ? ORDER BY hardware_type, group_index", (row["req_id"],)).fetchall()
                
                # Reconstruct groups
                groups = {"cpu": {}, "gpu": {}}
                for hw in hw_rows:
                    ht = hw["hardware_type"]
                    idx = hw["group_index"]
                    if idx not in groups[ht]:
                        groups[ht][idx] = {
                            "confidence": hw["confidence"],
                            "match_method": hw["match_method"],
                            "type": "generic_cpu" if ht == "cpu" and hw["hardware_id"].startswith("generic") else ("generic_gpu" if ht == "gpu" and hw["hardware_id"].startswith("generic") else "mapped"),
                            "alternatives": []
                        }
                    groups[ht][idx]["alternatives"].append(hw["hardware_id"])
                    
                result[rt]["cpu"] = list(groups["cpu"].values())
                result[rt]["gpu"] = list(groups["gpu"].values())
                
        return result
        
    def list_games(self) -> List[dict]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM games").fetchall()
            return [dict(r) for r in rows]

    def clear(self):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM games")
            conn.commit()

# Expose a default instance
requirements_db = RequirementsDB()
