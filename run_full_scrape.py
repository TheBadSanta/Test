"""
Full detail scrape using URLs from the existing transportation_companies.csv.
Writes results incrementally to transportation_companies_detailed.csv.
Supports resuming — skips URLs already scraped.
"""
import csv
import os
import sys
from dataclasses import asdict

from scraper import Company, RekvizitaiScraper, logger

INPUT_CSV = "transportation_companies.csv"
OUTPUT_CSV = "transportation_companies_detailed.csv"
DELAY = 1.0

def get_all_urls():
    with open(INPUT_CSV, encoding="utf-8") as f:
        return [r["url"] for r in csv.DictReader(f) if r["url"]]

def get_done_urls():
    if not os.path.exists(OUTPUT_CSV):
        return set()
    with open(OUTPUT_CSV, encoding="utf-8") as f:
        return {r["url"] for r in csv.DictReader(f) if r["url"]}

def main():
    all_urls = get_all_urls()
    done_urls = get_done_urls()
    remaining = [u for u in all_urls if u not in done_urls]

    logger.info("Total: %d, Already done: %d, Remaining: %d",
                len(all_urls), len(done_urls), len(remaining))

    if not remaining:
        logger.info("All companies already scraped!")
        return

    fieldnames = list(asdict(Company()).keys())
    scraper = RekvizitaiScraper(delay=DELAY)

    # Open in append mode if file exists, otherwise write header
    write_header = not os.path.exists(OUTPUT_CSV) or os.path.getsize(OUTPUT_CSV) == 0
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        for i, url in enumerate(remaining, 1):
            try:
                company = scraper.get_company(url)
                writer.writerow(asdict(company))
                f.flush()
                if i % 50 == 0 or i <= 5:
                    logger.info("(%d/%d) %s", i, len(remaining), company.name)
            except Exception as e:
                logger.error("(%d/%d) Failed %s: %s", i, len(remaining), url, e)

    total_done = len(get_done_urls())
    logger.info("Done! %d companies in %s", total_done, OUTPUT_CSV)

if __name__ == "__main__":
    main()
