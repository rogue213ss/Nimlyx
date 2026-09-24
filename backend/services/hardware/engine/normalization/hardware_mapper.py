import re
import json
import functools
from typing import Dict, Any, List, Optional
from pathlib import Path
from rapidfuzz import fuzz, process

DEFAULT_CPU_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "hardware" / "normalized" / "cpus.json"
DEFAULT_GPU_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / "data" / "hardware" / "normalized" / "gpus.json"

@functools.lru_cache(maxsize=None)
def _load_and_build_indexes(cpu_path_str: str, gpu_path_str: str):
    with open(cpu_path_str, "r", encoding="utf-8") as f:
        cpus = json.load(f)
    with open(gpu_path_str, "r", encoding="utf-8") as f:
        gpus = json.load(f)

    cpu_index: Dict[str, str] = {}
    gpu_index: Dict[str, str] = {}

    def add_to_index(idx, item, hw_type):
        ext_id = item["external_id"]
        name = item.get("model_name") if hw_type == "cpu" else item.get("name")
        vendor = item.get("manufacturer") if hw_type == "cpu" else item.get("vendor")
        
        if not name:
            return
            
        # Basic name
        c_name = HardwareMapper._clean_string_static(name)
        idx[c_name] = ext_id
        
        # Vendor + name
        if vendor:
            c_vendor_name = HardwareMapper._clean_string_static(f"{vendor} {name}")
            idx[c_vendor_name] = ext_id
            
        # Aliases
        aliases = item.get("aliases")
        if aliases:
            for a in aliases.split(","):
                idx[HardwareMapper._clean_string_static(a.strip())] = ext_id

    for c in cpus:
        add_to_index(cpu_index, c, "cpu")

    for g in gpus:
        add_to_index(gpu_index, g, "gpu")

    return cpu_index, gpu_index


