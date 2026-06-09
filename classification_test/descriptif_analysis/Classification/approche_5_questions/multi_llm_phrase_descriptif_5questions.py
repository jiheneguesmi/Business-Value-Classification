"""
Script : Filtre Descriptif Multi-LLM — OpenRouter (5 modeles)
v1 — Filtre amont avant classification ROI/Notoriete/Obligation

Logique :
  - 1 appel = 5 questions x 1 phrase x 1 modele (toutes les questions en un seul appel)
  - Une phrase est "descriptive" (à éliminer) si AUCUNE des 5 questions
    ne reçoit "oui" en vote majoritaire inter-modèles
  - Une phrase "passe" si AU MOINS 1 question reçoit "oui" majoritaire

Note : le type de question (descriptif/filtre) n'est PAS mentionné
dans les prompts pour éviter de biaiser le LLM.
"""

import os
import re
import json
import time
import random
import threading
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests

load_dotenv()

# ── Configuration ──────────────────────────────────────────────────────────────
SEGMENTS_INPUT_DIR   = r"F:\Jihene\business_value_classification\classification_test\Decoupage\phrases"
OUTPUT_DIR           = r"F:\Jihene\business_value_classification\classification_test\Classification\resultats_filtre_descriptif"
SYSTEM_PROMPT_FILE   = r"F:\Jihene\business_value_classification\classification_test\Classification\system_prompt_descriptif.txt"
USER_PROMPT_FILE     = r"F:\Jihene\business_value_classification\classification_test\Classification\user_prompt_descriptif.txt"

os.makedirs(OUTPUT_DIR, exist_ok=True)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY manquante dans le fichier .env")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

EUR_USD_RATE = 1.08

def usd_to_eur(usd: float) -> float:
    return usd / EUR_USD_RATE

MODEL_PRICING = {
    "meta-llama/llama-3.3-70b-instruct": {"input": 0.10, "output": 0.32},
    "google/gemma-3-27b-it":             {"input": 0.08, "output": 0.16},
    "mistralai/mistral-nemo":            {"input": 0.02, "output": 0.03},
    "qwen/qwen3-8b":                     {"input": 0.05, "output": 0.40},
    "openai/gpt-4o-mini":                {"input": 0.15, "output": 0.60},
}
DEFAULT_PRICING = {"input": 0.10, "output": 0.10}

def compute_call_cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model_name, DEFAULT_PRICING)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

ENSEMBLE_A = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "mistralai/mistral-nemo",
    "qwen/qwen3-8b",
    "openai/gpt-4o-mini",
]
MODELS_TO_USE = ENSEMBLE_A

# ── 5 questions du filtre descriptif ──────────────────────────────────────────
# Clés neutres (pas de mention du type "descriptif") pour ne pas biaiser le LLM
FILTER_QUESTIONS = {
    "q1": "Cette phrase te permet-elle de justifier la dépense devant ta hiérarchie ?",
    "q2": "Cette phrase te protège-t-elle si la décision est remise en question par ta hiérarchie ?",
    "q3": "Cette phrase te donne-t-elle confiance que le fournisseur a déjà résolu ce problème pour d'autres ?",
    "q4": "Cette phrase te donnerait-elle envie de recommander ce fournisseur à un pair ?",
    "q5": "Cette phrase te signale-t-elle une contrainte que tu dois respecter qu'elle te plaise ou non ?",
}
FILTER_QUESTION_KEYS = list(FILTER_QUESTIONS.keys())  # ["q1","q2","q3","q4","q5"]

MAX_TOKENS        = 128   # légèrement plus large pour le JSON à 5 champs
MAX_RETRIES       = 5
BACKOFF_BASE      = 2.0
MAX_WORKERS       = 5

# Noms courts des modèles
MODEL_SHORT_NAMES = [m.split("/")[-1][:20] for m in MODELS_TO_USE]


