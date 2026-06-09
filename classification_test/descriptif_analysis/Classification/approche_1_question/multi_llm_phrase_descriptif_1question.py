"""
Classification Descriptif - Approche 1 Question
Classifie les phrases : Descriptif (pure information) vs Non-Descriptif (contient valeur)
5 modèles LLM via OpenRouter, vote majoritaire
"""

import os
import re
import json
import time
import random
import threading
import uuid
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, asdict, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
import requests
import numpy as np

try:
    from langfuse import Langfuse
    try:
        from langfuse.types import TraceContext
    except ImportError:
        TraceContext = None
except ImportError:
    Langfuse = None
    TraceContext = None

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(ENV_FILE if ENV_FILE.exists() else None)


class NoopObservation:
    def end(self, **kwargs):
        return None


class SafeLangfuse:
    def __init__(self):
        self.client = None
        self.enabled = False

        if Langfuse is None:
            print("Langfuse non installe dans cet interpreteur : suivi desactive")
            return

        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")
        host = (
            os.environ.get("LANGFUSE_HOST")
            or os.environ.get("LANGFUSE_BASE_URL")
            or "https://cloud.langfuse.com"
        )

        if not public_key or not secret_key:
            print("Cles Langfuse manquantes : suivi desactive")
            return

        try:
            self.client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            self.enabled = True
            print(f"Langfuse initialise ({host})")
        except Exception as e:
            print(f"Langfuse desactive : {e}")

    def create_trace_id(self):
        if self.enabled:
            try:
                return self.client.create_trace_id()
            except Exception:
                pass
        return uuid.uuid4().hex

    def trace_context(self, trace_id):
        if TraceContext is None:
            return None
        return TraceContext(trace_id=trace_id)

    def start_observation(self, **kwargs):
        if not self.enabled:
            return NoopObservation()
        try:
            return self.client.start_observation(**kwargs)
        except Exception as e:
            print(f"Langfuse observation ignoree : {e}")
            return NoopObservation()

    def end_observation_success(
        self,
        obs,
        output,
        input_tokens,
        output_tokens,
        cost_usd,
        cached_tokens=0,
        cache_write_tokens=0,
    ):
        usage_details = {
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
        }
        if cached_tokens:
            usage_details["cached_tokens"] = cached_tokens
        if cache_write_tokens:
            usage_details["cache_write_tokens"] = cache_write_tokens
        metadata = {
            "cost_usd": round(cost_usd, 8),
            "cached_tokens": cached_tokens,
            "cache_write_tokens": cache_write_tokens,
        }
        try:
            if hasattr(obs, "update"):
                obs.update(
                    output=output,
                    usage_details=usage_details,
                    cost_details={"total": cost_usd},
                    metadata=metadata,
                )
                obs.end()
            else:
                obs.end(
                    output=output,
                    usage_details=usage_details,
                    cost_details={"total": cost_usd},
                    metadata=metadata,
                )
        except TypeError:
            obs.end()
        except Exception as e:
            print(f"Langfuse observation fin ignoree : {e}")

    def end_observation_error(self, obs, error):
        try:
            if hasattr(obs, "update"):
                obs.update(level="ERROR", status_message=str(error))
                obs.end()
            else:
                obs.end(level="ERROR", status_message=str(error))
        except Exception:
            pass

    def create_event(self, **kwargs):
        if not self.enabled:
            return None
        try:
            return self.client.create_event(**kwargs)
        except Exception as e:
            print(f"Langfuse event ignore : {e}")
            return None

    def create_score(self, **kwargs):
        if not self.enabled:
            return None
        try:
            return self.client.create_score(**kwargs)
        except Exception as e:
            print(f"Langfuse score ignore : {e}")
            return None

    def flush(self):
        if not self.enabled:
            return
        try:
            self.client.flush()
        except Exception as e:
            print(f"Langfuse flush ignore : {e}")


langfuse = SafeLangfuse()

# ── Configuration ──────────────────────────────────────────────────────────────
SEGMENTS_INPUT_DIR = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\Decoupage\phrases"
OUTPUT_DIR = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\descriptif_analysis\Classification\approche_1_question\resultats_classification_descriptif_1question"
SYSTEM_PROMPT_FILE = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\descriptif_analysis\Classification\approche_1_question\system_prompt_phrase.txt"
USER_PROMPT_FILE = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\descriptif_analysis\Classification\approche_1_question\user_prompt_phrase.txt"
QUESTIONS_FILE = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\descriptif_analysis\Classification\approche_1_question\liste_questions.txt"

