import json
from pathlib import Path
from services.hardware.engine.storage.requirements_db import requirements_db

def _safe_float(val):
    if val is None:
        return None
    try:
        f = float(val)
        if f < 0: return None
        return f
    except (ValueError, TypeError):
        return None

class QueryEngine:
    def __init__(self):
        self.db = requirements_db
        # Load hardware rankings for evaluation
        base_path = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "hardware" / "rankings"
        with open(base_path / "cpu_rankings.json", "r") as f:
            cpu_data = json.load(f)
            self.cpu_rankings = {r["external_id"]: r["performance_rank"] for r in cpu_data["records"] if r.get("performance_rank") is not None}
            
        with open(base_path / "gpu_rankings.json", "r") as f:
            gpu_data = json.load(f)
            self.gpu_rankings = {r["external_id"]: r["compute_capability_rank"] for r in gpu_data["records"] if r.get("compute_capability_rank") is not None}

    def check_hardware(self, user_val: str, hw_groups: list, hw_type: str, req_context: dict) -> dict:
        """
        Evaluates hardware groups and returns a dictionary with 'status' and 'reason'.
        For CPUs, multiple groups (lines) usually represent vendor alternatives (OR).
        For GPUs, multiple groups might represent vendor alternatives OR additional modifiers (AND).
        To be safe, we will treat multiple groups as OR if they are specific models, 
        and AND if one is generic. But actually, if ANY group has rank 0 (missing), we should ignore it if another group passes!
        """
        if not hw_groups:
            return {'status': 'pass', 'reason': 'no_requirement'}
            
        if user_val is None or str(user_val).strip() == "":
            return {'status': 'unknown', 'reason': 'missing_user_hardware'}
            
        rank_map = self.cpu_rankings if hw_type == 'cpu' else self.gpu_rankings
        
        try:
            user_rank = rank_map.get(user_val, 999999)
        except TypeError:
            # e.g., user_val is a list or dict
            return {'status': 'unknown', 'reason': 'invalid_hardware_type'}
            
        has_unresolved = False
        valid_groups_passed = 0
        valid_groups_failed = 0
        
        for group in hw_groups:
            alts = group.get("alternatives", [])
            if not alts or group.get("confidence") == "unresolved":
                has_unresolved = True
                continue
                
            group_passed = False
            for alt in alts:
                if alt.startswith("generic_"):
                    # Generic hardware handling
                    if hw_type == "gpu":
                        # If VRAM is explicitly checked at top level, we can let this generic pass.
                        # Wait, what if the generic group HAS VRAM? The query engine can't see it currently.
                        if _safe_float(req_context.get("vram_gb")) is not None:
                            group_passed = True
                    elif hw_type == "cpu":
                        if _safe_float(req_context.get("ram_gb")) is not None:
                            group_passed = True
                else:
                    req_rank = rank_map.get(alt)
                    if req_rank is not None:
                        if user_rank <= req_rank: 
                            group_passed = True
                    else:
                        # Missing from ranking! Rank 0 is impossible.
                        # Do not automatically fail the group if it's missing, but we can't pass it either.
                        pass
                        
                if group_passed:
                    break
                    
            # Did the group pass?
            if group_passed:
                valid_groups_passed += 1
            else:
                if all(a.startswith("generic_") for a in alts):
                    has_unresolved = True
                else:
                    # Check if all alternatives in this group were missing from rankings
                    all_missing = all(not a.startswith("generic_") and rank_map.get(a) is None for a in alts)
                    if all_missing:
                        has_unresolved = True
                    else:
                        valid_groups_failed += 1
                
        # If it's CPU, any passed group is usually enough (OR across lines)
        if hw_type == 'cpu':
            if valid_groups_passed > 0:
                return {'status': 'pass', 'reason': 'cpu_group_passed'}
            elif valid_groups_failed > 0:
                return {'status': 'fail', 'reason': 'cpu_groups_failed'}
            elif has_unresolved:
                return {'status': 'unknown', 'reason': 'cpu_unresolved'}
            else:
                return {'status': 'pass', 'reason': 'no_valid_cpu_groups'}
                
        # If it's GPU, we might require all non-unresolved groups to pass (AND across lines)
        # However, if it's AMD vs Nvidia on different lines, they should be OR!
        # If we have 1 passed and 1 failed, is it OR? Yes, usually.
        if hw_type == 'gpu':
            if valid_groups_passed > 0 and valid_groups_failed > 0:
                # E.g. Nvidia passed, AMD failed -> PASS
                return {'status': 'pass', 'reason': 'gpu_alternative_passed'}
            elif valid_groups_failed > 0:
                return {'status': 'fail', 'reason': 'gpu_groups_failed'}
            elif valid_groups_passed > 0:
                return {'status': 'pass', 'reason': 'gpu_group_passed'}
            elif has_unresolved:
                return {'status': 'unknown', 'reason': 'gpu_unresolved'}
            else:
                return {'status': 'pass', 'reason': 'no_valid_gpu_groups'}

    def evaluate_game(self, game_id: str, user_pc: dict) -> dict:
        """Evaluates a single game directly from the database."""
        with self.db.get_connection() as conn:
            game_row = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
            if not game_row:
                return None
                
            game = dict(game_row)
            
            if game.get("is_unknown"):
                return {
                    "game_id": game_id,
                    "title": game["title"],
                    "status": "unknown",
                    "is_unknown": True,
                    "checks": {
                        "ram": {"status": "unknown", "reason": "game_unknown"},
                        "vram": {"status": "unknown", "reason": "game_unknown"},
                        "cpu": {"status": "unknown", "reason": "game_unknown"},
                        "gpu": {"status": "unknown", "reason": "game_unknown"}
                    }
                }
                
            req_rows = conn.execute("SELECT * FROM requirements WHERE game_id = ?", (game_id,)).fetchall()
            reqs = {"minimum": {}, "recommended": {}}
            req_id_to_rt = {}
            for row in req_rows:
                rt = row["requirement_type"]
                req_id_to_rt[row["req_id"]] = rt
                reqs[rt] = {
                    "ram_gb": row["ram_gb"],
                    "vram_gb": row["vram_gb"],
                    "storage_gb": row["storage_gb"],
                    "os": row["os"],
                    "cpu": {},
                    "gpu": {}
                }
                
            if req_id_to_rt:
                req_ids = list(req_id_to_rt.keys())
                placeholders = ",".join("?" for _ in req_ids)
                hw_rows = conn.execute(f"SELECT * FROM requirement_hardware WHERE req_id IN ({placeholders}) ORDER BY req_id, hardware_type, group_index", req_ids).fetchall()
                for hw in hw_rows:
                    req_id = hw["req_id"]
                    rt = req_id_to_rt[req_id]
                    ht = hw["hardware_type"]
                    idx = hw["group_index"]
                    target_dict = reqs[rt][ht]
                    if idx not in target_dict:
                        target_dict[idx] = {
                            "confidence": hw["confidence"],
                            "match_method": hw["match_method"],
                            "type": "generic_cpu" if ht == "cpu" and hw["hardware_id"].startswith("generic") else ("generic_gpu" if ht == "gpu" and hw["hardware_id"].startswith("generic") else "mapped"),
                            "alternatives": []
                        }
                    target_dict[idx]["alternatives"].append(hw["hardware_id"])
                    
        # Convert groups dictionaries to lists
        for rt in ["minimum", "recommended"]:
            if reqs[rt]:
                reqs[rt]["cpu"] = list(reqs[rt]["cpu"].values())
                reqs[rt]["gpu"] = list(reqs[rt]["gpu"].values())
                
        user_ram = _safe_float(user_pc.get("ram_gb"))
        user_vram = _safe_float(user_pc.get("vram_gb"))
        
        min_req = reqs.get("minimum", {})
        rec_req = reqs.get("recommended", {})
        
        checks = {
            "ram": {"status": "pass", "reason": "no_requirement"},
            "vram": {"status": "pass", "reason": "no_requirement"},
            "cpu": {"status": "pass", "reason": "no_requirement"},
            "gpu": {"status": "pass", "reason": "no_requirement"}
        }
        
        min_ram = _safe_float(min_req.get("ram_gb"))
        min_vram = _safe_float(min_req.get("vram_gb"))
        
        if min_ram is not None:
            if user_ram is None:
                checks["ram"] = {"status": "unknown", "reason": "missing_user_ram"}
            elif user_ram < min_ram: 
                checks["ram"] = {"status": "fail", "reason": "insufficient_ram"}
            else:
                checks["ram"] = {"status": "pass", "reason": "ram_met"}
        elif "ram_gb" in min_req and min_req["ram_gb"] is not None: 
            checks["ram"] = {"status": "unknown", "reason": "malformed_ram"}
            
        if min_vram is not None:
            if user_vram is None:
                checks["vram"] = {"status": "unknown", "reason": "missing_user_vram"}
            elif user_vram < min_vram: 
                checks["vram"] = {"status": "fail", "reason": "insufficient_vram"}
            else:
                checks["vram"] = {"status": "pass", "reason": "vram_met"}
                
        if min_req.get("cpu"):
            checks["cpu"] = self.check_hardware(user_pc.get("cpu_id"), min_req["cpu"], "cpu", min_req)
            
        if min_req.get("gpu"):
            checks["gpu"] = self.check_hardware(user_pc.get("gpu_id"), min_req["gpu"], "gpu", min_req)
            
        is_unknown = any(c["status"] == "unknown" for c in checks.values())
        is_fail = any(c["status"] == "fail" for c in checks.values())
        
        if is_fail:
            status = "below_minimum"
        elif is_unknown:
            status = "unknown"
        else:
            rec_cpu = rec_req.get("cpu")
            rec_gpu = rec_req.get("gpu")
            rec_ram = _safe_float(rec_req.get("ram_gb"))
            
            meets_rec = True
            if rec_cpu and self.check_hardware(user_pc.get("cpu_id"), rec_cpu, "cpu", rec_req)["status"] != "pass":
                meets_rec = False
            if rec_gpu and self.check_hardware(user_pc.get("gpu_id"), rec_gpu, "gpu", rec_req)["status"] != "pass":
                meets_rec = False
            if rec_ram is not None and user_ram < rec_ram:
                meets_rec = False
                
            status = "runs_well" if meets_rec else "playable"
            
        return {
            "game_id": game_id,
            "title": game["title"],
            "status": status,
            "checks": checks
        }

    def get_games_for_hardware(self, user_pc: dict) -> list:
        """Evaluates all games by bulk loading requirements from the DB to minimize SQLite overhead."""
        import time
        results = []
        
        with self.db.get_connection() as conn:
            # 1. Load all games
            games_rows = conn.execute("SELECT * FROM games").fetchall()
            games_dict = {row["game_id"]: dict(row) for row in games_rows}
            
            # 2. Load all requirements
            req_rows = conn.execute("SELECT * FROM requirements").fetchall()
            reqs_by_game = {}
            req_id_to_game = {}
            for row in req_rows:
                game_id = row["game_id"]
                rt = row["requirement_type"]
                req_id_to_game[row["req_id"]] = (game_id, rt)
                
                if game_id not in reqs_by_game:
                    reqs_by_game[game_id] = {"minimum": {}, "recommended": {}}
                    
                reqs_by_game[game_id][rt] = {
                    "ram_gb": row["ram_gb"],
                    "vram_gb": row["vram_gb"],
                    "storage_gb": row["storage_gb"],
                    "os": row["os"],
                    "cpu": {},
                    "gpu": {}
                }
                
            # 3. Load all hardware requirements
            hw_rows = conn.execute("SELECT * FROM requirement_hardware ORDER BY req_id, hardware_type, group_index").fetchall()
            for hw in hw_rows:
                req_id = hw["req_id"]
                if req_id not in req_id_to_game: continue
                game_id, rt = req_id_to_game[req_id]
                
                ht = hw["hardware_type"]
                idx = hw["group_index"]
                target_dict = reqs_by_game[game_id][rt][ht]
                
                if idx not in target_dict:
                    target_dict[idx] = {
                        "confidence": hw["confidence"],
                        "match_method": hw["match_method"],
                        "type": "generic_cpu" if ht == "cpu" and hw["hardware_id"].startswith("generic") else ("generic_gpu" if ht == "gpu" and hw["hardware_id"].startswith("generic") else "mapped"),
                        "alternatives": []
                    }
                target_dict[idx]["alternatives"].append(hw["hardware_id"])

        # Convert groups dictionaries to lists
        for game_id, reqs in reqs_by_game.items():
            for rt in ["minimum", "recommended"]:
                if rt in reqs and reqs[rt]:
                    reqs[rt]["cpu"] = list(reqs[rt]["cpu"].values())
                    reqs[rt]["gpu"] = list(reqs[rt]["gpu"].values())

        # Evaluate each game
        user_ram = _safe_float(user_pc.get("ram_gb")) or 0
        user_vram = _safe_float(user_pc.get("vram_gb")) or 0
        
        for game_id, game in games_dict.items():
            if game.get("is_unknown"):
                results.append({
                    "game_id": game_id,
                    "title": game["title"],
                    "status": "unknown",
                    "is_unknown": True,
                    "checks": {
                        "ram": {"status": "unknown", "reason": "game_unknown"},
                        "vram": {"status": "unknown", "reason": "game_unknown"},
                        "cpu": {"status": "unknown", "reason": "game_unknown"},
                        "gpu": {"status": "unknown", "reason": "game_unknown"}
                    }
                })
                continue
                
            reqs = reqs_by_game.get(game_id, {"minimum": {}, "recommended": {}})
            min_req = reqs.get("minimum", {})
            rec_req = reqs.get("recommended", {})
            
            checks = {
                "ram": {"status": "pass", "reason": "no_requirement"},
                "vram": {"status": "pass", "reason": "no_requirement"},
                "cpu": {"status": "pass", "reason": "no_requirement"},
                "gpu": {"status": "pass", "reason": "no_requirement"}
            }
            
            min_ram = _safe_float(min_req.get("ram_gb"))
            min_vram = _safe_float(min_req.get("vram_gb"))
            
            if min_ram is not None:
                if user_ram < min_ram: 
                    checks["ram"] = {"status": "fail", "reason": "insufficient_ram"}
                else:
                    checks["ram"] = {"status": "pass", "reason": "ram_met"}
            elif "ram_gb" in min_req and min_req["ram_gb"] is not None: 
                checks["ram"] = {"status": "unknown", "reason": "malformed_ram"}
                
            if min_vram is not None:
                if user_vram < min_vram: 
                    checks["vram"] = {"status": "fail", "reason": "insufficient_vram"}
                else:
                    checks["vram"] = {"status": "pass", "reason": "vram_met"}
            elif "vram_gb" in min_req and min_req["vram_gb"] is not None: 
                checks["vram"] = {"status": "unknown", "reason": "malformed_vram"}
                
            checks["cpu"] = self.check_hardware(user_pc.get("cpu_id"), min_req.get("cpu", []), "cpu", min_req)
            checks["gpu"] = self.check_hardware(user_pc.get("gpu_id"), min_req.get("gpu", []), "gpu", min_req)
            
            # Extract just the statuses for the if logic
            min_statuses = [c["status"] for c in checks.values()]
            
            if "fail" in min_statuses:
                status = "below_minimum"
            elif "unknown" in min_statuses:
                status = "unknown"
            else:
                rec_cpu = self.check_hardware(user_pc.get("cpu_id"), rec_req.get("cpu", []), "cpu", rec_req)
                rec_gpu = self.check_hardware(user_pc.get("gpu_id"), rec_req.get("gpu", []), "gpu", rec_req)
                status = "runs_well" if rec_cpu["status"] == 'pass' and rec_gpu["status"] == 'pass' else "playable"
                    
            results.append({
                "game_id": game_id,
                "title": game["title"],
                "status": status,
                "is_unknown": False,
                "checks": checks
            })
            
        return results