# ── Chargement des prompts ─────────────────────────────────────────────────────
def load_text_file(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {file_path}")
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

SYSTEM_PROMPT        = load_text_file(SYSTEM_PROMPT_FILE)
USER_PROMPT_TEMPLATE = load_text_file(USER_PROMPT_FILE)


# ── Construction du prompt ─────────────────────────────────────────────────────
def build_prompt(phrase: str) -> str:
    """Injecte la phrase et les 5 questions dans le template utilisateur."""
    return USER_PROMPT_TEMPLATE.format(
        phrase=phrase,
        question_1=FILTER_QUESTIONS["q1"],
        question_2=FILTER_QUESTIONS["q2"],
        question_3=FILTER_QUESTIONS["q3"],
        question_4=FILTER_QUESTIONS["q4"],
        question_5=FILTER_QUESTIONS["q5"],
    )


# ── Dataclasses ────────────────────────────────────────────────────────────────
@dataclass
class Phrase:
    phrase:        str
    phrase_index:  int
    source_file:   str
    source_folder: str


@dataclass
class CallResult:
    """Résultat d'un appel : 1 modèle x 5 questions x 1 phrase."""
    model_name:    str
    reponses:      dict   # {"q1": "oui"|"non", ..., "q5": "oui"|"non"}
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0
    cost_eur:      float = 0.0
    duration_s:    float = 0.0
    erreur:        str   = None


@dataclass
class FilterResult:
    """Résultat final du filtre pour une phrase."""
    phrase:             str
    phrase_index:       int
    source_file:        str
    source_folder:      str
    # Décision finale : "PASSE" ou "DESCRIPTIF"
    decision:           str
    # Combien de questions ont eu "oui" majoritaire (0-5)
    nb_oui_majoritaires: int
    # Réponses agrégées par vote majoritaire
    reponses_agreges:   dict   # {"q1": "oui"|"non", ..., "q5": "oui"|"non"}
    # Taux d'accord inter-modèles par question
    agreement_rates:    dict   = field(default_factory=dict)
    cost_usd_phrase:    float = 0.0
    cost_eur_phrase:    float = 0.0
    duration_s_phrase:  float = 0.0
    detail_appels:      list  = field(default_factory=list)
    ensemble_modeles:   list  = field(default_factory=list)


# ── Accumulateur de stats ──────────────────────────────────────────────────────
class StatsAccumulator:
    def __init__(self, models: list):
        self.models              = models
        self.start_time          = time.time()
        self._lock               = threading.Lock()
        self.cost_usd_by_model   = {m: 0.0 for m in models}
        self.tokens_in_by_model  = {m: 0   for m in models}
        self.tokens_out_by_model = {m: 0   for m in models}
        self.calls_by_model      = {m: 0   for m in models}
        self.errors_by_model     = {m: 0   for m in models}
        # Accord inter-modèles par question
        self.agree_counts        = {k: 0   for k in FILTER_QUESTION_KEYS}
        self.total_votes         = {k: 0   for k in FILTER_QUESTION_KEYS}
        self.cost_usd_by_file:   dict = {}
        self.phrase_count:       int  = 0

    def record_call(self, model: str, tok_in: int, tok_out: int,
                    error: bool, source_file: str):
        cost = compute_call_cost_usd(model, tok_in, tok_out)
        with self._lock:
            self.cost_usd_by_model[model]   += cost
            self.tokens_in_by_model[model]  += tok_in
            self.tokens_out_by_model[model] += tok_out
            self.calls_by_model[model]      += 1
            if error:
                self.errors_by_model[model] += 1
            self.cost_usd_by_file[source_file] = (
                self.cost_usd_by_file.get(source_file, 0.0) + cost
            )

    def record_agreement(self, call_results: list):
        """Calcule l'accord inter-modèles par question sur un ensemble d'appels."""
        for qk in FILTER_QUESTION_KEYS:
            valid = [r for r in call_results if not r.erreur]
            n = len(valid)
            if n < 2:
                continue
            votes_oui = sum(1 for r in valid if r.reponses.get(qk) == "oui")
            agreed = (votes_oui == n or votes_oui == 0)
            with self._lock:
                self.agree_counts[qk] += (1 if agreed else 0)
                self.total_votes[qk]  += 1

    def compute_phrase_agreement(self, call_results: list) -> dict:
        """Retourne le taux d'accord par question pour une phrase donnée."""
        agreement = {}
        valid = [r for r in call_results if not r.erreur]
        n = len(valid)
        for qk in FILTER_QUESTION_KEYS:
            if n < 2:
                agreement[qk] = 0.5
            else:
                votes_oui = sum(1 for r in valid if r.reponses.get(qk) == "oui")
                majority  = max(votes_oui, n - votes_oui)
                agreement[qk] = majority / n
        return agreement

    @property
    def total_cost_usd(self) -> float:
        return sum(self.cost_usd_by_model.values())

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.start_time

    def error_rate(self, model: str) -> float:
        t = self.calls_by_model.get(model, 0)
        return self.errors_by_model.get(model, 0) / t if t else 0.0

    def agreement_rate(self, qk: str) -> float:
        t = self.total_votes.get(qk, 0)
        return self.agree_counts.get(qk, 0) / t if t else 0.0

    def eta_str(self, done: int, total: int) -> str:
        if done == 0:
            return ""
        avg = self.elapsed_s / done
        remaining = (total - done) * avg
        return f"ETA {remaining/60:.1f}min"

    def print_summary(self):
        n     = self.phrase_count
        elaps = self.elapsed_s
        total_eur = usd_to_eur(self.total_cost_usd)
        print("\n" + "-" * 70)
        print("STATISTIQUES GLOBALES — FILTRE DESCRIPTIF")
        print("-" * 70)
        print(f"  Coût total  : ${self.total_cost_usd:.4f} / EUR{total_eur:.4f}")
        if n:
            print(f"  Coût/phrase : ${self.total_cost_usd/n:.6f} / EUR{usd_to_eur(self.total_cost_usd)/n:.6f}")
        print(f"  Temps total : {elaps/60:.1f} min")
        if n:
            print(f"  Temps/phrase: {elaps/n:.1f}s")
        print("\n  Par modèle :")
        for m in self.models:
            c = self.cost_usd_by_model[m]
            print(f"    {m.split('/')[-1]:<32} "
                  f"${c:.4f}/EUR{usd_to_eur(c):.4f}  "
                  f"appels:{self.calls_by_model[m]}  "
                  f"err:{self.error_rate(m)*100:.1f}%")
        print(f"\n  Accord inter-modèles par question :")
        for qk in FILTER_QUESTION_KEYS:
            print(f"    {qk}  {self.agreement_rate(qk)*100:5.1f}%  "
                  f"{FILTER_QUESTIONS[qk][:55]}")
        print("-" * 70)


# ── API OpenRouter ─────────────────────────────────────────────────────────────
def _extract_content_and_usage(data: dict) -> tuple:
    choice  = data["choices"][0]
    msg     = choice.get("message", {})
    content = msg.get("content") or msg.get("reasoning") or ""
    if not content.strip():
        raise ValueError("Réponse vide")
    usage = data.get("usage", {})
    return (content.strip(),
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0))