os.makedirs(OUTPUT_DIR, exist_ok=True)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("OPENROUTER_API_KEY manquante")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
EUR_USD_RATE = 1.08

def usd_to_eur(usd: float) -> float:
    return usd / EUR_USD_RATE

MODEL_PRICING = {
    "meta-llama/llama-3.3-70b-instruct": {"input": 0.10, "output": 0.32},
    "google/gemma-3-27b-it": {"input": 0.08, "output": 0.16},
    "mistralai/mistral-nemo": {"input": 0.02, "output": 0.03},
    "qwen/qwen3-8b": {"input": 0.05, "output": 0.40},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
}
DEFAULT_PRICING = {"input": 0.10, "output": 0.10}

def compute_call_cost_usd(model_name: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model_name, DEFAULT_PRICING)
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

MODELS = [
    "meta-llama/llama-3.3-70b-instruct",
    "google/gemma-3-27b-it",
    "mistralai/mistral-nemo",
    "qwen/qwen3-8b",
    "openai/gpt-4o-mini",
]

MAX_TOKENS = 64
MAX_RETRIES = 5
BACKOFF_BASE = 2.0
MAX_WORKERS = 5
PROMPT_CACHE_ENABLED = os.environ.get("OPENROUTER_PROMPT_CACHE", "true").lower() in ("1", "true", "yes", "oui")
PROMPT_CACHE_TTL = os.environ.get("OPENROUTER_PROMPT_CACHE_TTL", "ephemeral")
PROMPT_CACHE_SESSION_ID = os.environ.get(
    "OPENROUTER_SESSION_ID",
    "classification-descriptif-1question-v1",
)

EXPLICIT_CACHE_QWEN_MODELS = {
    "deepseek/deepseek-v3.2",
    "qwen/qwen3-max",
    "qwen/qwen-plus",
    "qwen/qwen3.6-plus",
    "qwen/qwen3-coder-plus",
    "qwen/qwen3-coder-flash",
}

# ── Chargement ─────────────────────────────────────────────────────────────────
def load_question() -> str:
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and line.startswith("[DESC]"):
                return re.sub(r'^\[DESC\]\s*', '', line).strip()
QUESTION_TEXT = load_question()

def load_system_prompt() -> str:
    with open(SYSTEM_PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()

def load_user_prompt_template() -> str:
    with open(USER_PROMPT_FILE, "r", encoding="utf-8") as f:
        return f.read().strip()


SYSTEM_PROMPT = load_system_prompt()
USER_PROMPT_TEMPLATE = load_user_prompt_template()


def _cache_control() -> dict:
    cache_control = {"type": "ephemeral"}
    if PROMPT_CACHE_TTL == "1h":
        cache_control["ttl"] = "1h"
    return cache_control


def supports_explicit_prompt_cache(model_name: str) -> bool:
    return (
        model_name.startswith("anthropic/")
        or model_name.startswith("google/gemini")
        or model_name in EXPLICIT_CACHE_QWEN_MODELS
    )


def build_user_instruction() -> str:
    return (
        f"Question : {QUESTION_TEXT}\n\n"
        'Reponds UNIQUEMENT avec ce JSON valide (sans markdown) :\n'
        '{"reponse": "oui"} ou {"reponse": "non"}'
    )


def build_messages(model_name: str, phrase: str) -> list:
    user_instruction = build_user_instruction()
    phrase_message = f'Phrase : "{phrase}"'

    if PROMPT_CACHE_ENABLED and supports_explicit_prompt_cache(model_name):
        return [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": _cache_control(),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_instruction,
                        "cache_control": _cache_control(),
                    }
                ],
            },
            {"role": "user", "content": phrase_message},
        ]

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_instruction},
        {"role": "user", "content": phrase_message},
    ]

# ── Dataclasses ────────────────────────────────────────────────────────────────
@dataclass
class Phrase:
    phrase: str
    phrase_index: int
    source_file: str
    source_folder: str

@dataclass
class CallResult:
    model_name: str
    reponse: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    cost_eur: float = 0.0
    duration_s: float = 0.0
    erreur: str = None

