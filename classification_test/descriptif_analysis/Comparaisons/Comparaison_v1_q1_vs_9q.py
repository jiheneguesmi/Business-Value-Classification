"""
compare_classifications.py
--------------------------
Compare deux approches de classification :
  - Script 1 : 9 questions (roi, notoriété, obligation) → catégorie par vote majoritaire
               + champ "categorie" (Description par défaut)
  - Script 2 : 1 question descriptif/non
               + champ "descriptif" (oui/non)

Génère 4 graphiques de comparaison directs depuis les JSON.
"""

import json
import os
import sys
from collections import Counter
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ─────────────────────────────────────────────
# 0. CHEMINS DES JSON (modifiables)
# ─────────────────────────────────────────────
JSON2 = (
    r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\Decoupage\AO_gagne_AOM-outilPDME-Rennes-Métropole_phrases_classification_descriptif_1question.json"
)
JSON1 = (
    r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\Decoupage\phrases\1km\AO_gagne_AOM-outilPDME-Rennes-Métropole\AO_gagne_AOM-outilPDME-Rennes-Métropole_phrases_classification.json"
)

OUTPUT_DIR = r"F:\Jihene\business_value_classification\Business-Value-Knowledge-Graph\classification_test\comparaison_approches\version_1"

# ─────────────────────────────────────────────
# 1. CHARGEMENT
# ─────────────────────────────────────────────
def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────
# 2. NORMALISATION → label binaire "descriptif" / "non descriptif"
# ─────────────────────────────────────────────
def normalize_v1(record):
    """
    Script 1 : 9 questions.
    Règle : si scores_roi=0 ET scores_notoriete=0 ET scores_obligation=0
            → "descriptif", sinon "non descriptif".
    (même logique que le fallback "Description" du script 1)
    """
    roi  = record.get("scores_roi", 0)
    not_ = record.get("scores_notoriete", 0)
    obl  = record.get("scores_obligation", 0)
    cat  = record.get("categorie", "").lower()

    # Si le champ categorie est déjà renseigné, on s'appuie dessus
    if cat in ("description", "descriptif"):
        return "descriptif"
    if cat and cat not in ("", "none"):
        return "non descriptif"

    # Sinon on recalcule depuis les scores
    if roi == 0 and not_ == 0 and obl == 0:
        return "descriptif"
    return "non descriptif"


def normalize_v2(record):
    """
    Script 2 : 1 question.
    Champ "descriptif" : "oui" → descriptif, "non" → non descriptif.
    """
    val = str(record.get("descriptif", "")).strip().lower()
    if val == "oui":
        return "descriptif"
    return "non descriptif"


# ─────────────────────────────────────────────
# 3. JOINTURE SUR LE TEXTE DE LA PHRASE
# ─────────────────────────────────────────────
def build_lookup(records, normalize_fn):
    """Retourne un dict {phrase_text: label_normalisé}"""
    d = {}
    for r in records:
        phrase = r.get("phrase", "").strip()
        if phrase:
            d[phrase] = normalize_fn(r)
    return d


def join_common(lookup1, lookup2):
    """Retourne liste de (phrase, label_v1, label_v2) pour les phrases communes."""
    common_phrases = set(lookup1.keys()) & set(lookup2.keys())
    rows = []
    for p in sorted(common_phrases):
        rows.append((p, lookup1[p], lookup2[p]))
    return rows


# ─────────────────────────────────────────────
# 4. CALCUL DES MÉTRIQUES
# ─────────────────────────────────────────────
def compute_metrics(rows):
    n = len(rows)
    if n == 0:
        return {}

    accord = sum(1 for _, l1, l2 in rows if l1 == l2)
    desaccord = n - accord

    # Distribution par label dans chaque version
    counter_v1 = Counter(l1 for _, l1, _ in rows)
    counter_v2 = Counter(l2 for _, _, l2 in rows)

    # Croisement (matrice de confusion 2×2)
    conf = {"desc-desc": 0, "desc-nondesc": 0, "nondesc-desc": 0, "nondesc-nondesc": 0}
    for _, l1, l2 in rows:
        key = f"{'desc' if l1=='descriptif' else 'nondesc'}-{'desc' if l2=='descriptif' else 'nondesc'}"
        conf[key] += 1

    return {
        "n": n,
        "accord": accord,
        "desaccord": desaccord,
        "taux_accord": accord / n * 100,
        "taux_desaccord": desaccord / n * 100,
        "v1_descriptif": counter_v1.get("descriptif", 0),
        "v1_non_descriptif": counter_v1.get("non descriptif", 0),
        "v2_descriptif": counter_v2.get("descriptif", 0),
        "v2_non_descriptif": counter_v2.get("non descriptif", 0),
        "conf": conf,
    }