def _call_openrouter(model_name: str, messages: list) -> tuple:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://github.com/jiheneguesmi/Business-Value-Knowledge-Graph",
        "X-Title":       "Business Value Classification — Filtre Descriptif",
    }
    payload = {
        "model":       model_name,
        "messages":    messages,
        "temperature": 0,
        "max_tokens":  MAX_TOKENS,
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers,
                                 json=payload, timeout=120)
            if resp.status_code == 429:
                reset_ms = resp.headers.get("X-RateLimit-Reset")
                wait = max(1.0, (int(reset_ms) - time.time() * 1000) / 1000) if reset_ms else BACKOFF_BASE ** attempt
                wait = min(wait, 60.0) + random.uniform(0, 2.0)
                print(f"        Rate limit ({model_name.split('/')[-1]}), "
                      f"attente {wait:.1f}s... (tentative {attempt}/{MAX_RETRIES})")
                time.sleep(wait)
                continue
            if resp.status_code == 404:
                raise ValueError(f"Modèle introuvable : {model_name}")
            if resp.status_code == 400:
                err_detail = resp.json().get("error", {}).get("message", resp.text[:200])
                raise ValueError(f"Requête invalide (400) : {err_detail}")
            resp.raise_for_status()
            return _extract_content_and_usage(resp.json())
        except (ValueError, KeyError):
            raise
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE ** attempt)
            else:
                raise
        except Exception as e:
            if attempt < MAX_RETRIES:
                wait = BACKOFF_BASE ** attempt + random.uniform(0, 1)
                print(f"        {model_name.split('/')[-1]}: {e}, "
                      f"retry {attempt}/{MAX_RETRIES} dans {wait:.1f}s")
                time.sleep(wait)
            else:
                raise
    raise Exception(f"Échec après {MAX_RETRIES} tentatives pour {model_name}")


