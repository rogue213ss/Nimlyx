import os
import json

base_dir = "C:/Users/berli/OneDrive/Desktop/Nimlyx/seder/data/discovered/Intel"

cpus = [
    # Pentium
    {"name": "Intel Pentium 60", "manufacturer": "Intel", "family": "Pentium", "generation": "P5", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.06, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium 66", "manufacturer": "Intel", "family": "Pentium", "generation": "P5", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.066, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium MMX 166", "manufacturer": "Intel", "family": "Pentium", "generation": "P55C", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.166, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium II 233", "manufacturer": "Intel", "family": "Pentium II", "generation": "Klamath", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.233, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_II_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium II 266", "manufacturer": "Intel", "family": "Pentium II", "generation": "Klamath", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.266, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_II_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium III 450", "manufacturer": "Intel", "family": "Pentium III", "generation": "Katmai", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.45, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_III_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium 4 1.3", "manufacturer": "Intel", "family": "Pentium 4", "generation": "Willamette", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 1.3, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_4_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium D 820", "manufacturer": "Intel", "family": "Pentium D", "generation": "Smithfield", "is_desktop": True, "is_mobile": False, "cores": 2, "base_clock_ghz": 2.8, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_D_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium Dual-Core E2140", "manufacturer": "Intel", "family": "Pentium Dual-Core", "generation": "Conroe", "is_desktop": True, "is_mobile": False, "cores": 2, "base_clock_ghz": 1.6, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_Dual-Core_processors"], "audit_status": "verified"},
    {"name": "Intel Pentium G4560", "manufacturer": "Intel", "family": "Pentium", "generation": "Kaby Lake", "is_desktop": True, "is_mobile": False, "cores": 2, "base_clock_ghz": 3.5, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Pentium_processors"], "audit_status": "verified"},
    
    # Celeron
    {"name": "Intel Celeron 266", "manufacturer": "Intel", "family": "Celeron", "generation": "Covington", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.266, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Celeron_processors"], "audit_status": "verified"},
    {"name": "Intel Celeron 300A", "manufacturer": "Intel", "family": "Celeron", "generation": "Mendocino", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 0.3, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Celeron_processors"], "audit_status": "verified"},
    {"name": "Intel Celeron D 320", "manufacturer": "Intel", "family": "Celeron D", "generation": "Prescott", "is_desktop": True, "is_mobile": False, "cores": 1, "base_clock_ghz": 2.4, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Celeron_processors"], "audit_status": "verified"},
    {"name": "Intel Celeron G3930", "manufacturer": "Intel", "family": "Celeron", "generation": "Kaby Lake", "is_desktop": True, "is_mobile": False, "cores": 2, "base_clock_ghz": 2.9, "source_urls": ["https://en.wikipedia.org/wiki/List_of_Intel_Celeron_processors"], "audit_status": "verified"}
]

output_file_requested = "C:/Users/berli/OneDrive/Desktop/Nimlyx/seder/data/discovered/intel/pentium_celeron.json"
os.makedirs(os.path.dirname(output_file_requested), exist_ok=True)

with open(output_file_requested, "w") as f:
    json.dump(cpus, f, indent=2)

for cpu in cpus:
    family_dir = os.path.join(base_dir, cpu["family"])
    os.makedirs(family_dir, exist_ok=True)
    file_path = os.path.join(family_dir, f"{cpu['generation']}.json")
    
    existing = []
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            existing = json.load(f)
            if not isinstance(existing, list):
                existing = [existing]
    
    if not any(e["name"] == cpu["name"] for e in existing):
        existing.append(cpu)
        
    with open(file_path, "w") as f:
        json.dump(existing, f, indent=2)

print(f"Generated {len(cpus)} CPUs.")