# ─────────────────────────────────────────────
# 5. GRAPHIQUES
# ─────────────────────────────────────────────
COLORS = {
    "descriptif":     "#4C9BE8",   # bleu
    "non descriptif": "#F28B30",   # orange
    "accord":         "#2ECC71",   # vert
    "desaccord":      "#E74C3C",   # rouge
}

def save(fig, name, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, name)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✓  Sauvegardé : {path}")
    return path


def graph_accord_desaccord(m, out_dir):
    """Camembert accord / désaccord global."""
    fig, ax = plt.subplots(figsize=(6, 5))
    vals   = [m["accord"], m["desaccord"]]
    labels = [f"Accord\n{m['taux_accord']:.1f}%", f"Désaccord\n{m['taux_desaccord']:.1f}%"]
    colors = [COLORS["accord"], COLORS["desaccord"]]
    wedge_props = dict(width=0.6, edgecolor="white", linewidth=2)
    ax.pie(vals, labels=labels, colors=colors, autopct="%1.1f%%",
           startangle=90, wedgeprops=wedge_props, textprops={"fontsize": 12})
    ax.set_title(f"Accord global entre les 2 versions\n(n={m['n']} phrases communes)",
                 fontsize=13, fontweight="bold", pad=15)
    return save(fig, "01_accord_desaccord.png", out_dir)