def _parse_reponses(raw: str) -> dict:
    """
    Parse la réponse JSON à 5 champs.
    Retourne {"q1": "oui"|"non", ..., "q5": "oui"|"non"}.
    En cas d'échec, toutes les réponses sont "non" (comportement conservateur).
    """
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw).strip()

    def normalize(val) -> str:
        v = str(val).lower().strip()
        return "oui" if v in ("oui", "yes", "true", "1") else "non"

    try:
        parsed = json.loads(raw)
        return {qk: normalize(parsed.get(qk, "non")) for qk in FILTER_QUESTION_KEYS}
    except json.JSONDecodeError:
        # Fallback : cherche les patterns q1/q2/q3/q4/q5 dans le texte brut
        result = {}
        lower  = raw.lower()
        for qk in FILTER_QUESTION_KEYS:
            # Cherche "q1": "oui" ou q1 : oui ou q1 oui
            pattern = rf'"{qk}"\s*:\s*"?(oui|non|yes|no)"?'
            match   = re.search(pattern, lower)
            if match:
                result[qk] = "oui" if match.group(1) in ("oui", "yes") else "non"
            else:
                result[qk] = "non"
        return result


# ── Appel : 1 modèle x 5 questions x 1 phrase ─────────────────────────────────
def call_one(
    phrase_obj: Phrase,
    model_name: str,
    stats: StatsAccumulator,
) -> CallResult:

    prompt   = build_prompt(phrase_obj.phrase)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    t0 = time.time()
    try:
        raw, tok_in, tok_out = _call_openrouter(model_name, messages)
        duration  = time.time() - t0
        reponses  = _parse_reponses(raw)
        cost_usd  = compute_call_cost_usd(model_name, tok_in, tok_out)

        stats.record_call(model_name, tok_in, tok_out,
                          error=False, source_file=phrase_obj.source_file)

        return CallResult(
            model_name=model_name,
            reponses=reponses,
            input_tokens=tok_in,
            output_tokens=tok_out,
            cost_usd=cost_usd,
            cost_eur=usd_to_eur(cost_usd),
            duration_s=round(duration, 2),
        )

    except Exception as e:
        duration = time.time() - t0
        stats.record_call(model_name, 0, 0,
                          error=True, source_file=phrase_obj.source_file)
        return CallResult(
            model_name=model_name,
            reponses={qk: "non" for qk in FILTER_QUESTION_KEYS},
            duration_s=round(duration, 2),
            erreur=str(e),
        )


# ── Agrégation ────────────────────────────────────────────────────────────────
def majority_vote_per_question(call_results: list) -> dict:
    """
    Vote majoritaire par question sur l'ensemble des modèles.
    Retourne {"q1": "oui"|"non", ..., "q5": "oui"|"non"}.
    """
    valid = [r for r in call_results if not r.erreur]
    n = len(valid)
    if n == 0:
        return {qk: "non" for qk in FILTER_QUESTION_KEYS}

    aggregated = {}
    for qk in FILTER_QUESTION_KEYS:
        votes_oui = sum(1 for r in valid if r.reponses.get(qk) == "oui")
        aggregated[qk] = "oui" if votes_oui > n / 2 else "non"
    return aggregated


def determine_filter_decision(reponses_agreges: dict) -> tuple:
    """
    Décision finale :
    - "PASSE"      : au moins 1 question a "oui" majoritaire
    - "DESCRIPTIF" : aucune question n'a "oui" majoritaire
    Retourne (decision, nb_oui_majoritaires)
    """
    nb_oui = sum(1 for v in reponses_agreges.values() if v == "oui")
    decision = "PASSE" if nb_oui >= 1 else "DESCRIPTIF"
    return decision, nb_oui


