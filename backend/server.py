"""
server.py — Backend API Business Value Classifier
══════════════════════════════════════════════════
Orchestre les vrais scripts Python du projet :
  1. extraction_pdf.py    → PDF → Markdown (marker, optionnel si déjà fait)
  2. clean.py             → Markdown brut → Markdown nettoyé
  3. decoupage_en_phrases.py      → Mode Rapide : phrases plates
  4. decoupage_en_paragraphes.py  → Mode Expert : paragraphes + phrases
  5. multi_llm_phrase.py          → Classification Mode Rapide
  6. multi_llm_paragraph.py       → Classification Mode Expert
  7. Lecture des JSON résultats → réponses API au frontend

Routes :
  GET  /api/health
  GET  /api/dashboard
  GET  /api/documents
  GET  /api/results?documentId=<id>
  GET  /api/summary?documentId=<id>
  POST /api/analyze          (multipart: file=<pdf>, mode=rapide|expert)

CONFIGURATION : éditer la section "Chemins racines" ci-dessous.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import re
import sys
import tempfile
import threading
import time
from collections import Counter
from datetime import date
from hashlib import md5
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import email
import email.parser
import io

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION — arborescence
# ══════════════════════════════════════════════════════════════════════════════

PROJECT_ROOT  = Path("F:/Jihene/business_value_classification")
SCRIPTS_ROOT  = PROJECT_ROOT / "Business-Value-Knowledge-Graph/classification_test"

SCRIPT_EXTRACT         = Path("F:/Jihene/business_value_classification/Business-Value-Knowledge-Graph/classification_test/Extraction/extract.py")
SCRIPT_CLEAN           = SCRIPTS_ROOT / "decoupage/clean.py"
SCRIPT_PHRASES         = SCRIPTS_ROOT / "decoupage/decoupage_en_phrases.py"
SCRIPT_PARAGRAPHES     = SCRIPTS_ROOT / "decoupage/decoupage_en_paragraphes.py"
SCRIPT_CLASSIFY_PHRASE = SCRIPTS_ROOT / "classification/multi_llm_phrase.py"
SCRIPT_CLASSIFY_PARA   = SCRIPTS_ROOT / "classification/multi_llm_paragraph.py"

UPLOAD_WORK_DIR       = PROJECT_ROOT / "Business-Value-Knowledge-Graph/backend/work"
UPLOAD_CLEAN_DIR      = UPLOAD_WORK_DIR / "clean_markdown"
UPLOAD_PHRASES_DIR    = UPLOAD_WORK_DIR / "phrases"
UPLOAD_PARA_DIR       = UPLOAD_WORK_DIR / "paragraphes"
UPLOAD_RESULTS_PHRASE = UPLOAD_WORK_DIR / "resultats_phrases"
UPLOAD_RESULTS_PARA   = UPLOAD_WORK_DIR / "resultats_para"

DATA_ROOT = SCRIPTS_ROOT / "Decoupage"
ENV_FILE = SCRIPTS_ROOT / ".env"

HOST = "127.0.0.1"
PORT = 8000

CATEGORIES = ("ROI", "Notoriete", "Obligation", "Description")
UPLOAD_CLIENT = "Application Uploads"
# Mapping {chemin_résultat_absolu: nom_client} persistant sur disque
_CLIENT_OVERRIDES_FILE = UPLOAD_WORK_DIR / "client_overrides.json"
_CLIENT_OVERRIDES: dict[str, str] = {}
if _CLIENT_OVERRIDES_FILE.exists():
    try:
        _CLIENT_OVERRIDES = json.loads(_CLIENT_OVERRIDES_FILE.read_text(encoding="utf-8"))
    except Exception:
        _CLIENT_OVERRIDES = {}

def _persist_client_overrides() -> None:
    try:
        _CLIENT_OVERRIDES_FILE.write_text(
            json.dumps(_CLIENT_OVERRIDES, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════════
# CRÉATION DES DOSSIERS DE TRAVAIL
# ══════════════════════════════════════════════════════════════════════════════

for _d in (UPLOAD_WORK_DIR, UPLOAD_CLEAN_DIR, UPLOAD_PHRASES_DIR,
           UPLOAD_PARA_DIR, UPLOAD_RESULTS_PHRASE, UPLOAD_RESULTS_PARA):
    _d.mkdir(parents=True, exist_ok=True)

if ENV_FILE.exists():
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE)


# ══════════════════════════════════════════════════════════════════════════════
# CHARGEMENT DYNAMIQUE DES MODULES PYTHON
# ══════════════════════════════════════════════════════════════════════════════

def _noop_makedirs(*args, **kwargs) -> None:
    return None


def _configure_loaded_module(mod: Any, path: Path) -> None:
    resolved = path.resolve()

    if resolved == SCRIPT_PHRASES.resolve():
        mod.CLEAN_INPUT_DIR = str(UPLOAD_CLEAN_DIR)
        mod.PHRASES_OUT_DIR = str(UPLOAD_PHRASES_DIR)
        return

    if resolved == SCRIPT_PARAGRAPHES.resolve():
        mod.MARKDOWN_ROOT = str(UPLOAD_CLEAN_DIR)
        mod.SEGMENTS_OUTPUT_DIR = str(UPLOAD_PARA_DIR)
        return

    if resolved == SCRIPT_CLASSIFY_PHRASE.resolve():
        mod.SEGMENTS_INPUT_DIR = str(UPLOAD_PHRASES_DIR)
        mod.OUTPUT_DIR = str(UPLOAD_RESULTS_PHRASE)
        mod.SYSTEM_PROMPT_FILE = str(SCRIPTS_ROOT / "Classification/system_prompt_phrase.txt")
        mod.USER_PROMPT_FILE = str(SCRIPTS_ROOT / "Classification/user_prompt_phrase.txt")
        mod.QUESTIONS_FILE = str(SCRIPTS_ROOT / "Classification/liste_questions.txt")
        if hasattr(mod, "load_system_prompt"):
            mod.SYSTEM_PROMPT = mod.load_system_prompt(mod.SYSTEM_PROMPT_FILE)
        if hasattr(mod, "load_user_prompt_template"):
            mod.USER_PROMPT_TEMPLATE = mod.load_user_prompt_template(mod.USER_PROMPT_FILE)
        if hasattr(mod, "load_questions"):
            mod.QUESTIONS_DATA = mod.load_questions(mod.QUESTIONS_FILE)
        return

    if resolved == SCRIPT_CLASSIFY_PARA.resolve():
        mod.SEGMENTS_INPUT_DIR = str(UPLOAD_PARA_DIR)
        mod.OUTPUT_DIR = str(UPLOAD_RESULTS_PARA)
        mod.SYSTEM_PROMPT_FILE = str(SCRIPTS_ROOT / "Classification/system_prompt_paragraph.txt")
        mod.USER_PROMPT_FILE = str(SCRIPTS_ROOT / "Classification/user_prompt_paragraph.txt")
        mod.QUESTIONS_FILE = str(SCRIPTS_ROOT / "Classification/liste_questions.txt")
        if hasattr(mod, "load_system_prompt"):
            mod.SYSTEM_PROMPT = mod.load_system_prompt(mod.SYSTEM_PROMPT_FILE)
        if hasattr(mod, "load_user_prompt_template"):
            mod.USER_PROMPT_TEMPLATE = mod.load_user_prompt_template(mod.USER_PROMPT_FILE)
        if hasattr(mod, "load_questions"):
            mod.QUESTIONS_DATA = mod.load_questions(mod.QUESTIONS_FILE)


def _load_module(name: str, path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Script introuvable : {path}")
    from unittest.mock import patch

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de preparer le chargement du script : {path}")
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    with patch("os.makedirs", _noop_makedirs):
        try:
            spec.loader.exec_module(mod)
        except Exception as exc:
            sys.modules.pop(name, None)
            raise RuntimeError(f"Erreur pendant le chargement de {path.name}: {exc}") from exc
    _configure_loaded_module(mod, path)
    return mod


_module_cache: dict[str, Any] = {}
_module_lock  = threading.Lock()


def _get_module(name: str, path: Path):
    with _module_lock:
        if name not in _module_cache:
            _module_cache[name] = _load_module(name, path)
        return _module_cache[name]


def _mod_extract():     return _get_module("bvc_extract",  SCRIPT_EXTRACT)
def _mod_clean():       return _get_module("bvc_clean",    SCRIPT_CLEAN)
def _mod_phrases():     return _get_module("bvc_phrases",  SCRIPT_PHRASES)
def _mod_paragraphes(): return _get_module("bvc_para",     SCRIPT_PARAGRAPHES)
def _mod_clf_phrase():  return _get_module("bvc_clf_ph",   SCRIPT_CLASSIFY_PHRASE)
def _mod_clf_para():    return _get_module("bvc_clf_para", SCRIPT_CLASSIFY_PARA)


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS GÉNÉRIQUES
# ══════════════════════════════════════════════════════════════════════════════

def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _bad_request(handler, msg):  _json_response(handler, 400, {"error": msg})
def _not_found(handler):         _json_response(handler, 404, {"error": "Route introuvable"})


def _normalize_category(raw: Any) -> str:
    v = str(raw or "Description").strip().lower()
    if v.startswith("roi"):  return "ROI"
    if "not" in v:           return "Notoriete"
    if "obl" in v:           return "Obligation"
    return "Description"


def _doc_name_from_path(path: Path) -> str:
    name = path.stem
    name = re.sub(r"_(phrases|paragraphs|paragraphes)_classification$", "", name)
    return name.replace("_", " ").strip()


def _client_from_path(path: Path) -> str:
    key = str(path.resolve())
    if key in _CLIENT_OVERRIDES:
        return _CLIENT_OVERRIDES[key]
    try:
        path.relative_to(UPLOAD_WORK_DIR)
        return UPLOAD_CLIENT
    except ValueError:
        pass
    try:
        rel   = path.relative_to(DATA_ROOT)
        parts = rel.parts
        return parts[1] if len(parts) >= 3 else "Corpus"
    except ValueError:
        return "Corpus"



def _mode_from_path(path: Path) -> str:
    return "expert" if "paragraph" in str(path) else "rapide"


def _stable_id(path: Path) -> str:
    try:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        rel = str(path)
    return md5(rel.encode("utf-8")).hexdigest()[:12]


def _safe_stem(filename: str) -> str:
    stem = Path(filename).stem or "document"
    stem = re.sub(r"[^\w\- .()À-ÿ]+", " ", stem, flags=re.UNICODE)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:120] or "document"


# ══════════════════════════════════════════════════════════════════════════════
# EXTRACTION PDF → MARKDOWN via extract.py
# ══════════════════════════════════════════════════════════════════════════════

_MARKER_MODELS: dict | None = None
_MARKER_LOCK   = threading.Lock()


def _get_marker_models():
    global _MARKER_MODELS
    with _MARKER_LOCK:
        if _MARKER_MODELS is not None:
            return _MARKER_MODELS
        mod = _mod_extract()
        if not hasattr(mod, "load_marker_models"):
            raise RuntimeError(f"{SCRIPT_EXTRACT.name} ne contient pas load_marker_models().")
        if mod and hasattr(mod, "load_marker_models"):
            print("  [extract] Chargement des modèles marker...")
            _MARKER_MODELS = mod.load_marker_models()
            if _MARKER_MODELS:
                print("  [extract] Modèles marker prêts.")
            else:
                print("  [extract] Échec chargement modèles marker.")
        else:
            _MARKER_MODELS = None
    return _MARKER_MODELS


def _extract_pdf_to_markdown(pdf_path: Path) -> str:
    mod = _mod_extract()
    if not hasattr(mod, "extract_with_marker"):
        raise RuntimeError(f"{SCRIPT_EXTRACT.name} ne contient pas extract_with_marker().")

    if mod and hasattr(mod, "extract_with_marker"):
        models = _get_marker_models()
        if models:
            result = mod.extract_with_marker(str(pdf_path), models)
            if hasattr(mod, "clear_gpu_memory"):
                mod.clear_gpu_memory()
            md = result.get("markdown", "")
            if md.strip():
                return md
            if result.get("erreur"):
                raise RuntimeError(f"Erreur marker : {result['erreur']}")

    raise RuntimeError("extract.py n'a pas retourne de markdown exploitable.")



# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE D'ANALYSE — délégation aux vrais scripts
# ══════════════════════════════════════════════════════════════════════════════

def _step_clean_markdown(md_text: str) -> str:
    mod = _mod_clean()
    if not hasattr(mod, "clean_markdown"):
        raise RuntimeError(f"{SCRIPT_CLEAN.name} ne contient pas clean_markdown().")
    return mod.clean_markdown(md_text)


def _step_split_phrases(md_text: str, stem: str, source_folder: str) -> Path:
    mod = _mod_phrases()
    if not hasattr(mod, "parse_to_phrases"):
        raise RuntimeError(f"{SCRIPT_PHRASES.name} ne contient pas parse_to_phrases().")
    out_dir  = UPLOAD_PHRASES_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_phrases.json"

    if hasattr(mod, "_load_models") and not mod._NLP:
        mod._load_models()
    lang    = mod._detect_lang(md_text) if hasattr(mod, "_detect_lang") else "fr"
    phrases = mod.parse_to_phrases(md_text, f"{stem}.md", source_folder, lang)
    from dataclasses import asdict
    data = [asdict(p) if hasattr(p, "__dataclass_fields__") else p for p in phrases]

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _step_split_paragraphes(md_text: str, stem: str, source_folder: str) -> Path:
    mod = _mod_paragraphes()
    if not hasattr(mod, "parse_markdown"):
        raise RuntimeError(f"{SCRIPT_PARAGRAPHES.name} ne contient pas parse_markdown().")
    out_dir  = UPLOAD_PARA_DIR / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_paragraphs.json"

    if hasattr(mod, "_load_models") and not mod._NLP:
        mod._load_models()
    lang       = mod._detect_lang(md_text) if hasattr(mod, "_detect_lang") else "fr"
    paragraphs = mod.parse_markdown(md_text, f"{stem}.md", source_folder, lang)
    from dataclasses import asdict
    data = [asdict(p) if hasattr(p, "__dataclass_fields__") else p for p in paragraphs]

    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def _step_classify_phrases(json_path: Path, stem: str) -> Path:
    mod = _mod_clf_phrase()
    if not hasattr(mod, "process_file"):
        raise RuntimeError(f"{SCRIPT_CLASSIFY_PHRASE.name} ne contient pas process_file().")
    out_dir  = UPLOAD_RESULTS_PHRASE / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_phrases_classification.json"

    stats   = mod.StatsAccumulator(mod.MODELS_TO_USE)
    results = mod.process_file(json_path, mod.MODELS_TO_USE, stats)
    from dataclasses import asdict
    data = [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in results]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_path


def _step_classify_paragraphes(json_path: Path, stem: str) -> Path:
    mod = _mod_clf_para()
    if not hasattr(mod, "process_paragraphs_file"):
        raise RuntimeError(f"{SCRIPT_CLASSIFY_PARA.name} ne contient pas process_paragraphs_file().")
    out_dir  = UPLOAD_RESULTS_PARA / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}_paragraphs_classification.json"

    stats   = mod.StatsAccumulator(mod.MODELS_TO_USE)
    results = mod.process_paragraphs_file(json_path, mod.MODELS_TO_USE, stats)
    from dataclasses import asdict
    data = [asdict(r) if hasattr(r, "__dataclass_fields__") else r for r in results]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return out_path


# ══════════════════════════════════════════════════════════════════════════════
# FALLBACKS
# ══════════════════════════════════════════════════════════════════════════════

_ROI_KW = ("roi","retour","rentabilit","coût","cout","économie","economie","gain",
            "productivit","performance","automatisation","réduction","reduction",
            "temps","charge","revenu","profit","budget","optimisation")
_NOT_KW = ("notoriété","notoriete","image","attractiv","label","reconnaissance",
            "qualité de vie","qualite de vie","bien-être","bien etre","confort",
            "expérience","satisfaction","visibilit","innovation","usager")
_OBL_KW = ("obligation","réglement","reglement","réglementaire","reglementaire",
            "loi","norme","conformit","sécurité","securite","risque","prévention",
            "prevention","protection","sanction","rgpd","directive","obligatoire")


def _kw_score(text: str, kws: tuple) -> int:
    t = text.lower()
    return sum(1 for k in kws if k in t)


def _local_classify_phrase(item: dict) -> dict:
    phrase  = item.get("phrase", "")
    context = item.get("paragraph_context", "")
    full    = f"{context} {phrase}".strip()

    roi  = min(3, _kw_score(full, _ROI_KW))
    not_ = min(3, _kw_score(full, _NOT_KW))
    obl  = min(3, _kw_score(full, _OBL_KW))

    if max(roi, not_, obl) == 0:
        cat = "Description"
    else:
        cat = max([("ROI", roi), ("Obligation", obl), ("Notoriete", not_)],
                  key=lambda x: x[1])[0]

    conf = 0.62 if cat == "Description" else min(0.95, 0.72 + max(roi, not_, obl) * 0.08)
    responses = {
        "roi_1":      "oui" if roi >= 1 else "non",
        "roi_2":      "oui" if any(k in phrase.lower() for k in ("temps","charge","automatisation")) else "non",
        "roi_3":      "oui" if any(k in phrase.lower() for k in ("performance","résultat","resultat")) else "non",
        "notoriete_1":"oui" if any(k in phrase.lower() for k in ("bien-être","confort","qualité")) else "non",
        "notoriete_2":"oui" if any(k in phrase.lower() for k in ("label","image","attractiv")) else "non",
        "notoriete_3":"oui" if not_ >= 1 else "non",
        "obl_1":      "oui" if any(k in phrase.lower() for k in ("loi","norme","conformit")) else "non",
        "obl_2":      "oui" if any(k in phrase.lower() for k in ("sécurité","securite","risque")) else "non",
        "obl_3":      "oui" if obl >= 1 else "non",
    }
    return {
        **item,
        "categorie":             cat,
        "scores_roi":            roi,
        "scores_notoriete":      not_,
        "scores_obligation":     obl,
        "reponses_questions":    responses,
        "agreement_rates":       {k: conf for k in responses},
        "cost_usd_phrase":       0.0,
        "cost_eur_phrase":       0.0,
        "duration_s_phrase":     0.0,
        "detail_appels":         [],
        "classification_source": "local_rules_fallback",
    }


def _fallback_split_phrases(text: str, stem: str, folder: str) -> list[dict]:
    raw = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 15]
    return [{"phrase": s, "phrase_index": i, "source_file": f"{stem}.md",
             "source_folder": folder} for i, s in enumerate(raw)]


def _fallback_split_paragraphes(text: str, stem: str, folder: str) -> list[dict]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    result = []
    for pi, para in enumerate(paras):
        phrases = _fallback_split_phrases(para, stem, folder)
        result.append({
            "paragraph_index": pi,
            "section_title":   "",
            "source_file":     f"{stem}.md",
            "source_folder":   folder,
            "phrases":         phrases,
        })
    return result


# ══════════════════════════════════════════════════════════════════════════════
# ROUTE POST /api/analyze — pipeline complet
# ══════════════════════════════════════════════════════════════════════════════

def _parse_multipart(handler: BaseHTTPRequestHandler) -> dict:
    """Parse multipart/form-data sans cgi (supprimé en Python 3.13)."""
    content_type   = str(handler.headers.get("Content-Type", ""))  # ← str() forcé
    content_length = int(handler.headers.get("Content-Length", 0))
    body           = handler.rfile.read(content_length)

    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip().strip('"')
            break
    if not boundary:
        raise ValueError("Content-Type multipart/form-data sans boundary.")

    fields: dict = {}
    sep = ("--" + boundary).encode()

    for chunk in body.split(sep):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk in (b"--", b""):
            continue
        if chunk.startswith(b"--"):
            continue

        if b"\r\n\r\n" in chunk:
            raw_headers, content = chunk.split(b"\r\n\r\n", 1)
        elif b"\n\n" in chunk:
            raw_headers, content = chunk.split(b"\n\n", 1)
        else:
            continue

        content = content.rstrip(b"\r\n")
        msg     = email.parser.BytesHeaderParser().parsebytes(raw_headers + b"\r\n\r\n")
        disp    = str(msg.get("Content-Disposition", ""))  # ← str() forcé

        name = filename = None
        for item in disp.split(";"):
            item = item.strip()
            if item.startswith('name="'):
                name     = item[6:].rstrip('"')
            elif item.startswith('filename="'):
                filename = item[10:].rstrip('"')

        if name:
            fields[name] = {"filename": filename, "data": content}

    return fields


def _parse_upload(handler: BaseHTTPRequestHandler) -> tuple[Path, str, str, str]:
    fields     = _parse_multipart(handler)
    file_field = fields.get("file")
    if not file_field or not file_field.get("filename"):
        raise ValueError("Aucun fichier PDF reçu.")

    mode_field = fields.get("mode")
    mode       = mode_field["data"].decode("utf-8").strip().lower() if mode_field else "rapide"
    if mode not in {"rapide", "expert"}:
        mode = "rapide"

    # nom du client saisi dans l'UI
    client_field = fields.get("client")
    client_name  = ""
    if client_field and client_field.get("data") is not None:
        client_name = client_field["data"].decode("utf-8", errors="ignore").strip()
    if not client_name:
        client_name = UPLOAD_CLIENT  # fallback "Application Uploads"

    upload_dir    = PROJECT_ROOT / "Business-Value-Knowledge-Graph/backend/uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    original_name = file_field["filename"]
    target        = upload_dir / (_safe_stem(original_name) + ".pdf")
    target.write_bytes(file_field["data"])
    return target, original_name, mode, client_name



def _analyze_pdf(pdf_path: Path, original_name: str, mode: str, client_name: str) -> dict[str, Any]:
    stem          = _safe_stem(original_name)
    source_folder = f"{client_name}\\{stem}"

    raw_md = _extract_pdf_to_markdown(pdf_path)
    if not raw_md.strip():
        raise RuntimeError("Aucun texte extractible dans ce PDF.")

    clean_md = _step_clean_markdown(raw_md)
    clean_md_path = UPLOAD_CLEAN_DIR / f"{stem}.md"
    clean_md_path.write_text(clean_md, encoding="utf-8")

    if mode == "rapide":
        seg_json_path = _step_split_phrases(clean_md, stem, source_folder)
        result_path   = _step_classify_phrases(seg_json_path, stem)
    else:
        seg_json_path = _step_split_paragraphes(clean_md, stem, source_folder)
        result_path   = _step_classify_paragraphes(seg_json_path, stem)

    # Mémoriser le client pour ce résultat (utilisé par _client_from_path)
    _CLIENT_OVERRIDES[str(result_path.resolve())] = client_name
    _persist_client_overrides()

    found = _find_document(_stable_id(result_path))
    if not found:
        _doc_cache.clear()
        found = _find_document(_stable_id(result_path))

    if not found:
        doc, phrases = _build_doc_and_phrases_from_result(result_path, mode)
        doc["client"] = client_name
    else:
        doc, file_path = found
        doc["client"] = client_name
        phrases = _load_phrases(doc, file_path)

    return {
        "status":   "completed",
        "message":  f"Analyse terminée — pipeline {'Expert' if mode == 'expert' else 'Rapide'} "
                    f"(scripts Python du projet).",
        "document": doc,
        "phrases":  phrases,
    }


def _build_doc_and_phrases_from_result(result_path: Path, mode: str) -> tuple[dict, list]:
    try:
        rows = _read_json(result_path)
    except Exception:
        rows = []

    distribution: Counter = Counter()
    total_cost = total_duration = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        distribution[_normalize_category(row.get("categorie"))] += 1
        total_cost     += float(row.get("cost_eur_phrase")   or 0)
        total_duration += float(row.get("duration_s_phrase") or row.get("duration_s_paragraph") or 0)

    dist     = {cat: int(distribution.get(cat, 0)) for cat in CATEGORIES}
    dominant = max(dist, key=dist.get) if sum(dist.values()) else "Description"
    stem     = result_path.stem
    stem     = re.sub(r"_(phrases|paragraphs|paragraphes)_classification$", "", stem)

    doc = {
        "id":           _stable_id(result_path),
        "name":         stem.replace("_", " ").strip(),
        "client":       UPLOAD_CLIENT,
        "date":         date.today().isoformat(),
        "mode":         mode,
        "phrases":      len(rows),
        "pages":        max(1, round(len(rows) / 6)),
        "costEur":      round(total_cost, 4),
        "durationS":    round(total_duration, 2),
        "distribution": dist,
        "dominant":     dominant,
        "path":         str(result_path.relative_to(PROJECT_ROOT)) if True else str(result_path),
    }

    doc_id  = doc["id"]
    phrases = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rates   = row.get("agreement_rates") or {}
        numeric = [float(v) for v in rates.values() if isinstance(v, (int, float))]
        conf    = round(sum(numeric) / len(numeric), 3) if numeric else 0.75

        roi  = int(row.get("scores_roi")       or 0)
        not_ = int(row.get("scores_notoriete") or 0)
        obl  = int(row.get("scores_obligation")or 0)
        desc = 3 if roi == 0 and not_ == 0 and obl == 0 else 0

        phrases.append({
            "id":         f"{doc_id}-{idx}",
            "phrase":     row.get("phrase") or row.get("paragraph") or "",
            "document":   doc["name"],
            "categorie":  _normalize_category(row.get("categorie")),
            "confidence": conf,
            "scores":     {"ROI": roi, "Notoriete": not_, "Obligation": obl, "Description": desc},
            "modeUsed":   mode,
            "costEur":    float(row.get("cost_eur_phrase") or 0),
            "durationS":  float(row.get("duration_s_phrase") or row.get("duration_s_paragraph") or 0),
            "responses":  row.get("reponses_questions") or {},
        })

    return doc, phrases


# ══════════════════════════════════════════════════════════════════════════════
# LECTURE DU CORPUS
# ══════════════════════════════════════════════════════════════════════════════

_doc_cache: dict[str, list] = {}
_doc_cache_lock = threading.Lock()


def _classification_files() -> list[Path]:
    files: list[Path] = []
    if DATA_ROOT.exists():
        files += sorted(DATA_ROOT.rglob("*_classification.json"))
    for d in (UPLOAD_RESULTS_PHRASE, UPLOAD_RESULTS_PARA):
        if d.exists():
            files += sorted(d.rglob("*_classification.json"))
    return files


def _load_documents() -> list[dict[str, Any]]:
    documents: list[dict] = []
    for path in _classification_files():
        try:
            rows = _read_json(path)
        except Exception:
            continue
        if not isinstance(rows, list) or not rows:
            continue

        distribution: Counter = Counter()
        total_cost = total_duration = 0.0
        for row in rows:
            if not isinstance(row, dict):
                continue
            distribution[_normalize_category(row.get("categorie"))] += 1
            total_cost     += float(row.get("cost_eur_phrase")         or 0)
            total_duration += float(row.get("duration_s_phrase")
                                    or row.get("duration_s_paragraph") or 0)

        dist     = {cat: int(distribution.get(cat, 0)) for cat in CATEGORIES}
        dominant = max(dist, key=dist.get) if sum(dist.values()) else "Description"

        try:
            rel_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            rel_path = str(path)

        documents.append({
            "id":           _stable_id(path),
            "name":         _doc_name_from_path(path),
            "client":       _client_from_path(path),
            "date":         date.fromtimestamp(path.stat().st_mtime).isoformat(),
            "mode":         _mode_from_path(path),
            "phrases":      len(rows),
            "pages":        max(1, round(len(rows) / 6)),
            "costEur":      round(total_cost, 4),
            "durationS":    round(total_duration, 2),
            "distribution": dist,
            "dominant":     dominant,
            "path":         rel_path,
        })

    documents.sort(key=lambda d: (d["date"], d["name"]), reverse=True)
    return documents


def _find_document(doc_id: str) -> tuple[dict, Path] | None:
    for doc in _load_documents():
        if doc["id"] == doc_id:
            p = Path(doc["path"])
            path = PROJECT_ROOT / p if not p.is_absolute() else p
            return doc, path
    return None


def _load_phrases(doc: dict, path: Path) -> list[dict]:
    try:
        rows = _read_json(path)
    except Exception:
        rows = []

    phrases = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        rates   = row.get("agreement_rates") or {}
        numeric = [float(v) for v in rates.values() if isinstance(v, (int, float))]
        conf    = round(sum(numeric) / len(numeric), 3) if numeric else 0.75

        roi  = int(row.get("scores_roi")       or 0)
        not_ = int(row.get("scores_notoriete") or 0)
        obl  = int(row.get("scores_obligation")or 0)
        desc = 3 if roi == 0 and not_ == 0 and obl == 0 else 0

        phrases.append({
            "id":         f"{doc['id']}-{idx}",
            "phrase":     row.get("phrase") or row.get("paragraph") or "",
            "document":   doc["name"],
            "categorie":  _normalize_category(row.get("categorie")),
            "confidence": conf,
            "scores":     {"ROI": roi, "Notoriete": not_, "Obligation": obl, "Description": desc},
            "modeUsed":   doc["mode"],
            "costEur":    float(row.get("cost_eur_phrase") or 0),
            "durationS":  float(row.get("duration_s_phrase") or row.get("duration_s_paragraph") or 0),
            "responses":  row.get("reponses_questions") or {},
        })
    return phrases


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

def _dashboard() -> dict:
    docs  = _load_documents()
    dist: Counter = Counter()
    total_cost = total_phrases = 0
    clients = set()
    for doc in docs:
        clients.add(doc["client"])
        total_cost    += float(doc["costEur"])
        total_phrases += int(doc["phrases"])
        dist.update(doc["distribution"])

    models_available = 5 if _mod_clf_phrase() else 0

    return {
        "corpusStats": {
            "documents":    len(docs),
            "phrases":      total_phrases,
            "models":       models_available,
            "questions":    9,
            "clients":      len(clients),
            "totalCostEur": round(total_cost, 2),
        },
        "distribution":    {cat: int(dist.get(cat, 0)) for cat in CATEGORIES},
        "recentDocuments": docs[:8],
    }


def _summary(doc_id: str) -> dict | None:
    found = _find_document(doc_id)
    if not found:
        return None
    doc, path = found
    phrases   = _load_phrases(doc, path)
    total     = max(1, sum(doc["distribution"].values()))
    sorted_d  = sorted(doc["distribution"].items(), key=lambda x: x[1], reverse=True)
    dominant, dom_count = sorted_d[0]
    weak, weak_count    = sorted_d[-1]

    recommendations: list[str] = []
    pct = lambda cat: (doc["distribution"][cat] / total) * 100
    if pct("ROI")         > 40: recommendations.append("Document fortement orienté ROI : mettre en avant les gains chiffrés dans la synthèse.")
    if pct("Description") > 50: recommendations.append("Argumentaire surtout descriptif : enrichir avec des bénéfices mesurables.")
    if pct("Obligation")  > 25: recommendations.append("Présence forte d'obligations réglementaires : préparer une lecture conformité.")
    if pct("Notoriete")   > 25: recommendations.append("Notoriété et expérience utilisateur bien mises en avant : exploitable en communication.")
    if pct("ROI")         < 10: recommendations.append("Argumentaire ROI faible : ajouter des preuves de gain, coût ou productivité.")
    if not recommendations:
        recommendations.append("Argumentaire équilibré entre les axes de valeur business.")

    key_phrases = [p for p in phrases if p["categorie"] != "Description"][:6]
    return {
        "document":        doc,
        "dominant":        dominant,
        "dominantPct":     round((dom_count / total) * 100, 1),
        "weak":            weak,
        "weakPct":         round((weak_count / total) * 100, 1),
        "keyPhrases":      key_phrases,
        "recommendations": recommendations,
    }


# ══════════════════════════════════════════════════════════════════════════════
# HANDLER HTTP
# ══════════════════════════════════════════════════════════════════════════════

class ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_OPTIONS(self) -> None:
        _json_response(self, 204, {})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path   = parsed.path
        query  = parse_qs(parsed.query)

        if path == "/":
            _json_response(self, 200, {
                "name": "Business Value Classifier Backend API",
                "status": "ok",
                "endpoints": {
                    "health": "/api/health",
                    "dashboard": "/api/dashboard",
                    "documents": "/api/documents",
                    "results": "/api/results?documentId=<id>",
                    "summary": "/api/summary?documentId=<id>",
                    "analyze": "POST /api/analyze",
                },
            })
            return

        if path == "/api/health":
            gpu_info = {}
            mod_ext  = _mod_extract()
            if mod_ext and hasattr(mod_ext, "get_gpu_memory_info"):
                free_gb, total_gb = mod_ext.get_gpu_memory_info()
                if total_gb is not None:
                    gpu_info = {"detected": True, "total_gb": round(total_gb, 1), "free_gb": round(free_gb, 1)}
                else:
                    gpu_info = {"detected": False}

            _json_response(self, 200, {
                "status": "ok",
                "scripts": {
                    "extract":         SCRIPT_EXTRACT.exists(),
                    "clean":           SCRIPT_CLEAN.exists(),
                    "phrases":         SCRIPT_PHRASES.exists(),
                    "paragraphes":     SCRIPT_PARAGRAPHES.exists(),
                    "classify_phrase": SCRIPT_CLASSIFY_PHRASE.exists(),
                    "classify_para":   SCRIPT_CLASSIFY_PARA.exists(),
                },
                "modules_loaded": {
                    "extract":         _mod_extract() is not None,
                    "clean":           _mod_clean() is not None,
                    "phrases":         _mod_phrases() is not None,
                    "paragraphes":     _mod_paragraphes() is not None,
                    "classify_phrase": _mod_clf_phrase() is not None,
                    "classify_para":   _mod_clf_para() is not None,
                },
                "gpu":                  gpu_info,
                "marker_models_cached": _MARKER_MODELS is not None,
            })
            return

        if path == "/api/dashboard":
            _json_response(self, 200, _dashboard())
            return

        if path == "/api/documents":
            _json_response(self, 200, {"documents": _load_documents()})
            return

        if path == "/api/results":
            doc_id = query.get("documentId", [""])[0]
            found  = _find_document(doc_id) if doc_id else None
            if not found:
                docs  = _load_documents()
                found = _find_document(docs[0]["id"]) if docs else None
            if not found:
                _json_response(self, 200, {"document": None, "phrases": []})
                return
            doc, file_path = found
            _json_response(self, 200, {"document": doc, "phrases": _load_phrases(doc, file_path)})
            return

        if path == "/api/summary":
            doc_id = query.get("documentId", [""])[0]
            if not doc_id:
                docs   = _load_documents()
                doc_id = docs[0]["id"] if docs else ""
            payload = _summary(doc_id)
            if payload is None:
                _json_response(self, 200, {"document": None, "recommendations": [], "keyPhrases": []})
                return
            _json_response(self, 200, payload)
            return

        _not_found(self)

    def do_POST(self) -> None:
        if urlparse(self.path).path == "/api/analyze":
            try:
                pdf_path, original_name, mode, client_name = _parse_upload(self)
                payload = _analyze_pdf(pdf_path, original_name, mode, client_name)

                _json_response(self, 200, payload)
            except ValueError as exc:
                _bad_request(self, str(exc))
            except Exception as exc:
                import traceback
                traceback.print_exc()
                _json_response(self, 500, {"error": str(exc)})
            return
        _not_found(self)


# ══════════════════════════════════════════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    print("=" * 70)
    print("Business Value Classifier — Backend API")
    print("=" * 70)
    print(f"  Adresse  : http://{HOST}:{PORT}")
    print(f"  Données  : {DATA_ROOT}")
    print()
    print("  Scripts Python configurés :")
    for label, path in [
        ("extract.py",                 SCRIPT_EXTRACT),
        ("clean.py",                   SCRIPT_CLEAN),
        ("decoupage_en_phrases.py",    SCRIPT_PHRASES),
        ("decoupage_en_paragraphes.py",SCRIPT_PARAGRAPHES),
        ("multi_llm_phrase.py",        SCRIPT_CLASSIFY_PHRASE),
        ("multi_llm_paragraph.py",     SCRIPT_CLASSIFY_PARA),
    ]:
        status = "✓ trouvé" if path.exists() else "✗ ABSENT — erreur au chargement"
        print(f"    {label:<35} {status}")
    print()

    mod_ext = _mod_extract()
    if mod_ext and hasattr(mod_ext, "get_gpu_memory_info"):
        free_gb, total_gb = mod_ext.get_gpu_memory_info()
        if total_gb is not None:
            print(f"  GPU détecté : {total_gb:.0f} GB total, {free_gb:.1f} GB libre")
        else:
            print("  GPU non détecté (utilisation CPU)")
    print()

    print("  Chargement des modules Python...")
    for loader in (_mod_extract, _mod_clean, _mod_phrases, _mod_paragraphes,
                   _mod_clf_phrase, _mod_clf_para):
        loader()
    print("  Modules chargés. Serveur prêt.\n")

    server = ThreadingHTTPServer((HOST, PORT), ApiHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du serveur.")


if __name__ == "__main__":
    main()