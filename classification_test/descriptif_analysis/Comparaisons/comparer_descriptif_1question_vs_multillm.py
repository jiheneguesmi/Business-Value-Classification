"""
Script : Comparaison des approches descriptif
Version 2 : DESCRIPTIF 1 QUESTION vs MULTI-LLM (9 questions)
"""

import os
import json
import pandas as pd
from pathlib import Path
from dataclasses import dataclass

# ── Chemins ────────────────────────────────────────────────────────────────────
MULTI_LLM_RESULTS_DIR = r"F:\Jihene\business_value_classification\classification_test\Classification\resultats_classification_phrases"
DESCRIPTIF_1Q_RESULTS_DIR = r"F:\Jihene\business_value_classification\classification_test\Classification\resultats_classification_phrases_descriptif_elimination"
OUTPUT_DIR = r"F:\Jihene\business_value_classification\classification_test\analyse_comparative\descriptif_analysis\Comparaisons\resultats_1question_vs_multillm"

os.makedirs(OUTPUT_DIR, exist_ok=True)


@dataclass
class ComparisonResult:
    phrase: str
    phrase_index: int
    source_file: str
    multi_category: str
    descriptif_1q_label: str
    agreement: bool
    agreement_type: str


def load_multi_llm_results() -> dict:
    results = {}
    multi_llm_dir = Path(MULTI_LLM_RESULTS_DIR)
    json_files = list(multi_llm_dir.glob("*_classification.json"))
    print(f"  Chargement Multi-LLM : {len(json_files)} fichiers")
    
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                key = (item["source_file"], item["phrase_index"])
                results[key] = item
            print(f"    ✓ {json_file.name}")
        except Exception as e:
            print(f"    ✗ {json_file.name} : {e}")
    return results


def load_descriptif_1q_results() -> dict:
    results = {}
    desc_1q_dir = Path(DESCRIPTIF_1Q_RESULTS_DIR)
    json_files = list(desc_1q_dir.glob("*_classification_descriptif_elimination.json"))
    print(f"  Chargement Descriptif 1 Question : {len(json_files)} fichiers")
    
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                key = (item["source_file"], item["phrase_index"])
                results[key] = item
            print(f"    ✓ {json_file.name}")
        except Exception as e:
            print(f"    ✗ {json_file.name} : {e}")
    return results


def compare_results(multi_llm: dict, descriptif_1q: dict) -> list:
    common_keys = set(multi_llm.keys()) & set(descriptif_1q.keys())
    print(f"\n  Phrases en commun : {len(common_keys)}")
    
    comparisons = []
    for source_file, phrase_index in sorted(common_keys):
        m = multi_llm[(source_file, phrase_index)]
        d1q = descriptif_1q[(source_file, phrase_index)]
        
        multi_category = m.get("categorie", "?")
        multi_is_description = multi_category == "Description"
        
        desc_1q_label = "Descriptif" if d1q.get("descriptif") == "oui" else "Non-descriptif"
        desc_1q_is_descriptif = desc_1q_label == "Descriptif"
        
        agree = multi_is_description == desc_1q_is_descriptif
        
        if agree and multi_is_description:
            agreement_type = "Accord_Descriptif"
        elif agree and not multi_is_description:
            agreement_type = "Accord_Non-Descriptif"
        elif multi_is_description and not desc_1q_is_descriptif:
            agreement_type = "Divergence_Multi-Desc"
        else:
            agreement_type = "Divergence_1Q-Desc"
        
        comparisons.append(ComparisonResult(
            phrase=m.get("phrase", ""),
            phrase_index=phrase_index,
            source_file=source_file,
            multi_category=multi_category,
            descriptif_1q_label=desc_1q_label,
            agreement=agree,
            agreement_type=agreement_type,
        ))
    
    return comparisons