@dataclass
class FinalClassification:
    phrase: str
    phrase_index: int
    source_file: str
    source_folder: str
    descriptif: str
    agreement_rate: float = 0.5
    cost_usd_phrase: float = 0.0
    cost_eur_phrase: float = 0.0
    duration_s_phrase: float = 0.0
    detail_appels: list = field(default_factory=list)

# ── Stats ──────────────────────────────────────────────────────────────────────
class StatsAccumulator:
    def __init__(self, models: list):
        self.models = models
        self.start_time = time.time()
        self._lock = threading.Lock()
        self.cost_usd_by_model = {m: 0.0 for m in models}
        self.tokens_in_by_model = {m: 0 for m in models}
        self.tokens_out_by_model = {m: 0 for m in models}
        self.cached_tokens_by_model = {m: 0 for m in models}
        self.cache_write_tokens_by_model = {m: 0 for m in models}
        self.calls_by_model = {m: 0 for m in models}
        self.errors_by_model = {m: 0 for m in models}
        self.cost_usd_by_file = {}
        self.phrase_count = 0

    def record_call(
        self,
        model: str,
        tok_in: int,
        tok_out: int,
        error: bool,
        source_file: str,
        cached_tokens: int = 0,
        cache_write_tokens: int = 0,
    ):
        cost = compute_call_cost_usd(model, tok_in, tok_out)
        with self._lock:
            self.cost_usd_by_model[model] += cost
            self.tokens_in_by_model[model] += tok_in
            self.tokens_out_by_model[model] += tok_out
            self.cached_tokens_by_model[model] += cached_tokens
            self.cache_write_tokens_by_model[model] += cache_write_tokens
            self.calls_by_model[model] += 1
            if error:
                self.errors_by_model[model] += 1
            self.cost_usd_by_file[source_file] = self.cost_usd_by_file.get(source_file, 0.0) + cost

    def error_rate(self, model):
        calls = self.calls_by_model.get(model, 0)

        if calls == 0:
            return 0.0

        return self.errors_by_model.get(model, 0) / calls
    @property
    def total_cost_usd(self) -> float:
        return sum(self.cost_usd_by_model.values())

    @property
    def elapsed_s(self) -> float:
        return time.time() - self.start_time

    def print_summary(self):
        n = self.phrase_count
        elaps = self.elapsed_s
        total_eur = usd_to_eur(self.total_cost_usd)
        print(f"\n  Cout total : ${self.total_cost_usd:.4f} / EUR{total_eur:.4f}")
        if n:
            print(f"  Cout/phrase : ${self.total_cost_usd/n:.6f} / EUR{usd_to_eur(self.total_cost_usd)/n:.6f}")
        cached = sum(self.cached_tokens_by_model.values())
        written = sum(self.cache_write_tokens_by_model.values())
        if cached or written:
            print(f"  Prompt cache : {cached} tokens lus / {written} tokens ecrits")
        print(f"  Temps total : {elaps/60:.1f} min")

# ── API ────────────────────────────────────────────────────────────────────────
def _extract_content_and_usage(data: dict) -> tuple:
    choice = data["choices"][0]
    msg = choice.get("message", {})
    content = msg.get("content") or ""
    usage = data.get("usage", {})
    prompt_details = usage.get("prompt_tokens_details", {}) or {}
    return (
        content.strip(),
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        prompt_details.get("cached_tokens", 0),
        prompt_details.get("cache_write_tokens", 0),
    )

def _call_openrouter(model_name: str, messages: list, trace_context= None) -> tuple:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/jiheneguesmi/Business-Value-Knowledge-Graph",
        "X-Title": "Business Value Classification",
    }
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": 0,
        "max_tokens": MAX_TOKENS,
    }
    if PROMPT_CACHE_ENABLED:
        payload["session_id"] = PROMPT_CACHE_SESSION_ID

    obs = langfuse.start_observation(
        trace_context=trace_context,
        name=f"llm-call-{model_name.split('/')[-1]}",
        as_type="generation",
        model=model_name,
        input=messages,
        model_parameters={"temperature": 0, "max_tokens": MAX_TOKENS},
    )
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(OPENROUTER_URL, headers=headers,
                                 json=payload, timeout=120)
            if resp.status_code == 429:
                wait = BACKOFF_BASE ** attempt + random.uniform(0, 2.0)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            content, tok_in, tok_out, cached_tokens, cache_write_tokens = _extract_content_and_usage(resp.json())

            cost_usd = compute_call_cost_usd(
                model_name,
                tok_in,
                tok_out
            )
            langfuse.end_observation_success(
                obs,
                output=content,
                input_tokens=tok_in,
                output_tokens=tok_out,
                cost_usd=cost_usd,
                cached_tokens=cached_tokens,
                cache_write_tokens=cache_write_tokens,
            )
            return content, tok_in, tok_out, cached_tokens, cache_write_tokens

        except Exception as e:
            if attempt == MAX_RETRIES:
                langfuse.end_observation_error(obs, e)
                raise
            time.sleep(BACKOFF_BASE ** attempt)

    raise Exception(f"Echec apres {MAX_RETRIES} tentatives pour {model_name}")