def graph_distribution_bars(m, out_dir):
    """Barres groupées : distribution descriptif/non par version."""
    categories = ["Descriptif", "Non descriptif"]
    v1 = [m["v1_descriptif"], m["v1_non_descriptif"]]
    v2 = [m["v2_descriptif"], m["v2_non_descriptif"]]

    x    = np.arange(len(categories))
    w    = 0.35
    fig, ax = plt.subplots(figsize=(7, 5))
    b1 = ax.bar(x - w/2, v1, w, label="V1 (9 questions)", color=COLORS["descriptif"],   alpha=0.85, edgecolor="white")
    b2 = ax.bar(x + w/2, v2, w, label="V2 (1 question)",  color=COLORS["non descriptif"], alpha=0.85, edgecolor="white")

    def autolabel(bars):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2., h + 0.3,
                    f"{int(h)}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    autolabel(b1)
    autolabel(b2)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=12)
    ax.set_ylabel("Nombre de phrases", fontsize=11)
    ax.set_title("Distribution des labels par version\n(phrases communes)", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.set_ylim(0, max(max(v1), max(v2)) * 1.2 + 1)
    ax.spines[["top", "right"]].set_visible(False)
    return save(fig, "02_distribution_labels.png", out_dir)


def graph_distribution_pct(m, out_dir):
    """Barres empilées 100 % pour les deux versions."""
    n1 = m["v1_descriptif"] + m["v1_non_descriptif"]
    n2 = m["v2_descriptif"] + m["v2_non_descriptif"]

    pct_desc   = [m["v1_descriptif"]/n1*100 if n1 else 0,
                  m["v2_descriptif"]/n2*100 if n2 else 0]
    pct_nondesc= [m["v1_non_descriptif"]/n1*100 if n1 else 0,
                  m["v2_non_descriptif"]/n2*100 if n2 else 0]

    fig, ax = plt.subplots(figsize=(6, 5))
    versions = ["V1\n(9 questions)", "V2\n(1 question)"]
    x = np.arange(len(versions))
    w = 0.5

    bars1 = ax.bar(x, pct_desc,    w, label="Descriptif",     color=COLORS["descriptif"],   alpha=0.85)
    bars2 = ax.bar(x, pct_nondesc, w, bottom=pct_desc,        label="Non descriptif", color=COLORS["non descriptif"], alpha=0.85)

    for bar, val in zip(bars1, pct_desc):
        if val > 3:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height()/2,
                    f"{val:.1f}%", ha="center", va="center", fontsize=10, color="white", fontweight="bold")
    for bar, bot, val in zip(bars2, pct_desc, pct_nondesc):
        if val > 3:
            ax.text(bar.get_x() + bar.get_width()/2, bot + val/2,
                    f"{val:.1f}%", ha="center", va="center", fontsize=10, color="white", fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(versions, fontsize=12)
    ax.set_ylabel("Pourcentage (%)", fontsize=11)
    ax.set_ylim(0, 110)
    ax.set_title("Répartition en % des labels par version", fontsize=13, fontweight="bold")
    ax.legend(fontsize=10, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    return save(fig, "03_distribution_pct.png", out_dir)


def graph_confusion(m, out_dir):
    """Heatmap de la matrice de confusion 2×2."""
    conf = m["conf"]
    matrix = np.array([
        [conf["desc-desc"],    conf["desc-nondesc"]],
        [conf["nondesc-desc"], conf["nondesc-nondesc"]]
    ])
    labels_ax = ["Descriptif", "Non descriptif"]

    fig, ax = plt.subplots(figsize=(6, 5))
    im = ax.imshow(matrix, cmap="Blues", aspect="auto")

    ax.set_xticks([0, 1])
    ax.set_yticks([0, 1])
    ax.set_xticklabels(labels_ax, fontsize=11)
    ax.set_yticklabels(labels_ax, fontsize=11)
    ax.set_xlabel("V2 (1 question)", fontsize=11, labelpad=8)
    ax.set_ylabel("V1 (9 questions)", fontsize=11, labelpad=8)
    ax.set_title("Matrice de confusion entre les 2 versions\n(phrases communes)",
                 fontsize=13, fontweight="bold", pad=12)

    vmax = matrix.max() if matrix.max() > 0 else 1
    for i in range(2):
        for j in range(2):
            val = matrix[i, j]
            color = "white" if val > vmax * 0.6 else "black"
            ax.text(j, i, str(val), ha="center", va="center", fontsize=14,
                    fontweight="bold", color=color)

    plt.colorbar(im, ax=ax, shrink=0.85)
    # Encadrer la diagonale en vert (accords)
    for k in range(2):
        rect = mpatches.FancyBboxPatch((k - 0.45, k - 0.45), 0.9, 0.9,
                                       boxstyle="round,pad=0.02",
                                       linewidth=2, edgecolor=COLORS["accord"],
                                       facecolor="none")
        ax.add_patch(rect)

    return save(fig, "04_matrice_confusion.png", out_dir)


# ─────────────────────────────────────────────
# 6. RAPPORT TEXTE
# ─────────────────────────────────────────────
def print_report(rows, m):
    n = m["n"]
    print("\n" + "="*60)
    print("  RAPPORT DE COMPARAISON DES DEUX APPROCHES")
    print("="*60)
    print(f"\n  Phrases communes trouvées     : {n}")
    print(f"  Accord (même label)           : {m['accord']}  ({m['taux_accord']:.1f}%)")
    print(f"  Désaccord (labels différents) : {m['desaccord']}  ({m['taux_desaccord']:.1f}%)")

    print("\n  ─── Distribution V1 (9 questions) ───")
    print(f"    Descriptif     : {m['v1_descriptif']}  ({m['v1_descriptif']/n*100:.1f}%)")
    print(f"    Non descriptif : {m['v1_non_descriptif']}  ({m['v1_non_descriptif']/n*100:.1f}%)")

    print("\n  ─── Distribution V2 (1 question) ────")
    print(f"    Descriptif     : {m['v2_descriptif']}  ({m['v2_descriptif']/n*100:.1f}%)")
    print(f"    Non descriptif : {m['v2_non_descriptif']}  ({m['v2_non_descriptif']/n*100:.1f}%)")

    print("\n  ─── Matrice de confusion ─────────────")
    c = m["conf"]
    print(f"    V1=desc  ∩ V2=desc      : {c['desc-desc']}")
    print(f"    V1=desc  ∩ V2=non-desc  : {c['desc-nondesc']}")
    print(f"    V1=non   ∩ V2=desc      : {c['nondesc-desc']}")
    print(f"    V1=non   ∩ V2=non-desc  : {c['nondesc-nondesc']}")

    if m["desaccord"] > 0:
        print("\n  ─── Phrases en désaccord ─────────────")
        for phrase, l1, l2 in rows:
            if l1 != l2:
                short = phrase[:70] + "…" if len(phrase) > 70 else phrase
                print(f"    [{l1:>16} | {l2:<16}]  {short}")
    print("="*60 + "\n")


# ─────────────────────────────────────────────
# 7. MAIN
# ─────────────────────────────────────────────
def main():
    # --- Chargement ---
    print(f"\nChargement JSON1 : {JSON1}")
    data1 = load_json(JSON1)
    print(f"  → {len(data1)} enregistrements")

    print(f"Chargement JSON2 : {JSON2}")
    data2 = load_json(JSON2)
    print(f"  → {len(data2)} enregistrements")

    # --- Normalisation & jointure ---
    lookup1 = build_lookup(data1, normalize_v1)
    lookup2 = build_lookup(data2, normalize_v2)
    rows    = join_common(lookup1, lookup2)
    print(f"\n  Phrases communes : {len(rows)}")

    if len(rows) == 0:
        print("  ⚠  Aucune phrase commune ! Vérifiez les fichiers.")
        sys.exit(1)

    # --- Métriques ---
    m = compute_metrics(rows)
    print_report(rows, m)

    # --- Graphiques ---
    print("Génération des graphiques...")
    p1 = graph_accord_desaccord(m, OUTPUT_DIR)
    p2 = graph_distribution_bars(m, OUTPUT_DIR)
    p3 = graph_distribution_pct(m, OUTPUT_DIR)
    p4 = graph_confusion(m, OUTPUT_DIR)

    print(f"\n   4 graphiques sauvegardés dans : {OUTPUT_DIR}")
    return [p1, p2, p3, p4]


if __name__ == "__main__":
    main()