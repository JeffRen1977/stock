from __future__ import annotations

from dataclasses import dataclass

import requests


IMPORTANT_FORMS = {"8-K", "10-Q", "10-K", "4", "S-1"}

CIK_BY_SYMBOL = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "TSLA": "0001318605",
    "GOOGL": "0001652044",
    "GOOG": "0001652044",
    "AMZN": "0001018724",
    "META": "0001326801",
    "AMD": "0000002488",
    "SMCI": "0001375365",
    "ANET": "0001596532",
    "VRT": "0001674101",
}


@dataclass(frozen=True)
class SecFiling:
    symbol: str
    cik: str
    form_type: str
    filing_date: str
    accession_number: str
    filing_url: str
    title: str


class SecEdgarClient:
    submissions_url = "https://data.sec.gov/submissions/CIK{cik}.json"
    filing_base_url = "https://www.sec.gov/Archives/edgar/data/{cik_no_zero}/{accession_no_dash}/{primary_document}"

    def __init__(self, user_agent: str, timeout_seconds: float = 8.0) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "data.sec.gov",
            }
        )

    def get_recent_filings(self, symbol: str, limit: int = 5) -> list[SecFiling]:
        cik = CIK_BY_SYMBOL.get(symbol.upper())
        if not cik:
            return []

        response = self.session.get(
            self.submissions_url.format(cik=cik),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        recent = payload.get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])
        descriptions = recent.get("primaryDocDescription", [])

        filings = []
        for idx, form_type in enumerate(forms):
            if form_type not in IMPORTANT_FORMS:
                continue
            accession_number = _safe_index(accession_numbers, idx)
            primary_document = _safe_index(primary_documents, idx)
            if not accession_number or not primary_document:
                continue

            cik_no_zero = str(int(cik))
            accession_no_dash = accession_number.replace("-", "")
            filings.append(
                SecFiling(
                    symbol=symbol,
                    cik=cik,
                    form_type=form_type,
                    filing_date=_safe_index(filing_dates, idx) or "unknown",
                    accession_number=accession_number,
                    filing_url=self.filing_base_url.format(
                        cik_no_zero=cik_no_zero,
                        accession_no_dash=accession_no_dash,
                        primary_document=primary_document,
                    ),
                    title=_safe_index(descriptions, idx) or form_type,
                )
            )
            if len(filings) >= limit:
                break

        return filings


def _safe_index(values: list[str], idx: int) -> str:
    if idx >= len(values):
        return ""
    return str(values[idx]).strip()