def _parse_reponse(raw: str) -> str:
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw).strip()
    try:
        parsed = json.loads(raw)
        rep = str(parsed.get("reponse", "non")).lower().strip()
        return "oui" if rep in ("oui", "yes", "true", "1") else "non"
    except:
        return "oui" if "oui" in raw.lower() else "non"

# ── Appels ─────────────────────────────────────────────────────────────────────
def call_one(
    phrase_obj: Phrase,
    model_name: str,
    stats: StatsAccumulator,
    trace_context=None
) -> CallResult:
    messages = build_messages(model_name, phrase_obj.phrase)
    t0 = time.time()
    try:
        raw, tok_in, tok_out, cached_tokens, cache_write_tokens = _call_openrouter(
            model_name,
            messages,
            trace_context=trace_context,
        )
        duration = time.time() - t0
        reponse = _parse_reponse(raw)
        cost_usd = compute_call_cost_usd(model_name, tok_in, tok_out)
        
        stats.record_call(
            model_name,
            tok_in,
            tok_out,
            False,
            phrase_obj.source_file,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        return CallResult(
            model_name=model_name,
            reponse=reponse,
            input_tokens=tok_in,
            output_tokens=tok_out,
            cached_tokens=cached_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost_usd,
            cost_eur=usd_to_eur(cost_usd),
            duration_s=round(duration, 2),
        )
    except Exception as e:
        duration = time.time() - t0
        stats.record_call(model_name, 0, 0, True, phrase_obj.source_file)
        return CallResult(
            model_name=model_name,
            reponse="non",
            duration_s=round(duration, 2),
            erreur=str(e),
        )

def majority_vote(call_results: list) -> str:
    valid = [r for r in call_results if not r.erreur]
    if not valid:
        return "non"
    votes_oui = sum(1 for r in valid if r.reponse == "oui")
    return "oui" if votes_oui > len(valid) / 2 else "non"

# ── Traitement ─────────────────────────────────────────────────────────────────
def process_phrase(phrase_obj: Phrase, models: list, stats: StatsAccumulator, phrase_num: int, total_phrases: int) -> FinalClassification:
    t_phrase = time.time()

    trace_id = langfuse.create_trace_id()
    trace_context = langfuse.trace_context(trace_id)

    langfuse.create_event(
        trace_context=trace_context,
        name="classification-start",
        input={
            "phrase": phrase_obj.phrase,
            "question": QUESTION_TEXT
        },
        metadata={
            "source_file": phrase_obj.source_file,
            "source_folder": phrase_obj.source_folder,
            "phrase_index": phrase_obj.phrase_index
        }
    )
    all_calls = []
    _lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(call_one, phrase_obj, model, stats, trace_context): model for model in models}
        for future in as_completed(futures):
            result = future.result()  #  CallResult directement, pas de tuple
            with _lock:
                all_calls.append(result)

    reponse_finale = majority_vote(all_calls)
    valid = [r for r in all_calls if not r.erreur]
    phrase_agreement = (
        max(
            sum(1 for r in valid if r.reponse == "oui"),
            len(valid) - sum(1 for r in valid if r.reponse == "oui")
        ) / len(valid)
        if valid and len(valid) > 1 else 0.5
    )

    phrase_cost_usd = sum(r.cost_usd for r in all_calls)
    phrase_cost_eur = usd_to_eur(phrase_cost_usd)
    phrase_duration = time.time() - t_phrase

    detail = [
        {
            "model": r.model_name.split("/")[-1][:20],
            "reponse": r.reponse,
            "erreur": r.erreur,
            "cost_eur": round(r.cost_eur, 7),
            "cached_tokens": r.cached_tokens,
            "cache_write_tokens": r.cache_write_tokens,
            "duration_s": r.duration_s
        }
        for r in all_calls
    ]

    label = "Descriptif" if reponse_finale == "oui" else "Non-descriptif"
    print(f"  [{phrase_num:>4}/{total_phrases}] '{phrase_obj.phrase[:50]:<50}' {label:<16} EUR{phrase_cost_eur:.6f} {phrase_duration:.1f}s")

    stats.phrase_count += 1

    langfuse.create_score(
        trace_id=trace_id,
        name="agreement_rate",
        value=float(phrase_agreement)
    )

    langfuse.create_score(
        trace_id=trace_id,
        name="final_classification",
        value=1 if reponse_finale == "oui" else 0
    )

    langfuse.create_event(
        trace_context=trace_context,
        name="classification-result",
        output={
            "classification": reponse_finale,
            "agreement_rate": phrase_agreement,
            "cost_eur": round(phrase_cost_eur, 6),
            "cost_usd": round(phrase_cost_usd, 6),
            "nb_models": len(valid)
        }
    )

    return FinalClassification(
        phrase=phrase_obj.phrase,
        phrase_index=phrase_obj.phrase_index,
        source_file=phrase_obj.source_file,
        source_folder=phrase_obj.source_folder,
        descriptif=reponse_finale,
        agreement_rate=round(phrase_agreement, 3),
        cost_usd_phrase=round(phrase_cost_usd, 7),
        cost_eur_phrase=round(phrase_cost_eur, 7),
        duration_s_phrase=round(phrase_duration, 2),
        detail_appels=detail,
    )