# ── Traitement d'une phrase ───────────────────────────────────────────────────
def process_phrase(
    phrase_obj: Phrase,
    models: list,
    stats: StatsAccumulator,
    phrase_num: int,
    total_phrases: int,
) -> FilterResult:

    t_phrase = time.time()
    all_calls: list = []
    _lock = threading.Lock()

    # Appel parallèle : 1 appel par modèle (chaque appel couvre les 5 questions)
    def call_model(model):
        result = call_one(phrase_obj, model, stats)
        return result

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(call_model, model): model for model in models}
        for future in as_completed(futures):
            result = future.result()
            with _lock:
                all_calls.append(result)

    stats.record_agreement(all_calls)
    phrase_agreement  = stats.compute_phrase_agreement(all_calls)
    reponses_agreges  = majority_vote_per_question(all_calls)
    decision, nb_oui  = determine_filter_decision(reponses_agreges)

    phrase_cost_usd = sum(r.cost_usd for r in all_calls)
    phrase_cost_eur = usd_to_eur(phrase_cost_usd)
    phrase_duration = time.time() - t_phrase

    detail = [
        {
            "model":      r.model_name.split("/")[-1][:20],
            "reponses":   r.reponses,
            "erreur":     r.erreur,
            "cost_eur":   round(r.cost_eur, 7),
            "duration_s": r.duration_s,
        }
        for r in all_calls
    ]

    n_errors     = sum(1 for d in detail if d["erreur"])
    eta          = stats.eta_str(phrase_num, total_phrases)
    err_flag     = f"  {n_errors} err" if n_errors else ""
    decision_tag = f"{'✓ PASSE':>10}" if decision == "PASSE" else f"{'✗ DESCRIPTIF':>10}"

    print(f"  [{phrase_num:>4}/{total_phrases}] "
          f"'{phrase_obj.phrase[:50]:<50}'  "
          f"{decision_tag}  oui:{nb_oui}/5  "
          f"EUR{phrase_cost_eur:.6f}  "
          f"{phrase_duration:.1f}s  "
          f"{eta}{err_flag}")

    stats.phrase_count += 1

    return FilterResult(
        phrase=phrase_obj.phrase,
        phrase_index=phrase_obj.phrase_index,
        source_file=phrase_obj.source_file,
        source_folder=phrase_obj.source_folder,
        decision=decision,
        nb_oui_majoritaires=nb_oui,
        reponses_agreges=reponses_agreges,
        agreement_rates=phrase_agreement,
        cost_usd_phrase=round(phrase_cost_usd, 7),
        cost_eur_phrase=round(phrase_cost_eur, 7),
        duration_s_phrase=round(phrase_duration, 2),
        detail_appels=detail,
        ensemble_modeles=models,
    )