def compute_stats(comparisons: list) -> dict:
    total = len(comparisons)
    agree = sum(1 for c in comparisons if c.agreement)
    
    type_counts = {}
    for c in comparisons:
        type_counts[c.agreement_type] = type_counts.get(c.agreement_type, 0) + 1
    
    return {
        "total": total,
        "agree_count": agree,
        "agree_%": round(agree / total * 100, 2) if total > 0 else 0,
        "type_counts": type_counts,
    }


def export_results(comparisons: list, stats: dict, output_dir: Path):
    # Détails
    rows = []
    for c in comparisons:
        rows.append({
            "Source_File": c.source_file,
            "Phrase_Index": c.phrase_index,
            "Phrase": c.phrase[:100],
            "Multi_LLM": c.multi_category,
            "Descriptif_1Q": c.descriptif_1q_label,
            "Agreement": "OUI" if c.agreement else "NON",
            "Type": c.agreement_type,
        })
    df = pd.DataFrame(rows)
    
    # Divergences
    divergences = [c for c in comparisons if not c.agreement]
    rows_div = []
    for c in divergences:
        rows_div.append({
            "Source_File": c.source_file,
            "Phrase_Index": c.phrase_index,
            "Phrase": c.phrase[:80],
            "Multi_LLM": c.multi_category,
            "Descriptif_1Q": c.descriptif_1q_label,
            "Type": c.agreement_type,
        })
    df_div = pd.DataFrame(rows_div) if rows_div else pd.DataFrame()
    
    # Export
    excel_path = output_dir / "comparaison_1question_vs_multillm.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Toutes_Comparaisons", index=False)
        
        df_stats = pd.DataFrame([
            {"Métrique": "Total phrases", "Valeur": stats["total"]},
            {"Métrique": "Accord (nombre)", "Valeur": stats["agree_count"]},
            {"Métrique": "Accord (%)", "Valeur": f"{stats['agree_%']}%"},
            {"Métrique": "", "Valeur": ""},
            {"Métrique": "Accord Descriptif", "Valeur": stats["type_counts"].get("Accord_Descriptif", 0)},
            {"Métrique": "Accord Non-Descriptif", "Valeur": stats["type_counts"].get("Accord_Non-Descriptif", 0)},
            {"Métrique": "Divergence (Multi→Desc)", "Valeur": stats["type_counts"].get("Divergence_Multi-Desc", 0)},
            {"Métrique": "Divergence (1Q→Desc)", "Valeur": stats["type_counts"].get("Divergence_1Q-Desc", 0)},
        ])
        df_stats.to_excel(writer, sheet_name="Statistiques", index=False, header=False)
        
        if not df_div.empty:
            df_div.to_excel(writer, sheet_name="Divergences", index=False)
    
    print(f"\n   Export -> {excel_path.name}")


def run():
    print("=" * 80)
    print("COMPARAISON : DESCRIPTIF 1 QUESTION vs MULTI-LLM")
    print("=" * 80)
    
    print("\n[1/3] Chargement des résultats...")
    multi_llm = load_multi_llm_results()
    desc_1q = load_descriptif_1q_results()
    
    print(f"\n  Total Multi-LLM : {len(multi_llm)}")
    print(f"  Total Descriptif 1Q : {len(desc_1q)}")
    
    print("\n[2/3] Comparaison...")
    comparisons = compare_results(multi_llm, desc_1q)
    stats = compute_stats(comparisons)
    
    print("\n[3/3] Export...")
    export_results(comparisons, stats, Path(OUTPUT_DIR))
    
    print("\n" + "=" * 80)
    print("RÉSUMÉ")
    print("=" * 80)
    print(f"  Phrases : {stats['total']}")
    print(f"  Accord : {stats['agree_count']}/{stats['total']} ({stats['agree_%']}%)")
    print(f"  Accord Descriptif : {stats['type_counts'].get('Accord_Descriptif', 0)}")
    print(f"  Accord Non-Descriptif : {stats['type_counts'].get('Accord_Non-Descriptif', 0)}")
    print(f"  Divergences totales : {len(comparisons) - stats['agree_count']}")


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        import traceback
        print(f"\nErreur : {e}")
        traceback.print_exc()