def process_file(seg_path: Path, models: list, stats: StatsAccumulator) -> list:
    with open(seg_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    phrases = [Phrase(phrase=item["phrase"], phrase_index=item["phrase_index"], source_file=item.get("source_file", seg_path.name), source_folder=item.get("source_folder", "")) for item in data if item.get("phrase", "").strip()]
    
    n_phrases = len(phrases)
    print(f"\n   {seg_path.name} : {n_phrases} phrases\n")
    
    results = []
    for i, phrase_obj in enumerate(phrases, 1):
        result = process_phrase(phrase_obj, models, stats, i, n_phrases)
        results.append(result)
    return results

# ── Export ─────────────────────────────────────────────────────────────────────
def export_file_results(results: list, dest_dir: Path, base_name: str, models: list):
    json_out = dest_dir / f"{base_name}v2_classification_descriptif_1question.json"
    xl_out = dest_dir / f"{base_name}v2_classification_descriptif_1question.xlsx"

    with open(json_out, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, ensure_ascii=False, indent=2)

    rows = []
    for r in results:
        row = {
            "Source_File": r.source_file,
            "Phrase_Index": r.phrase_index,
            "Phrase": r.phrase,
            "Classification": "Descriptif" if r.descriptif == "oui" else "Non-descriptif",
            "Accord_%": round(r.agreement_rate * 100, 1),
            "Cost_EUR": r.cost_eur_phrase,
            "Cache_Read_Tokens": sum(d.get("cached_tokens", 0) for d in r.detail_appels),
            "Cache_Write_Tokens": sum(d.get("cache_write_tokens", 0) for d in r.detail_appels),
            "Duration_s": r.duration_s_phrase,
        }
        for m in models:
            short = m.split("/")[-1][:20]
            match = next((d for d in r.detail_appels if d["model"] == short), None)
            row[short] = match["reponse"] if match and not match["erreur"] else "ERR"
        rows.append(row)

    df = pd.DataFrame(rows)
    with pd.ExcelWriter(xl_out, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Classification", index=False)

    print(f"\n   Export -> {json_out.name}")
    print(f"   Export -> {xl_out.name}")

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
            "Source_File":      r.source_file,
            "Source_Folder":    r.source_folder,
            "Phrase_Index":     r.phrase_index,
            "Phrase":           r.phrase,
            "Classification":   "Descriptif" if r.descriptif == "oui" else "Non-descriptif",
            "Accord_%":         round(r.agreement_rate * 100, 1),
            "Cost_EUR":         r.cost_eur_phrase,
            "Duration_s":       r.duration_s_phrase,
        }
        for m in models:
            short = m.split("/")[-1][:20]
            match = next(
                (d for d in r.detail_appels if d["model"] == short),
                None,
            )
            row[short] = match["reponse"] if match and not match["erreur"] else "ERR"
        rows.append(row)
    df_main = pd.DataFrame(rows)

    # ── Sheet 2 : Stats_Par_Model ─────────────────────────────────────────────
    rows_models = []
    for m in models:
        rows_models.append({
            "Modele":         m.split("/")[-1][:30],
            "Modele_complet": m,
            "Tokens_Input":   stats.tokens_in_by_model.get(m, 0),
            "Tokens_Output":  stats.tokens_out_by_model.get(m, 0),
            "Cache_Read_Tokens": stats.cached_tokens_by_model.get(m, 0),
            "Cache_Write_Tokens": stats.cache_write_tokens_by_model.get(m, 0),
            "Cout_USD":       round(stats.cost_usd_by_model.get(m, 0), 6),
            "Cout_EUR":       round(usd_to_eur(stats.cost_usd_by_model.get(m, 0)), 6),
            "Nb_Appels":      stats.calls_by_model.get(m, 0),
            "Nb_Erreurs":     stats.errors_by_model.get(m, 0),
            "Taux_Erreur_%":  round(stats.error_rate(m) * 100, 2)
                              if stats.calls_by_model.get(m, 0) > 0 else 0,
        })
    df_models = pd.DataFrame(rows_models)

    # ── Sheet 3 : Stats_Globales ──────────────────────────────────────────────
    total_phrases  = len(all_results)
    total_cost_eur = usd_to_eur(stats.total_cost_usd)
    df_global = pd.DataFrame([{
        "Timestamp":               timestamp,
        "Total_Phrases":           total_phrases,
        "Total_Cout_EUR":          round(total_cost_eur, 6),
        "Cout_Moyen_EUR_Phrase":   round(total_cost_eur / total_phrases, 7) if total_phrases else 0,
        "Duree_Totale_min":        round(stats.elapsed_s / 60, 2),
        "Nb_Modeles":              len(models),
        "Nb_Questions":            1,
        "Prompt_Cache_Enabled":    PROMPT_CACHE_ENABLED,
        "Prompt_Cache_Session_ID": PROMPT_CACHE_SESSION_ID,
        "Cache_Read_Tokens":       sum(stats.cached_tokens_by_model.values()),
        "Cache_Write_Tokens":      sum(stats.cache_write_tokens_by_model.values()),
        "Question_DESC":           QUESTION_TEXT,
        "Modeles_Utilises":        " | ".join(m.split("/")[-1] for m in models),
    }])

    # ── Export Excel ──────────────────────────────────────────────────────────
    excel_path = output_dir / f"recapitulatif_complet_{timestamp}.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_main.to_excel(writer,   sheet_name="Toutes_Phrases",  index=False)
        df_models.to_excel(writer, sheet_name="Stats_Par_Model", index=False)
        df_global.to_excel(writer, sheet_name="Stats_Globales",  index=False)
    print(f"\n   Export Excel complet -> {excel_path.name}")

    # ── Export Tensor NPY ─────────────────────────────────────────────────────
    # Format(n_clients, max_phrases, n_models, n_questions)
    # Ici n_questions = 1  (la question DESC)
    QUESTION_KEY_DESC = "desc_1"

    clients = sorted({r.source_folder for r in all_results})
    client_to_index = {c: i for i, c in enumerate(clients)}

    phrases_by_client = {c: [] for c in clients}
    for result in sorted(
        all_results,
        key=lambda r: (r.source_folder, r.source_file, r.phrase_index)
    ):
        phrases_by_client[result.source_folder].append(result)

    n_clients   = len(clients)
    n_models    = len(models)
    n_questions = 1   # une seule question DESC
    max_phrases = max(len(v) for v in phrases_by_client.values()) if phrases_by_client else 0

    # Shape : (n_clients, max_phrases, n_models, n_questions)  — même que script 2
    tensor = np.zeros((n_clients, max_phrases, n_models, n_questions), dtype=np.int8)
    model_short_names = [m.split("/")[-1][:20] for m in models]

    for client, phrase_results in phrases_by_client.items():
        ci = client_to_index[client]
        for pi, result in enumerate(phrase_results):
            for mi, model_short in enumerate(model_short_names):
                # qi = 0 : seul axe question
                match = next(
                    (d for d in result.detail_appels if d["model"] == model_short),
                    None,
                )
                tensor[ci, pi, mi, 0] = (
                    1 if (match and not match.get("erreur") and match["reponse"] == "oui")
                    else 0
                )

    npy_path  = output_dir / f"tensor_complet_{timestamp}.npy"
    meta_path = output_dir / f"tensor_complet_{timestamp}_meta.json"
    np.save(npy_path, tensor)

    meta = {
        "shape":    list(tensor.shape),
        "dtype":    "int8",
        "axes":     ["client", "phrase", "model", "question"],
        "values":   {"1": "oui", "0": "non"},
        "clients":  clients,
        "models":   model_short_names,
        # Clé identique au script 2 pour pouvoir concaténer les tenseurs
        "questions":      [QUESTION_KEY_DESC],
        "questions_text": {QUESTION_KEY_DESC: QUESTION_TEXT},
        "n_clients":               n_clients,
        "max_phrases_per_client":  max_phrases,
        "n_models":                n_models,
        "n_questions":             n_questions,
        "timestamp":               timestamp,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"   Tensor NPY -> {npy_path.name}  shape={tensor.shape}")
    print(f"   Metadonnees -> {meta_path.name}")

    return excel_path, npy_path

# ── Main ───────────────────────────────────────────────────────────────────────
def run():
    stats = StatsAccumulator(MODELS)

    print("=" * 80)
    print("CLASSIFICATION DESCRIPTIF — Approche 1 Question")
    print("=" * 80)
    print("=== SYSTEM PROMPT EFFECTIF ===")
    print(SYSTEM_PROMPT[:200])
    print("=== QUESTION ===")
    print(QUESTION_TEXT)

    print(f"  Modeles : {len(MODELS)}")
    print()

    seg_root = Path(SEGMENTS_INPUT_DIR)
    seg_files = sorted(seg_root.rglob("*.json"))
    seg_files = [p for p in seg_files if not p.name.endswith("_classification.json") and not "_classification_descriptif" in p.name]

    if not seg_files:
        print("[ERREUR] Aucun fichier source")
        return

    print(f"  {len(seg_files)} fichier(s)\n")

    all_results = []
    ok, skipped, errors = 0, 0, 0

    for i, seg_path in enumerate(seg_files, 1):
        rel = seg_path.relative_to(seg_root)
        dest_dir = seg_path.parent
        base_name = seg_path.stem
        json_out = dest_dir / f"{base_name}_classification_descriptif_1question.json"

        print(f"\n{'='*60}\n[{i}/{len(seg_files)}] {rel}\n{'='*60}")

        if json_out.exists():
            print(f"   Skip — {json_out.name} existe deja")
            with open(json_out, "r", encoding="utf-8") as f:
                cached = json.load(f)
            for item in cached:
                all_results.append(FinalClassification(**{k: item[k] for k in FinalClassification.__dataclass_fields__ if k in item}))
            skipped += 1
            continue

        try:
            results = process_file(seg_path, MODELS, stats)
            export_file_results(results, dest_dir, base_name, MODELS)
            all_results.extend(results)
            ok += 1
            print(f"\n   Fichier termine : {len(results)} phrases")
        except Exception as e:
            print(f"   ERREUR : {e}")
            errors += 1

    stats.print_summary()
    ts = time.strftime("%Y%m%d_%H%M%S")
    if all_results:
        export_complete_summary(all_results, MODELS, ts, stats, Path(OUTPUT_DIR))

    total = len(all_results)
    desc_count = sum(1 for r in all_results if r.descriptif == "oui")

    print("\n" + "=" * 80)
    print("RESUME FINAL")
    print("=" * 80)
    print(f"  Fichiers : {len(seg_files)} (traites:{ok} skipes:{skipped} erreurs:{errors})")
    print(f"  Phrases : {total}")
    print(f"  Descriptif : {desc_count} ({round(desc_count/total*100,1) if total else 0}%)")

    langfuse.flush()

if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nInterruption")
    except Exception as e:
        import traceback
        print(f"\nErreur : {e}")
        traceback.print_exc()
