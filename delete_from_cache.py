#!/usr/bin/env python3
"""
delete_from_cache.py - Remove a handle from the MTLD cache
Usage: python3 delete_from_cache.py <handle>
"""
import os
import shelve
import sys

CACHE_PATH = os.environ.get("CACHE_PATH", "./data/mtld_cache")

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 delete_from_cache.py <handle>")
        sys.exit(1)

    handle = sys.argv[1]

    try:
        with shelve.open(CACHE_PATH) as cache:
            if handle in cache:
                entry = cache[handle]
                del cache[handle]
                print(f"✓ Deleted {handle} from cache")
                print(f"  MTLD: {entry['mtld']:.1f}, Date: {entry['date']}")
            else:
                print(f"✗ Handle '{handle}' not found in cache")
                print(f"\nAvailable handles:")
                for h in sorted(cache.keys()):
                    print(f"  - {h}")
                sys.exit(1)
    except Exception as e:
        print(f"Error accessing cache: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
