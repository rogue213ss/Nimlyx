import json
import os

SOURCE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "hardware", "source", "all-gpus.json"))
OUTPUT_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "hardware", "normalized", "gpus.json"))

def main():
    with open(SOURCE_PATH, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    normalized_gpus = []
    excluded = []
    duplicates = []
    seen_ids = set()

    stats = {
        'raw_count': len(raw_data),
        'vendors': {'NVIDIA': 0, 'AMD': 0, 'Intel': 0},
        'categories': {'Consumer': 0, 'Professional': 0, 'Integrated': 0},
        'datacenter_excluded': 0
    }

    for record in raw_data:
        name = record.get('name', '')
        vendor_raw = record.get('vendor', '').lower()
        generation = (record.get('generation') or '').lower()
        gpu_name = record.get('gpuName', '')
        bus_interface = record.get('busInterface', '')
        architecture = record.get('architecture', '')

        # 1. Vendor normalization
        vendor = None
        if 'nvidia' in vendor_raw or 'nvidia' in name.lower():
            vendor = 'NVIDIA'
        elif 'amd' in vendor_raw or 'ati' in vendor_raw or 'amd' in name.lower() or 'radeon' in name.lower():
            vendor = 'AMD'
        elif 'intel' in vendor_raw or 'intel' in name.lower():
            vendor = 'Intel'
        
        if not vendor:
            excluded.append(record)
            continue

        # 2. Exclude datacenter / compute hardware
        is_datacenter = False
        name_lower = name.lower()
        
        if 'tesla' in name_lower and vendor == 'NVIDIA':
            is_datacenter = True
        if 'instinct' in name_lower:
            is_datacenter = True
        if 'data center' in generation or 'datacenter' in generation or 'accelerator' in generation:
            is_datacenter = True
        if 'grid' in name_lower and vendor == 'NVIDIA':
            is_datacenter = True
        # Exclude specific compute cards by regex or keyword
        for prefix in ['a100 ', 'h100 ', 'v100 ', 'p100 ']:
            if name_lower.startswith(prefix) or name_lower == prefix.strip():
                is_datacenter = True
                
        if 'arctic sound' in name_lower or 'ponte vecchio' in name_lower:
            is_datacenter = True
        
        if is_datacenter:
            stats['datacenter_excluded'] += 1
            excluded.append(record)
            continue

        # 3. Classify Category
        category = 'Consumer'
        if any(kw in name_lower for kw in ['quadro', 'firepro', 'radeon pro', 'rtx a', 'rtx 4000 sff', 'rtx 5000 ada', 'rtx 6000 ada', 'rtx 4000 ada']):
            category = 'Professional'
        elif bus_interface == 'IGP' or any(kw in name_lower for kw in ['uhd ', 'iris', 'vega 3', 'vega 8', 'vega 11', 'hd graphics', 'arc graphics']):
            category = 'Integrated'
        elif 'integrated' in generation:
            category = 'Integrated'

        # 4. Generate stable external_id
        ext_id = record.get('id')
        if not ext_id:
            ext_id = f"{vendor.lower()}-{name.replace(' ', '-').lower()}"
            
        if ext_id in seen_ids:
            duplicates.append(record)
            continue
            
        seen_ids.add(ext_id)

        # 5. Extract and normalize fields
        norm_rec = {
            'external_id': ext_id,
            'name': name,
            'vendor': vendor,
            'category': category,
            'architecture': architecture if architecture else None,
            'vram_gb': record.get('memorySize'),
            'memory_type': record.get('memoryType'),
            'memory_bus_bits': record.get('memoryBus'),
            'base_clock_mhz': record.get('baseClock'),
            'boost_clock_mhz': record.get('boostClock'),
            'memory_clock_mhz': record.get('memoryClock'),
            'shaders': record.get('shaders'),
            'tdp_w': record.get('tdp'),
            'release_date': record.get('releaseDate'),
            'process_node_nm': record.get('processSize'),
            'source': {
                'file': 'all-gpus.json',
                'source_id': ext_id
            }
        }

        normalized_gpus.append(norm_rec)
        stats['vendors'][vendor] += 1
        stats['categories'][category] += 1

    # Write normalized output
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(normalized_gpus, f, indent=2)

    # Validation summary
    print(f"Raw GPU records: {stats['raw_count']}")
    print(f"Normalized GPU records: {len(normalized_gpus)}")
    print(f"Excluded records: {len(excluded)}")
    print(f"Potential duplicates: {len(duplicates)}")
    print(f"\nNVIDIA: {stats['vendors']['NVIDIA']}")
    print(f"AMD: {stats['vendors']['AMD']}")
    print(f"Intel: {stats['vendors']['Intel']}")
    print(f"\nConsumer: {stats['categories']['Consumer']}")
    print(f"Professional/workstation: {stats['categories']['Professional']}")
    print(f"Integrated: {stats['categories']['Integrated']}")
    print(f"\nData-center/compute excluded: {stats['datacenter_excluded']}")
    
    print("\nRepresentative Samples:")
    
    def print_sample(condition):
        for g in normalized_gpus:
            if condition(g):
                print(json.dumps(g, indent=2))
                return

    print("\n--- GeForce / RTX ---")
    print_sample(lambda g: 'RTX' in g['name'] and g['category'] == 'Consumer')
    print("\n--- Quadro / RTX Professional ---")
    print_sample(lambda g: g['category'] == 'Professional' and g['vendor'] == 'NVIDIA')
    print("\n--- Radeon / Radeon RX ---")
    print_sample(lambda g: 'Radeon RX' in g['name'] and g['category'] == 'Consumer')
    print("\n--- Radeon Pro / FirePro ---")
    print_sample(lambda g: ('Radeon Pro' in g['name'] or 'FirePro' in g['name']) and g['category'] == 'Professional')
    print("\n--- Intel Arc ---")
    print_sample(lambda g: 'Arc' in g['name'] and g['vendor'] == 'Intel' and g['category'] == 'Consumer')
    print("\n--- Integrated GPU ---")
    print_sample(lambda g: g['category'] == 'Integrated')

if __name__ == "__main__":
    main()
