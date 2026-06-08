#!/usr/bin/env python3
"""
graffmap Parallel Data Preparation
Uses multiple CPU cores to process photos in parallel - much faster!
"""

import os
import json
import sys
import argparse
import glob
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from PIL import Image


def get_photo_files(photo_dir):
    """Get all photo files (deduplicated — NTFS is case-insensitive)."""
    print(f"Scanning {photo_dir}...")
    seen = set()
    files = []
    for ext in ['jpg', 'jpeg']:
        for f in glob.glob(os.path.join(photo_dir, '**', f'*.{ext}'), recursive=True):
            key = os.path.normcase(os.path.abspath(f))
            if key not in seen:
                seen.add(key)
                files.append(f)
    return files


def split_into_chunks(items, num_chunks):
    """Split list into roughly equal chunks."""
    chunk_size = len(items) // num_chunks + 1
    return [items[i:i+chunk_size] for i in range(0, len(items), chunk_size)]


def process_chunk(args):
    """Process a chunk of files with exiftool (runs in parallel)."""
    chunk_files, chunk_id = args

    # Create temp file with file list
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as tmp:
        for f in chunk_files:
            tmp.write(f"{f}\n")
        file_list = tmp.name

    try:
        # Run exiftool on this chunk
        cmd = [
            'exiftool',
            '-n', '-fast2',
            '-if', '$GPSLatitude',  # Only GPS photos
            '-gpslatitude', '-gpslongitude',
            '-datetimeoriginal', '-filename', '-SourceFile',
            '-charset', 'UTF8',
            '-json',
            '-@', file_list
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        os.unlink(file_list)  # Cleanup

        if result.returncode == 0 and result.stdout:
            data = json.loads(result.stdout)
            return chunk_id, data
        return chunk_id, []

    except Exception as e:
        print(f"Error in chunk {chunk_id}: {e}")
        return chunk_id, []


def parallel_extract_gps(photo_dir, output_json, num_workers=None):
    """
    Extract GPS data using parallel processing.
    Uses all CPU cores by default.
    """
    import multiprocessing

    if num_workers is None:
        num_workers = multiprocessing.cpu_count()

    print(f"\n=== Parallel GPS Extraction (using {num_workers} CPU cores) ===")

    # Get all files
    photo_files = get_photo_files(photo_dir)
    total = len(photo_files)
    print(f"Found {total:,} image files")

    # Split into chunks for parallel processing
    chunks = split_into_chunks(photo_files, num_workers * 4)  # 4x workers for better load balancing
    print(f"Split into {len(chunks)} chunks for parallel processing")

    # Process chunks in parallel
    all_data = []
    completed = 0

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        # Submit all chunks
        futures = {executor.submit(process_chunk, (chunk, i)): i
                  for i, chunk in enumerate(chunks)}

        # Collect results as they complete
        for future in as_completed(futures):
            chunk_id, data = future.result()
            all_data.extend(data)
            completed += 1
            print(f"  Chunk {completed}/{len(chunks)} complete | Total GPS photos: {len(all_data):,}")

    # Write combined results
    print(f"\nWriting {len(all_data):,} photos to {output_json}...")
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False)

    print(f"✓ Success: {len(all_data):,} photos with GPS data")
    return len(all_data)


def create_thumbnail(args):
    """Create a single thumbnail (for parallel processing)."""
    photo_path, thumb_dir, thumb_size = args

    filename = os.path.basename(photo_path)
    thumb_path = os.path.join(thumb_dir, filename)

    if os.path.exists(thumb_path):
        return True

    try:
        with Image.open(photo_path) as img:
            img.thumbnail(thumb_size, Image.Resampling.LANCZOS)
            img.save(thumb_path, quality=85, optimize=True)
        return True
    except:
        return False


def parallel_create_thumbnails(photos, thumb_dir, thumb_size, num_workers=None):
    """Create thumbnails in parallel."""
    import multiprocessing

    if num_workers is None:
        num_workers = multiprocessing.cpu_count()

    print(f"\n=== Creating thumbnails in parallel ({num_workers} workers) ===")
    os.makedirs(thumb_dir, exist_ok=True)

    # Prepare arguments for parallel processing
    tasks = [(p["SourceFile"], thumb_dir, thumb_size)
             for p in photos if "SourceFile" in p]

    created = 0
    total = len(tasks)

    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = {executor.submit(create_thumbnail, task): i
                  for i, task in enumerate(tasks)}

        for future in as_completed(futures):
            if future.result():
                created += 1
            if created % 100 == 0:
                print(f"  Created {created:,}/{total:,} thumbnails...")

    print(f"✓ Created {created:,} thumbnails")
    return created


def create_geojson(input_json, output_geojson, thumb_dir):
    """Convert JSON to GeoJSON."""
    print(f"\n=== Creating GeoJSON ===")

    with open(input_json, 'r', encoding='utf-8') as f:
        photos = json.load(f)

    features = []
    for p in photos:
        try:
            lat = float(p["GPSLatitude"])
            lon = float(p["GPSLongitude"])

            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                continue

            filename = p.get("FileName", "unknown")

            properties = {
                "filename": filename,
                "datetime": p.get("DateTimeOriginal", ""),
                "thumb": f"{thumb_dir}/{filename}",
                "original": p.get("SourceFile", "")
            }

            feature = {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": properties
            }
            features.append(feature)
        except:
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open(output_geojson, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print(f"✓ Created {output_geojson} with {len(features):,} features")


def main():
    parser = argparse.ArgumentParser(
        description='Parallel photo processing - uses all CPU cores',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=r"""
Example:
  # Process with all CPU cores (FASTEST!)
  python prepare_data_parallel.py .\photos\ --thumb-size 500 500

  # Use specific number of workers
  python prepare_data_parallel.py .\photos\ --workers 8
        """
    )

    parser.add_argument('photo_dir', help='Directory containing photos')
    parser.add_argument('--workers', type=int, default=None,
                       help='Number of parallel workers (default: all CPU cores)')
    parser.add_argument('--thumb-size', type=int, nargs=2, default=[500, 500],
                       metavar=('WIDTH', 'HEIGHT'))
    parser.add_argument('--thumb-dir', default='thumbnails')
    parser.add_argument('--output-json', default='photos.json')
    parser.add_argument('--output-geojson', default='photos.geojson')

    args = parser.parse_args()

    if not os.path.isdir(args.photo_dir):
        print(f"Error: Directory not found: {args.photo_dir}")
        sys.exit(1)

    # Step 1: Extract GPS data in parallel
    num_photos = parallel_extract_gps(args.photo_dir, args.output_json, args.workers)

    if num_photos == 0:
        print("No photos with GPS data found!")
        sys.exit(0)

    # Step 2: Load data
    with open(args.output_json, 'r', encoding='utf-8') as f:
        photos = json.load(f)

    # Step 3: Create thumbnails in parallel
    parallel_create_thumbnails(photos, args.thumb_dir, tuple(args.thumb_size), args.workers)

    # Step 4: Create GeoJSON
    create_geojson(args.output_json, args.output_geojson, args.thumb_dir)

    print("\n=== Done! ===")


if __name__ == '__main__':
    main()
