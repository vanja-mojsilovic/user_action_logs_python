"""Connectivity test: fetch restaurant names from SpotHopper and write them
to the 'restaurants' tab. Validates the SpotHopper fetch + sheet-write path.

Spot ids come from the 'result' tab (step 1 output); falls back to a single
test id if that's empty. Limited to a handful of rows so it stays a quick test.
"""
import os
import time
from dotenv import load_dotenv

from sheets_client import read_column, write_table
from sh_client import SpotHopperClient

load_dotenv()

SHEET_ID = os.environ["SHEET_ID"]
SH_BASE_URL = os.environ.get("SH_BASE_URL", "https://www.spothopperapp.com")
SH_COOKIE = os.environ.get("SPOTHOPPER_COOKIES", "")
RESULT_TAB = os.environ.get("RESULT_TAB") or "spot_id_results"
LIMIT = int(os.environ.get("TEST_LIMIT", "25"))  # keep the test small

FALLBACK_IDS = ["321387"]


def main():
    try:
        spot_ids = read_column(SHEET_ID, RESULT_TAB)
    except Exception as exc:
        print(f"Couldn't read '{RESULT_TAB}' tab ({exc}); using fallback id.")
        spot_ids = []
    if not spot_ids:
        spot_ids = FALLBACK_IDS
    spot_ids = spot_ids[:LIMIT]
    print(f"Fetching names for {len(spot_ids)} spot(s)...")

    client = SpotHopperClient(SH_BASE_URL, SH_COOKIE)
    rows = []
    for sid in spot_ids:
        try:
            name = client.get_spot_name(int(sid)) or ""
        except Exception as exc:
            name = f"ERROR: {exc}"
        print(f"  {sid}: {name}")
        rows.append([sid, name])
        time.sleep(0.2)  # be gentle

    n = write_table(SHEET_ID, ["Spot ID", "Restaurant Name"], rows, "restaurants")
    print(f"Wrote {n} rows to 'restaurants' tab.")


if __name__ == "__main__":
    main()