class HardwareMapper:
    def __init__(self, cpu_index_path=None, gpu_index_path=None):
        cpu_path = Path(cpu_index_path) if cpu_index_path else DEFAULT_CPU_PATH
        gpu_path = Path(gpu_index_path) if gpu_index_path else DEFAULT_GPU_PATH
        self.cpu_index, self.gpu_index = _load_and_build_indexes(str(cpu_path), str(gpu_path))

    @staticmethod
    def _clean_string_static(text: str) -> str:
        text = text.lower()
        text = re.sub(r'\(r\)|\(tm\)', '', text)
        text = text.replace('-', ' ')
        text = text.replace('@', ' ')
        text = text.replace(',', ' ')
        
        # Normalize memory sizes (e.g., 6gb -> 6 gb)
        text = re.sub(r'(\d+)\s*gb\b', r'\1 gb', text)
        text = re.sub(r'(\d+)\s*mb\b', r'\1 mb', text)
        
        # Remove generic fillers
        fillers = [
            r'\bcpu\b', r'\bgpu\b', r'\bgraphics\b', r'\bprocessor\b', 
            r'\bequivalent\b', r'\bor higher\b', r'\bor better\b', 
            r'\bcard\b', r'\bdedicated\b', r'\bcompatible\b', r'\bvideo memory\b'
        ]
        for filler in fillers:
            text = re.sub(filler, '', text)
            
        # Standardize spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _clean_string(self, text: str) -> str:
        return HardwareMapper._clean_string_static(text)

    def extract_candidates(self, raw_str: str) -> List[str]:
        if not raw_str: return []
        # Split on OR, /, |
        parts = re.split(r'\b(?:or)\b|/|\|', raw_str, flags=re.IGNORECASE)
        candidates = []
        for p in parts:
            # Also split on commas if it looks like a list of distinct cards.
            # Some listings are like "GTX 1060, RX 580"
            subparts = re.split(r',\s*(?=(?:amd|intel|nvidia|geforce|radeon))', p, flags=re.IGNORECASE)
            for sp in subparts:
                clean = sp.strip()
                if clean:
                    candidates.append(clean)
        return candidates
        
    def _parse_generic_cpu(self, raw_str: str) -> Optional[Dict[str, Any]]:
        raw_lower = raw_str.lower()
        cores = None
        clock = None
        if "dual core" in raw_lower or "dual-core" in raw_lower:
            cores = 2
        elif "quad core" in raw_lower or "quad-core" in raw_lower:
            cores = 4
        clock_match = re.search(r'([\d\.]+)\s*ghz', raw_lower)
        if clock_match:
            clock = float(clock_match.group(1))
            
        if (cores or clock) and not any(b in raw_lower for b in ["i3", "i5", "i7", "i9", "ryzen", "pentium", "athlon", "fx-"]):
            return {
                "type": "generic_cpu",
                "attributes": {"cores": cores, "clock_ghz": clock},
                "raw": raw_str,
                "match_method": "generic",
                "confidence": "high"
            }
        return None
        
    def _parse_generic_gpu(self, raw_str: str) -> Optional[Dict[str, Any]]:
        raw_lower = raw_str.lower()
        vram = None
        dx = None
        vram_match = re.search(r'([\d\.]+)\s*gb\s*vram', raw_lower)
        if not vram_match:
            vram_match = re.search(r'([\d\.]+)\s*gb', raw_lower)
        if vram_match:
            vram = float(vram_match.group(1))
        dx_match = re.search(r'directx\s*(\d+)', raw_lower)
        if dx_match:
            dx = int(dx_match.group(1))
            
        if (vram or dx) and not any(b in raw_lower for b in ["gtx", "rtx", "rx", "radeon", "hd", "iris", "gts"]):
            return {
                "type": "generic_gpu",
                "attributes": {"vram_gb": vram, "directx": dx},
                "raw": raw_str,
                "match_method": "generic",
                "confidence": "high"
            }
        return None

    @functools.lru_cache(maxsize=4096)
    def match_candidate(self, candidate_raw: str, hw_type: str) -> Dict[str, Any]:
        cleaned = self._clean_string(candidate_raw)
        if not cleaned:
            return {
                "raw": candidate_raw,
                "normalized_id": None,
                "match_method": "none",
                "confidence": "unresolved",
                "score": 0
            }

        index = self.cpu_index if hw_type == "cpu" else self.gpu_index
        
        # 1. Exact / Alias Match
        if cleaned in index:
            return {
                "raw": candidate_raw,
                "normalized_id": index[cleaned],
                "match_method": "exact",
                "confidence": "high",
                "score": 100.0
            }
            
        cleaned_no_space = cleaned.replace(" ", "")
        for key, hw_id in index.items():
            if key.replace(" ", "") == cleaned_no_space:
                return {
                    "raw": candidate_raw,
                    "normalized_id": hw_id,
                    "match_method": "alias",
                    "confidence": "high",
                    "score": 100.0
                }

        # 2. Fuzzy Match
        results = process.extract(cleaned, index.keys(), scorer=fuzz.WRatio, limit=5)
        if not results:
            return {
                "raw": candidate_raw,
                "normalized_id": None,
                "match_method": "none",
                "confidence": "unresolved",
                "score": 0
            }
            
        best_score = results[0][1]
        
        if best_score < 75.0:
            return {
                "raw": candidate_raw,
                "normalized_id": None,
                "match_method": "none",
                "confidence": "unresolved",
                "score": round(best_score, 1)
            }
            
        # Ambiguity check
        top_candidates = []
        for r in results:
            if best_score - r[1] <= 3.0: # Close enough to be considered a tie or near-tie
                hw_id = index[r[0]]
                if hw_id not in [tc['id'] for tc in top_candidates]:
                    top_candidates.append({"id": hw_id, "score": r[1], "key": r[0]})
                    
        if len(top_candidates) > 1:
            return {
                "raw": candidate_raw,
                "normalized_id": None,
                "match_method": "fuzzy",
                "score": round(best_score, 1),
                "confidence": "ambiguous",
                "ambiguous_candidates": [tc['id'] for tc in top_candidates]
            }
            
        # Single top candidate
        confidence = "high" if best_score >= 88.0 else "medium"
        return {
            "raw": candidate_raw,
            "normalized_id": top_candidates[0]['id'],
            "match_method": "fuzzy",
            "score": round(best_score, 1),
            "confidence": confidence
        }

    def normalize_requirements(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        norm = {
            "game_id": parsed.get("game_id"),
            "title": parsed.get("title"),
            "source": parsed.get("source"),
            "minimum": {k: v for k, v in parsed["minimum"].items() if k not in ["cpu", "gpu"]},
            "recommended": {k: v for k, v in parsed["recommended"].items() if k not in ["cpu", "gpu"]},
            "raw_requirements": parsed["raw_requirements"]
        }
        norm["minimum"]["cpu"] = self._process_hw_list(parsed["minimum"].get("cpu", []), "cpu")
        norm["minimum"]["gpu"] = self._process_hw_list(parsed["minimum"].get("gpu", []), "gpu")
        norm["recommended"]["cpu"] = self._process_hw_list(parsed["recommended"].get("cpu", []), "cpu")
        norm["recommended"]["gpu"] = self._process_hw_list(parsed["recommended"].get("gpu", []), "gpu")
        return norm

    def _process_hw_list(self, raw_list: List[str], hw_type: str) -> List[Dict[str, Any]]:
        results = []
        for raw_str in raw_list:
            # Handle generics
            gen = self._parse_generic_cpu(raw_str) if hw_type == "cpu" else self._parse_generic_gpu(raw_str)
            if gen:
                results.append(gen)
                continue
                    
            candidates = self.extract_candidates(raw_str)
            
            # Form alternatives structure
            alt_res = {
                "type": hw_type,
                "alternatives": [],
                "raw": raw_str,
                "confidence": "unresolved"
            }
            
            highest_conf_score = -1
            confidence_levels = {"high": 3, "medium": 2, "ambiguous": 1, "unresolved": 0, "none": 0}
            
            for c in candidates:
                match = self.match_candidate(c, hw_type)
                if match.get("normalized_id"):
                    alt_res["alternatives"].append(match["normalized_id"])
                    
                conf_val = confidence_levels.get(match.get("confidence", "none"), 0)
                if conf_val > highest_conf_score:
                    highest_conf_score = conf_val
                    alt_res["confidence"] = match.get("confidence", "unresolved")
                
                # Copy over debug fields for the first or highest confidence match
                if "match_method" not in alt_res or conf_val >= highest_conf_score:
                    alt_res["match_method"] = match.get("match_method", "none")
                    alt_res["score"] = match.get("score", 0)
                    if match.get("ambiguous_candidates"):
                        alt_res["ambiguous_candidates"] = match["ambiguous_candidates"]
                        
            if alt_res["alternatives"]:
                # Ensure unique
                alt_res["alternatives"] = list(dict.fromkeys(alt_res["alternatives"]))
                
            results.append(alt_res)
        return results
