from typing import List, Dict, Any, Optional
from services.hardware.engine.normalization.hardware_mapper import HardwareMapper
from services.hardware.engine.compatibility.query_engine import QueryEngine

class HardwareProfile:
    def __init__(self, mapper: HardwareMapper):
        self.mapper = mapper
        
    def build_profile(self, cpu_raw: str = None, gpu_raw: str = None, ram_gb: float = None, vram_gb: float = None) -> Dict[str, Any]:
        """
        Resolves human-readable hardware into Nimlyx IDs using the HardwareMapper.
        """
        profile = {
            "ram_gb": ram_gb,
            "vram_gb": vram_gb,
            "cpu_id": None,
            "gpu_id": None,
            "resolution_debug": {
                "cpu": {"raw": cpu_raw, "status": "missing"},
                "gpu": {"raw": gpu_raw, "status": "missing"}
            }
        }
        
        if cpu_raw:
            match = self.mapper.match_candidate(cpu_raw, "cpu")
            if match.get("normalized_id"):
                profile["cpu_id"] = match["normalized_id"]
                profile["resolution_debug"]["cpu"]["status"] = match.get("confidence", "unknown")
            else:
                profile["resolution_debug"]["cpu"]["status"] = "unresolved"
                
        if gpu_raw:
            match = self.mapper.match_candidate(gpu_raw, "gpu")
            if match.get("normalized_id"):
                profile["gpu_id"] = match["normalized_id"]
                profile["resolution_debug"]["gpu"]["status"] = match.get("confidence", "unknown")
            else:
                profile["resolution_debug"]["gpu"]["status"] = "unresolved"
                
        return profile

class DiscoveryEngine:
    def __init__(self, query_engine: QueryEngine = None):
        self.query_engine = query_engine or QueryEngine()
        
    def find_games(self, hardware_profile: Dict[str, Any], statuses: List[str] = None, limit: int = None) -> List[Dict[str, Any]]:
        """
        Evaluates the hardware profile against the SQLite database.
        Returns a ranked list of games.
        """
        # Execute the raw evaluations leveraging the existing query engine
        evaluations = self.query_engine.get_games_for_hardware(hardware_profile)
        
        filtered = []
        for eval_res in evaluations:
            status = eval_res.get("status")
            if statuses and status not in statuses:
                continue
            filtered.append(eval_res)
            
        # Ranking logic
        # 1. runs_well, 2. playable, 3. unknown, 4. below_minimum
        rank_order = {
            "runs_well": 0,
            "playable": 1,
            "unknown": 2,
            "below_minimum": 3
        }
        
        # Sort by status tier, then alphabetically by title (or game_id)
        filtered.sort(key=lambda x: (rank_order.get(x["status"], 99), x.get("title", "")))
        
        if limit is not None:
            filtered = filtered[:limit]
            
        return filtered

class DiscoveryService:
    def __init__(self):
        self.mapper = HardwareMapper()
        self.profile_builder = HardwareProfile(self.mapper)
        self.engine = DiscoveryEngine()
        
    def find_games(self, cpu: str = None, gpu: str = None, ram_gb: float = None, vram_gb: float = None, statuses: List[str] = None, limit: int = None) -> List[Dict[str, Any]]:
        profile = self.profile_builder.build_profile(cpu, gpu, ram_gb, vram_gb)
        results = self.engine.find_games(profile, statuses=statuses, limit=limit)
        return {
            "hardware": profile,
            "results": results
        }

    def evaluate_single_game(self, game_id: str, cpu: str = None, gpu: str = None, ram_gb: float = None, vram_gb: float = None) -> Dict[str, Any]:
        profile = self.profile_builder.build_profile(cpu, gpu, ram_gb, vram_gb)
        result = self.engine.query_engine.evaluate_game(game_id, profile)
        return {
            "hardware": profile,
            "result": result
        }
