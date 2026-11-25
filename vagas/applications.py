"""Sincronização opcional, somente-leitura, de candidaturas em uma planilha CSV."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from urllib.parse import quote

from . import http
from .models import Job, canonical_url


def _header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower().translate(str.maketrans("áàâãéêíóôõúç", "aaaaeeiooouc")))


def _text(value: str) -> str:
    value = re.sub(r"\b(brazil|brasil|remote|remoto|latam|latin america)\b", "", value, flags=re.I)
    return _header(value)


def _url_from_config(cfg: dict) -> str:
    app = cfg.get("applications", {})
    if app.get("csv_url"):
        return str(app["csv_url"])
    match = re.search(r"/spreadsheets/d/([\w-]+)", str(app.get("spreadsheet_url", "")))
    if not match:
        return ""
    tab = quote(str(app.get("sheet", "Candidaturas 2026")))
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/gviz/tq?tqx=out:csv&sheet={tab}"


@dataclass(frozen=True)
class Application:
    title: str
    company: str
    status: str
    stage: str
    date: str
    url: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"status": self.status, "stage": self.stage, "date": self.date}


def read_applications(cfg: dict) -> list[Application]:
    """Lê a aba configurada; vazio quando a integração está desligada ou indisponível."""
    if not cfg.get("applications", {}).get("enabled", False):
        return []
    url = _url_from_config(cfg)
    if not url:
        return []
    response = http.get(url, timeout=20)
    if response is None:
        return []
    found: list[Application] = []
    for row in csv.DictReader(io.StringIO(response.text)):
        fields = {_header(k): (v or "").strip() for k, v in row.items() if k}
        title = fields.get("cargo", "")
        if title:
            found.append(Application(title, fields.get("empresa", ""), fields.get("status", "Candidatura registrada"),
                                     fields.get("etapaseletivo", ""), fields.get("datacandidatura", ""),
                                     fields.get("linkdavaga", fields.get("link", ""))))
    return found


def _same_job(job: Job, application: Application) -> bool:
    if application.url.startswith(("http://", "https://")):
        return canonical_url(job.url) == canonical_url(application.url)
    if application.company and _text(job.company) != _text(application.company):
        return False
    return _text(job.title) == _text(application.title)


def match_applications(jobs: list[Job], applications: list[Application]) -> dict[str, dict[str, str]]:
    """Relaciona por URL quando disponível; sem URL, por título e empresa normalizados."""
    matched: dict[str, dict[str, str]] = {}
    for job in jobs:
        for application in applications:
            if _same_job(job, application):
                matched[job.id] = application.to_dict()
                break
    return matched
