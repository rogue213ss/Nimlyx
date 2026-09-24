import re
from typing import Dict, Any, Optional

# Import the actual engines from the isolated demo project
from services.hardware.engine.compatibility.discovery_engine import DiscoveryService

class NimlyxAdapter:
    """
    Adapter bridging the Production Nimlyx backend with the Offline Requirements Engine.
    """
    
    def __init__(self):
        # The DiscoveryService encapsulates DB connections and hardware resolution
        self.service = DiscoveryService()

    def evaluate_hardware_catalog(
        self, 
        cpu_raw: Optional[str] = None, 
        gpu_raw: Optional[str] = None, 
        ram_gb: Optional[float] = None, 
        vram_gb: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Evaluates a user's PC against the entire requirements catalog offline.
        """
        
        # 1. Ask the discovery service to evaluate
        raw_result = self.service.find_games(
            cpu=cpu_raw, 
            gpu=gpu_raw, 
            ram_gb=ram_gb, 
            vram_gb=vram_gb
        )
        
        # 2. Extract resolved hardware profile
        resolved_hardware = {
            "cpu": raw_result.get("hardware", {}).get("cpu_id"),
            "gpu": raw_result.get("hardware", {}).get("gpu_id"),
            "ram_gb": raw_result.get("hardware", {}).get("ram_gb"),
            "vram_gb": raw_result.get("hardware", {}).get("vram_gb"),
        }
        
        # 3. Translate the responses to Production Contract
        games_output = {}
        for game in raw_result.get("results", []):
            internal_id = game.get("game_id", "")
            
            # Map "steam_730" -> 730
            match = re.match(r'steam_(\d+)', internal_id)
            if not match:
                continue
                
            production_app_id = int(match.group(1))
            
            status = game.get("status")
            checks = game.get("checks", {})
            
            # Formulate a top level reason based on sub-checks
            reason = self._summarize_reason(status, checks)
            
            games_output[production_app_id] = {
                "title": game.get("title"),
                "status": status,
                "reason": reason,
                "evaluation": checks
            }
            
        return {
            "resolved_hardware": resolved_hardware,
            "games": games_output
        }

    def _summarize_reason(self, status: str, checks: Dict[str, Any]) -> str:
        """
        Translates raw check dicts into a human-readable top-level reason for production.
        """
        if status == "runs_well":
            return "Meets recommended specifications."
        elif status == "playable":
            return "Meets minimum specifications."
        elif status == "below_minimum":
            failures = []
            for comp, comp_data in checks.items():
                if comp_data.get("status") == "fail":
                    failures.append(comp.upper())
            if failures:
                return f"Below minimum requirements: {', '.join(failures)} insufficient."
            return "Below minimum requirements."
        else: # unknown
            unknowns = []
            for comp, comp_data in checks.items():
                if comp_data.get("status") == "unknown":
                    unknowns.append(comp.upper())
            if unknowns:
                return f"Requirements incomplete or hardware unrecognized: {', '.join(unknowns)}."
            return "Compatibility unknown."
    def evaluate_production_endpoint(self, app_id: int, cpu_id: str, gpu_id: str, ram_gb: float) -> dict:
        """
        Evaluates a single game for the /api/game-detail/<app_id>/compatibility endpoint.
        Uses exactly 0 network requests by looking up 'steam_{app_id}' in the offline db.
        Returns the exact JSON format expected by the frontend.
        """
        game_id = f"steam_{app_id}"
        user_pc = {
            "cpu_id": cpu_id,
            "gpu_id": gpu_id,
            "ram_gb": ram_gb,
            "vram_gb": None # VRAM is not provided by production UI currently
        }
        
        raw_res = self.service.engine.query_engine.evaluate_game(game_id, user_pc)
        
        if not raw_res:
            return {
                "verdict": "unknown",
                "components": [
                    {"component": "cpu", "meets_minimum": None, "meets_recommended": None},
                    {"component": "gpu", "meets_minimum": None, "meets_recommended": None},
                    {"component": "ram", "meets_minimum": None, "meets_recommended": None}
                ],
                "notes": ["Game not found in offline requirements database."]
            }
            
        status = raw_res.get("status", "unknown")
        checks = raw_res.get("checks", {})
        
        def map_comp(comp_name):
            c_status = checks.get(comp_name, {}).get("status", "unknown")
            if c_status == "pass":
                meets_min = True
                meets_rec = (status == "runs_well")
                return {"component": comp_name, "meets_minimum": meets_min, "meets_recommended": meets_rec}
            elif c_status == "fail":
                return {"component": comp_name, "meets_minimum": False, "meets_recommended": False}
            else:
                return {"component": comp_name, "meets_minimum": None, "meets_recommended": None}
                
        verdict_map = {
            "runs_well": "runs_well",
            "playable": "playable",
            "below_minimum": "not_recommended",
            "unknown": "unknown"
        }
        
        verdict = verdict_map.get(status, "unknown")
        
        notes = []
        if verdict == "unknown":
            notes.append(self._summarize_reason(status, checks))
            
        if raw_res.get("is_unknown"):
            notes.append("Game requirements are unknown or unparseable.")
            
        return {
            "verdict": verdict,
            "components": [
                map_comp("cpu"),
                map_comp("gpu"),
                map_comp("ram")
            ],
            "notes": notes
        }
