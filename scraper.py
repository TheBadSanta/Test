"""
Web scraper for rekvizitai.vz.lt - Lithuanian company directory.

Scrapes company information including registration details, contact info,
and business metadata from the public company registry.
"""

import csv
import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_URL = "https://rekvizitai.vz.lt"
SEARCH_URL = f"{BASE_URL}/en/company-search/{{page}}/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
DEFAULT_DELAY = 1.5  # seconds between requests


@dataclass
class Company:
    name: str = ""
    registration_code: str = ""
    vat: str = ""
    address: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""
    manager: str = ""
    company_type: str = ""
    status: str = ""
    registration_date: str = ""
    share_capital: str = ""
    employees: str = ""
    activities: str = ""
    url: str = ""


class RekvizitaiScraper:
    """Scraper for rekvizitai.vz.lt Lithuanian company directory."""

    def __init__(self, delay: float = DEFAULT_DELAY):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.delay = delay

    def _get(self, url: str) -> BeautifulSoup:
        """Fetch a URL and return parsed BeautifulSoup."""
        time.sleep(self.delay)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    def _post(self, url: str, data: dict) -> BeautifulSoup:
        """POST to a URL and return parsed BeautifulSoup."""
        time.sleep(self.delay)
        resp = self.session.post(url, data=data, timeout=30)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        name: str = "",
        company_code: str = "",
        vat: str = "",
        city: str = "",
        street: str = "",
        search_word: str = "",
        max_pages: int = 1,
    ) -> list[str]:
        """
        Search for companies and return a list of company page URLs.

        Args:
            name: Company name (partial match).
            company_code: 9-digit registration code.
            vat: VAT number.
            city: City code (e.g. "2000090" for Vilnius).
            street: Street name.
            search_word: Keyword search.
            max_pages: Maximum number of result pages to scrape.

        Returns:
            List of absolute URLs to company detail pages.
        """
        form_data = {
            "name": name,
            "company_code": company_code,
            "codepvm": vat,
            "location": city,
            "street": street,
            "search_word": search_word,
            "type": "unlimited",
        }
        # Remove empty values
        form_data = {k: v for k, v in form_data.items() if v}

        all_urls: list[str] = []

        for page in range(1, max_pages + 1):
            url = SEARCH_URL.format(page=page)
            logger.info("Searching page %d: %s", page, url)

            soup = self._post(url, form_data)
            urls = self._parse_search_results(soup)

            if not urls:
                logger.info("No more results on page %d, stopping.", page)
                break

            all_urls.extend(urls)
            logger.info("Found %d companies on page %d.", len(urls), page)

            # Check if there is a next page
            if not self._has_next_page(soup, page):
                break

        logger.info("Total companies found: %d", len(all_urls))
        return all_urls

    def _parse_search_results(self, soup: BeautifulSoup) -> list[str]:
        """Extract company URLs from a search results page."""
        urls = []
        for div in soup.select("div.company"):
            link = div.select_one("a.company-title")
            if link and link.get("href"):
                urls.append(urljoin(BASE_URL, link["href"]))
        return urls

    def _has_next_page(self, soup: BeautifulSoup, current_page: int) -> bool:
        """Check if there is a next page of results."""
        next_page = current_page + 1
        pagination = soup.select("a.page-link")
        for link in pagination:
            href = link.get("href", "")
            if f"company-search/{next_page}" in href:
                return True
        return False

    # ------------------------------------------------------------------
    # Company detail
    # ------------------------------------------------------------------

    def get_company(self, url: str) -> Company:
        """
        Scrape a single company's details from its page.

        Args:
            url: Full URL to the company page on rekvizitai.vz.lt.

        Returns:
            Company dataclass with all scraped fields.
        """
        logger.info("Scraping company: %s", url)
        soup = self._get(url)
        company = Company(url=url)

        # Company name from h1
        h1 = soup.select_one("h1.title")
        if h1:
            company.name = h1.get_text(strip=True)

        # Parse the info table rows (search all tables in main content)
        for row in soup.select("table tr"):
            label_td = row.select_one("td.name")
            value_td = row.select_one("td.value")
            if not label_td or not value_td:
                continue

            label = label_td.get_text(strip=True).lower()
            value = self._extract_value(value_td)

            if "registration code" in label:
                company.registration_code = value
            elif label == "vat":
                company.vat = value
            elif "email" in label:
                # Skip - email is behind a contact form
                pass
            elif label == "address":
                company.address = value
            elif "phone" in label and not company.phone:
                company.phone = value
            elif "website" in label:
                link = value_td.select_one("a[href]")
                company.website = link["href"] if link else value
            elif "manager" in label:
                company.manager = value
            elif "status" in label:
                company.status = value
            elif "type" in label or "legal form" in label:
                company.company_type = value
            elif "registered" in label or "registration date" in label:
                company.registration_date = value
            elif "share capital" in label:
                company.share_capital = value
            elif "employees" in label:
                # Extract just the number
                match = re.search(r"[\d,]+", value)
                company.employees = match.group(0) if match else value
            elif "activit" in label:
                company.activities = value

        # Activities from dedicated section
        activities_div = soup.select_one("div.activities-list")
        if activities_div:
            acts = [a.get_text(strip=True) for a in activities_div.select("a.activity")]
            if acts:
                company.activities = "; ".join(acts)

        # Fallback: parse the hidden textarea with pre-formatted info
        textarea = soup.select_one("textarea#company-copy")
        if textarea:
            self._enrich_from_textarea(company, textarea.get_text())

        return company

    @staticmethod
    def _extract_value(td) -> str:
        """Extract clean text from a value <td>, ignoring SVGs, buttons, and 'More' links."""
        # Remove SVGs, buttons, modals, and "More ›" links
        for tag in td.select("svg, button, [data-toggle='modal'], script"):
            tag.decompose()
        for a in td.select("a"):
            text = a.get_text(strip=True)
            if text.startswith("More") or text.startswith("›"):
                a.decompose()
        # Get direct text and first-level content
        parts = []
        for child in td.children:
            if hasattr(child, "get_text"):
                t = child.get_text(strip=True)
            else:
                t = str(child).strip()
            if t:
                parts.append(t)
        result = " ".join(parts).strip()
        # Clean up extra whitespace
        return " ".join(result.split())

    def _enrich_from_textarea(self, company: Company, text: str) -> None:
        """Fill missing fields from the hidden company-copy textarea."""
        for line in text.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("Company:") and not company.name:
                company.name = line.split(":", 1)[1].strip()
            elif line.startswith("Address:") and not company.address:
                company.address = line.split(":", 1)[1].strip()
            elif line.startswith("Phone:") and not company.phone:
                company.phone = line.split(":", 1)[1].strip()
            elif line.startswith("Registration code:") and not company.registration_code:
                company.registration_code = line.split(":", 1)[1].strip()
            elif line.startswith("VAT:") and not company.vat:
                company.vat = line.split(":", 1)[1].strip()
            elif line.startswith("Manager:") and not company.manager:
                company.manager = line.split(":", 1)[1].strip()

    # ------------------------------------------------------------------
    # Batch scraping
    # ------------------------------------------------------------------

    def scrape_companies(self, urls: list[str]) -> list[Company]:
        """Scrape details for a list of company URLs."""
        companies = []
        for i, url in enumerate(urls, 1):
            try:
                company = self.get_company(url)
                companies.append(company)
                logger.info("(%d/%d) Scraped: %s", i, len(urls), company.name)
            except Exception as e:
                logger.error("Failed to scrape %s: %s", url, e)
        return companies

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    @staticmethod
    def to_csv(companies: list[Company], filename: str = "companies.csv") -> None:
        """Export list of companies to CSV."""
        if not companies:
            logger.warning("No companies to export.")
            return
        fieldnames = list(asdict(companies[0]).keys())
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for c in companies:
                writer.writerow(asdict(c))
        logger.info("Exported %d companies to %s", len(companies), filename)

    @staticmethod
    def to_json(companies: list[Company], filename: str = "companies.json") -> None:
        """Export list of companies to JSON."""
        data = [asdict(c) for c in companies]
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Exported %d companies to %s", len(companies), filename)


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Scrape Lithuanian company data from rekvizitai.vz.lt"
    )
    parser.add_argument("--name", default="", help="Company name to search for")
    parser.add_argument("--code", default="", help="Registration code")
    parser.add_argument("--vat", default="", help="VAT number")
    parser.add_argument("--city", default="", help="City code")
    parser.add_argument("--word", default="", help="Keyword search")
    parser.add_argument("--pages", type=int, default=1, help="Max result pages (default: 1)")
    parser.add_argument("--url", default="", help="Scrape a single company URL directly")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between requests in seconds")
    parser.add_argument("--output", default="companies", help="Output filename (without extension)")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="both", help="Output format")

    args = parser.parse_args()
    scraper = RekvizitaiScraper(delay=args.delay)

    if args.url:
        # Scrape a single company
        company = scraper.get_company(args.url)
        companies = [company]
    else:
        if not any([args.name, args.code, args.vat, args.city, args.word]):
            parser.error("Provide at least one search parameter (--name, --code, --vat, --city, --word) or --url")

        urls = scraper.search(
            name=args.name,
            company_code=args.code,
            vat=args.vat,
            city=args.city,
            search_word=args.word,
            max_pages=args.pages,
        )
        companies = scraper.scrape_companies(urls)

    if args.format in ("csv", "both"):
        scraper.to_csv(companies, f"{args.output}.csv")
    if args.format in ("json", "both"):
        scraper.to_json(companies, f"{args.output}.json")

    print(f"\nDone! Scraped {len(companies)} companies.")
    for c in companies[:5]:
        print(f"  - {c.name} ({c.registration_code})")
    if len(companies) > 5:
        print(f"  ... and {len(companies) - 5} more")


if __name__ == "__main__":
    main()