# ── Traitement d'un fichier ────────────────────────────────────────────────────
def process_file(
    seg_path: Path,
    models: list,
    stats: StatsAccumulator,
) -> list:

    with open(seg_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    phrases = [
        Phrase(
            phrase=item["phrase"],
            phrase_index=item["phrase_index"],
            source_file=item.get("source_file", seg_path.name),
            source_folder=item.get("source_folder", ""),
        )
        for item in data
        if item.get("phrase", "").strip()
    ]

    n_phrases = len(phrases)
    # 1 appel par modèle par phrase (les 5 questions dans 1 seul appel)
    n_calls   = n_phrases * len(models)
    print(f"\n   {seg_path.name}")
    print(f"   {n_phrases} phrases  |  "
          f"5 questions (1 appel/modèle)  |  "
          f"{len(models)} modèles  |  "
          f"~{n_calls} appels\n")

    results = []
    for i, phrase_obj in enumerate(phrases, 1):
        result = process_phrase(phrase_obj, models, stats, i, n_phrases)
        results.append(result)

    return results


# ── Export fichier (JSON + Excel) ─────────────────────────────────────────────
def export_file_results(
    results: list,
    dest_dir: Path,
    base_name: str,
    models: list,
):
    json_out = dest_dir / f"{base_name}_filtre_descriptif.json"
    xl_out   = dest_dir / f"{base_name}_filtre_descriptif.xlsx"

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)

    rows = []
    for r in results:
        row = {
            "Source_File":        r.source_file,
            "Source_Folder":      r.source_folder,
            "Phrase_Index":       r.phrase_index,
            "Phrase":             r.phrase,
            "Decision":           r.decision,
            "Nb_OUI_Majoritaires": r.nb_oui_majoritaires,
            "Cost_EUR":           r.cost_eur_phrase,
            "Duration_s":         r.duration_s_phrase,
        }
        # Réponses agrégées par question
        for qk in FILTER_QUESTION_KEYS:
            row[f"AGG_{qk}"] = r.reponses_agreges.get(qk, "?")
        # Taux d'accord inter-modèles
        for qk in FILTER_QUESTION_KEYS:
            row[f"ACCORD_{qk}_%"] = round(r.agreement_rates.get(qk, 0.5) * 100, 1)
        # Détail par modèle
        for model in models:
            short = model.split("/")[-1][:20]
            match = next((d for d in r.detail_appels if d["model"] == short), None)
            for qk in FILTER_QUESTION_KEYS:
                col = f"{short}__{qk}"
                if match:
                    row[col] = match["reponses"].get(qk, "?") if not match["erreur"] else "ERR"
                else:
                    row[col] = "?"
        rows.append(row)

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(xl_out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Filtre_Descriptif", index=False)

    print(f"\n   Sauvegarde -> {json_out.name}")
    print(f"   Sauvegarde -> {xl_out.name}")


# ── Export global complet ──────────────────────────────────────────────────────
def export_complete_summary(
    all_results: list,
    models: list,
    timestamp: str,
    stats: StatsAccumulator,
    output_dir: Path,
):
    # ── Sheet 1 : Toutes_Phrases ──────────────────────────────────────────────
    rows = []
    for r in all_results:
        row = {
            "Source_File":         r.source_file,
            "Source_Folder":       r.source_folder,
            "Phrase_Index":        r.phrase_index,
            "Phrase":              r.phrase,
            "Decision":            r.decision,
            "Nb_OUI_Majoritaires": r.nb_oui_majoritaires,
            "Cost_EUR":            r.cost_eur_phrase,
            "Duration_s":          r.duration_s_phrase,
        }
        for qk in FILTER_QUESTION_KEYS:
            row[f"AGG_{qk}"]       = r.reponses_agreges.get(qk, "?")
            row[f"ACCORD_{qk}_%"]  = round(r.agreement_rates.get(qk, 0.5) * 100, 1)
        for model in models:
            short = model.split("/")[-1][:20]
            match = next((d for d in r.detail_appels if d["model"] == short), None)
            for qk in FILTER_QUESTION_KEYS:
                col = f"{short}__{qk}"
                if match:
                    row[col] = match["reponses"].get(qk, "?") if not match["erreur"] else "ERR"
                else:
                    row[col] = "?"
        rows.append(row)
    df_main = pd.DataFrame(rows)

    # ── Sheet 2 : Synthese_Par_Fichier ────────────────────────────────────────
    summary_rows = []
    for file_name, grp in df_main.groupby("Source_File"):
        summary_rows.append({
            "Fichier":              file_name,
            "Total_Phrases":        len(grp),
            "PASSE":                (grp.Decision == "PASSE").sum(),
            "DESCRIPTIF":           (grp.Decision == "DESCRIPTIF").sum(),
            "Taux_DESCRIPTIF_%":    round((grp.Decision == "DESCRIPTIF").sum() / len(grp) * 100, 1),
            "Cout_Total_EUR":       grp["Cost_EUR"].sum(),
            "Cout_Moyen_EUR_Phrase":grp["Cost_EUR"].mean(),
            "Duree_Totale_sec":     grp["Duration_s"].sum(),
        })
    df_summary = pd.DataFrame(summary_rows)

    # ── Sheet 3 : Stats_Par_Modele ────────────────────────────────────────────
    rows_models = []
    for m in models:
        rows_models.append({
            "Modele":         m.split("/")[-1][:30],
            "Modele_complet": m,
            "Tokens_Input":   stats.tokens_in_by_model.get(m, 0),
            "Tokens_Output":  stats.tokens_out_by_model.get(m, 0),
            "Cout_USD":       round(stats.cost_usd_by_model.get(m, 0), 6),
            "Cout_EUR":       round(usd_to_eur(stats.cost_usd_by_model.get(m, 0)), 6),
            "Nb_Appels":      stats.calls_by_model.get(m, 0),
            "Nb_Erreurs":     stats.errors_by_model.get(m, 0),
            "Taux_Erreur_%":  round(stats.error_rate(m) * 100, 2),
        })
    df_models = pd.DataFrame(rows_models)

    # ── Sheet 4 : Accord_Questions ────────────────────────────────────────────
    rows_accord = []
    for qk in FILTER_QUESTION_KEYS:
        rows_accord.append({
            "Question_Key":    qk,
            "Texte_Question":  FILTER_QUESTIONS[qk],
            "Taux_Accord_%":   round(stats.agreement_rate(qk) * 100, 2),
            "Nb_Comparaisons": stats.total_votes.get(qk, 0),
        })
    df_accord = pd.DataFrame(rows_accord)

    # ── Sheet 5 : Distribution_Decisions ─────────────────────────────────────
    total = len(all_results)
    passe      = sum(1 for r in all_results if r.decision == "PASSE")
    descriptif = sum(1 for r in all_results if r.decision == "DESCRIPTIF")
    df_distrib = pd.DataFrame([
        {"Decision": "PASSE",      "Nombre": passe,
         "Pourcentage_%": round(passe/total*100, 1) if total else 0},
        {"Decision": "DESCRIPTIF", "Nombre": descriptif,
         "Pourcentage_%": round(descriptif/total*100, 1) if total else 0},
    ])

    # ── Sheet 6 : Stats_Globales ──────────────────────────────────────────────
    n = stats.phrase_count
    total_eur = usd_to_eur(stats.total_cost_usd)
    df_global = pd.DataFrame([{
        "Timestamp":               timestamp,
        "Total_Phrases":           total,
        "Total_PASSE":             passe,
        "Total_DESCRIPTIF":        descriptif,
        "Taux_DESCRIPTIF_%":       round(descriptif/total*100, 1) if total else 0,
        "Total_Cout_EUR":          round(total_eur, 6),
        "Cout_Moyen_EUR_Phrase":   round(total_eur / n, 7) if n else 0,
        "Duree_Totale_min":        round(stats.elapsed_s / 60, 2),
        "Duree_Moyenne_sec_Phrase":round(stats.elapsed_s / n, 2) if n else 0,
        "Taux_EUR_USD":            EUR_USD_RATE,
        "Nb_Modeles":              len(models),
        "Nb_Questions_Par_Appel":  5,
        "Modeles_Utilises":        " | ".join(m.split("/")[-1] for m in models),
    }])

    # ── Export Excel ──────────────────────────────────────────────────────────
    excel_path = output_dir / f"recapitulatif_filtre_descriptif_{timestamp}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_main.to_excel(writer,    sheet_name="Toutes_Phrases",       index=False)
        df_summary.to_excel(writer, sheet_name="Synthese_Par_Fichier", index=False)
        df_models.to_excel(writer,  sheet_name="Stats_Par_Modele",     index=False)
        df_accord.to_excel(writer,  sheet_name="Accord_Questions",     index=False)
        df_distrib.to_excel(writer, sheet_name="Distribution",         index=False)
        df_global.to_excel(writer,  sheet_name="Stats_Globales",       index=False)

    print(f"\n   Export Excel complet -> {excel_path.name}")

    # ── Export JSON des phrases filtrées uniquement ───────────────────────────
    # Utile pour enchaîner directement avec le script de classification ROI/NOT/OBL
    phrases_passees = [r for r in all_results if r.decision == "PASSE"]
    json_passe_path = output_dir / f"phrases_passees_{timestamp}.json"
    with open(json_passe_path, "w", encoding="utf-8") as f:
        json.dump(
            [{"phrase": r.phrase,
              "phrase_index": r.phrase_index,
              "source_file": r.source_file,
              "source_folder": r.source_folder}
             for r in phrases_passees],
            f, ensure_ascii=False, indent=2
        )
    print(f"   Phrases PASSE (prêtes pour classification) -> {json_passe_path.name}")
    print(f"   {len(phrases_passees)}/{total} phrases passent le filtre "
          f"({round(len(phrases_passees)/total*100,1) if total else 0}%)")

    return excel_path


# ── Main ───────────────────────────────────────────────────────────────────────
def run(models: list = None):
    if models is None:
        models = MODELS_TO_USE

    stats = StatsAccumulator(models)

    print("=" * 80)
    print("FILTRE DESCRIPTIF — 1 appel = 5 questions x 1 phrase (par modèle)")
    print("=" * 80)
    print(f"  System Prompt  : {SYSTEM_PROMPT_FILE}")
    print(f"  User Prompt    : {USER_PROMPT_FILE}")
    print(f"  {len(FILTER_QUESTION_KEYS)} questions par appel  |  {len(models)} modèles")
    print(f"  Appels par phrase : {len(models)}  (vs {len(models)*9} dans v5-parallel)")
    print(f"\n  Questions du filtre :")
    for qk, qtxt in FILTER_QUESTIONS.items():
        print(f"    {qk} : {qtxt}")
    print(f"\n  Décision : PASSE si ≥1 question OUI majoritaire, sinon DESCRIPTIF")
    for m in models:
        p = MODEL_PRICING.get(m, DEFAULT_PRICING)
        print(f"  * {m}  in:${p['input']}/M  out:${p['output']}/M")
    print()

    seg_root  = Path(SEGMENTS_INPUT_DIR)
    seg_files = sorted(seg_root.rglob("*.json"))
    seg_files = [p for p in seg_files
                 if not p.name.endswith("_filtre_descriptif.json")
                 and not p.name.endswith("_classification.json")]

    if not seg_files:
        print("[ERREUR] Aucun .json source trouvé")
        return

    print(f"  {len(seg_files)} fichier(s) source(s) trouvé(s)\n")

    all_results         = []
    ok, skipped, errors = 0, 0, 0

    for i, seg_path in enumerate(seg_files, 1):
        rel      = seg_path.relative_to(seg_root)
        dest_dir = seg_path.parent
        base_name = seg_path.stem
        json_out  = dest_dir / f"{base_name}_filtre_descriptif.json"

        print(f"\n{'='*60}")
        print(f"[{i}/{len(seg_files)}] {rel}")
        print(f"{'='*60}")

        if json_out.exists():
            print(f"   Skip — {json_out.name} existe déjà.")
            with open(json_out, "r", encoding="utf-8") as f:
                cached = json.load(f)
            loaded = []
            for item in cached:
                loaded.append(FilterResult(**{
                    k: item[k]
                    for k in FilterResult.__dataclass_fields__
                    if k in item
                }))
            existing_keys = {(r.source_file, r.phrase_index) for r in all_results}
            for fc in loaded:
                key = (fc.source_file, fc.phrase_index)
                if key not in existing_keys:
                    all_results.append(fc)
                    existing_keys.add(key)
            skipped += 1
            continue

        try:
            results = process_file(seg_path, models, stats)
            export_file_results(results, dest_dir, base_name, models)

            existing_keys = {(r.source_file, r.phrase_index) for r in all_results}
            for fc in results:
                key = (fc.source_file, fc.phrase_index)
                if key not in existing_keys:
                    all_results.append(fc)
                    existing_keys.add(key)
            ok += 1

        except Exception as e:
            import traceback
            print(f"   ERREUR : {e}")
            traceback.print_exc()
            errors += 1

    ts = time.strftime("%Y%m%d_%H%M%S")
    if all_results:
        export_complete_summary(all_results, models, ts, stats, Path(OUTPUT_DIR))

    stats.print_summary()

    total      = len(all_results)
    passe      = sum(1 for r in all_results if r.decision == "PASSE")
    descriptif = sum(1 for r in all_results if r.decision == "DESCRIPTIF")

    print("\n" + "=" * 80)
    print("RÉSUMÉ FINAL — FILTRE DESCRIPTIF")
    print("=" * 80)
    print(f"  Traités:{ok}  Skipés:{skipped}  Erreurs:{errors}  "
          f"Fichiers:{len(seg_files)}")
    print(f"  Phrases totales  : {total}")
    print(f"  PASSE            : {passe}  ({round(passe/total*100,1) if total else 0}%)")
    print(f"  DESCRIPTIF       : {descriptif}  ({round(descriptif/total*100,1) if total else 0}%)")
    print(f"\n  → Les phrases PASSE sont exportées dans phrases_passees_<timestamp>.json")
    print(f"    Prêtes pour le script de classification ROI/Notoriété/Obligation")


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nInterruption utilisateur")
    except Exception as e:
        import traceback
        print(f"\nErreur fatale : {e}")
        traceback.print_exc()