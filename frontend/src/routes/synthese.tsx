import { createFileRoute } from "@tanstack/react-router";
import { PageHeader, ModePill } from "@/components/app-shell";
import { CategoryBadge } from "@/components/category-badge";
import { api, type ApiDocument, type Category, type SummaryPayload } from "@/lib/api";
import { Sparkles, TrendingUp, AlertTriangle, Quote, Lightbulb, Loader2, AlertCircle, FileJson, Sheet } from "lucide-react";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Search = { documentId?: string };

export const Route = createFileRoute("/synthese")({
  head: () => ({ meta: [{ title: "Synthèse & recommandations — BVC" }] }),
  validateSearch: (s: Record<string, unknown>): Search => ({
    documentId: typeof s.documentId === "string" ? s.documentId : undefined,
  }),
  component: SyntheseView,
});

function SyntheseView() {
  const { documentId } = Route.useSearch();
  const navigate = Route.useNavigate();

  const docsQ = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const docs: ApiDocument[] = docsQ.data?.documents ?? [];

  const [selected, setSelected] = useState<string | undefined>(documentId);
  useEffect(() => {
    if (documentId) setSelected(documentId);
    else if (!selected && docs.length > 0) setSelected(docs[0].id);
  }, [documentId, docs, selected]);

  const effectiveId = selected ?? docs[0]?.id;

  const summaryQ = useQuery<SummaryPayload>({
    queryKey: ["summary", effectiveId],
    queryFn: () => api.summary(effectiveId!),
    enabled: !!effectiveId,
  });

  const data = summaryQ.data;
  const doc = data?.document ?? null;

  const onChange = (id: string) => {
    setSelected(id);
    navigate({ search: { documentId: id }, replace: true });
  };

  if ((docsQ.error || summaryQ.error)) {
    return (
      <>
        <PageHeader title="Synthèse & recommandations" />
        <div className="p-6 lg:p-8">
          <div className="rounded-lg border border-destructive/30 bg-destructive/5 text-destructive p-4 flex items-start gap-3">
            <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-semibold">Backend inaccessible</div>
              <div className="text-[12px] opacity-90 break-all">
                {((docsQ.error as Error) || (summaryQ.error as Error)).message}
              </div>
            </div>
          </div>
        </div>
      </>
    );
  }

  const downloadBlob = (content: string, filename: string, mime: string) => {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = window.document.createElement("a");
    a.href = url;
    a.download = filename;
    window.document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const exportSummaryJSON = () => {
    if (!data) return;
    downloadBlob(JSON.stringify(data, null, 2), `bvc-synthese-${effectiveId}-${Date.now()}.json`, "application/json");
  };

  const exportSummaryCSV = () => {
    if (!data || !doc) return;
    const escape = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const lines: string[] = [];
    // Document metadata
    lines.push(["Section", "Champ", "Valeur"].join(";"));
    lines.push(["Document", "Nom", doc.name].map(escape).join(";"));
    lines.push(["Document", "Client", doc.client].map(escape).join(";"));
    lines.push(["Document", "Mode", doc.mode].map(escape).join(";"));
    lines.push(["Document", "Phrases", doc.phrases].map(escape).join(";"));
    lines.push(["Document", "Pages", doc.pages].map(escape).join(";"));
    lines.push(["Document", "Coût (€)", doc.costEur.toFixed(2)].map(escape).join(";"));
    lines.push(["Résumé", "Dominante", `${data.dominant ?? '-'} (${(data.dominantPct ?? 0).toFixed(1)}%)`].map(escape).join(";"));
    lines.push(["Résumé", "Faible", `${data.weak ?? '-'} (${(data.weakPct ?? 0).toFixed(1)}%)`].map(escape).join(";"));
    // Key phrases
    lines.push("");
    lines.push(["Phrase", "Catégorie", "Confiance (%)"].join(";"));
    (data.keyPhrases ?? []).forEach((p) => {
      lines.push([p.phrase, p.categorie, (p.confidence * 100).toFixed(0)].map(escape).join(";"));
    });
    // Recommendations
    lines.push("");
    lines.push(["Recommandation"].join(";"));
    (data.recommendations ?? []).forEach((r) => {
      lines.push([r].map(escape).join(";"));
    });
    const csv = "\uFEFF" + lines.join("\n");
    downloadBlob(csv, `bvc-synthese-${effectiveId}-${Date.now()}.csv`, "text/csv;charset=utf-8;");
  };

  return (
    <>
      <PageHeader
        title="Synthèse & recommandations"
        description="Conclusion métier exploitable : points forts, zones faibles et axes d'amélioration pour orienter votre prochaine action commerciale."
        modeBadge={doc?.mode ?? null}
        actions={
          <div className="flex items-center gap-2">
            {docs.length > 0 ? (
              <select
                value={effectiveId ?? ""}
                onChange={(e) => onChange(e.target.value)}
                className="rounded-md border border-border bg-card px-3 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-ring/40 max-w-[300px] truncate"
              >
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>{d.name} · {d.client}</option>
                ))}
              </select>
            ) : null}
            <button
              onClick={exportSummaryCSV}
              disabled={!data || !doc}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12px] font-medium hover:bg-secondary disabled:opacity-40"
            >
              <Sheet className="h-3.5 w-3.5" /> Export Excel (.csv)
            </button>
            <button
              onClick={exportSummaryJSON}
              disabled={!data}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12px] font-medium hover:bg-secondary disabled:opacity-40"
            >
              <FileJson className="h-3.5 w-3.5" /> Export JSON
            </button>
          </div>
        }
      />

      <div className="p-6 lg:p-8">
        {(docsQ.isLoading || summaryQ.isLoading) && (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement de la synthèse…
          </div>
        )}

        {!doc && !docsQ.isLoading && (
          <div className="rounded-lg border border-border bg-card p-6 text-[13px] text-muted-foreground">
            Aucun document analysé. Lancez une analyse depuis l'onglet « Analyse document » pour
            générer une synthèse.
          </div>
        )}

        {doc && data && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Headline */}
            <div className="lg:col-span-3 rounded-lg border border-border bg-card p-6">
              <div className="flex flex-wrap items-start gap-6">
                <div className="flex-1 min-w-[260px]">
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Document analysé
                  </div>
                  <h2 className="text-xl font-semibold tracking-tight text-foreground mt-1">
                    {doc.name}
                  </h2>
                  <div className="text-[12px] text-muted-foreground mt-1">
                    {doc.client} · {doc.phrases} phrases · {doc.pages} pages · <ModePill mode={doc.mode} />
                  </div>
                </div>
                <div className="rounded-md bg-primary/5 border border-primary/20 p-4 max-w-md">
                  <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-primary font-semibold">
                    <Sparkles className="h-3.5 w-3.5" /> Verdict métier
                  </div>
                  <p className="mt-2 text-[14px] text-foreground leading-relaxed">
                    Document <CategoryBadge category={data.dominant ?? doc.dominant} size="sm" /> à{" "}
                    <span className="font-semibold">{(data.dominantPct ?? 0).toFixed(0)} %</span>.{" "}
                    {verdictSentence(data.dominant ?? doc.dominant, data.dominantPct ?? 0)}
                  </p>
                </div>
              </div>
            </div>

            {/* Strengths */}
            <Panel icon={TrendingUp} title="Points forts détectés" tone="green">
              <ul className="space-y-2.5">
                {buildStrengths(doc.distribution).map((s) => (
                  <li key={s.cat} className="flex items-start gap-2.5">
                    <CategoryBadge category={s.cat} size="sm" />
                    <span className="text-[13px] text-foreground leading-relaxed">{s.text}</span>
                  </li>
                ))}
              </ul>
            </Panel>

            {/* Weaknesses */}
            <Panel icon={AlertTriangle} title="Zones faibles" tone="amber">
              <ul className="space-y-2.5">
                {data.weak && (
                  <li className="text-[13px] text-foreground leading-relaxed">
                    Catégorie sous-représentée : <CategoryBadge category={data.weak} size="sm" /> (
                    {(data.weakPct ?? 0).toFixed(1)} %).
                  </li>
                )}
                <li className="text-[13px] text-muted-foreground leading-relaxed">
                  Envisager de renforcer l'argumentaire sur cette dimension dans la prochaine itération.
                </li>
              </ul>
            </Panel>

            {/* Recommendations */}
            <Panel icon={Lightbulb} title="Recommandations" tone="indigo">
              <ul className="space-y-2">
                {(data.recommendations ?? []).map((r, i) => (
                  <li key={i} className="flex items-start gap-2 text-[13px] leading-relaxed">
                    <span className="mt-1.5 h-1 w-1 rounded-full bg-primary shrink-0" />
                    <span className="text-foreground">{r}</span>
                  </li>
                ))}
                {(!data.recommendations || data.recommendations.length === 0) && (
                  <li className="text-[12px] text-muted-foreground">Aucune recommandation générée.</li>
                )}
              </ul>
            </Panel>

            {/* Key phrases */}
            <div className="lg:col-span-3 rounded-lg border border-border bg-card p-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold tracking-tight flex items-center gap-2">
                  <Quote className="h-4 w-4 text-muted-foreground" /> Phrases clés à réutiliser
                </h2>
                <span className="text-[11px] text-muted-foreground">
                  Sélection automatique · hors descriptions
                </span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                {(data.keyPhrases ?? []).map((p) => (
                  <div key={p.id} className="rounded-md border border-border bg-background p-4">
                    <CategoryBadge category={p.categorie} size="sm" />
                    <p className="mt-2 text-[13px] text-foreground leading-relaxed">« {p.phrase} »</p>
                    <div className="mt-2 text-[11px] text-muted-foreground font-mono">
                      Confiance {(p.confidence * 100).toFixed(0)} % · {p.document}
                    </div>
                  </div>
                ))}
                {(!data.keyPhrases || data.keyPhrases.length === 0) && (
                  <div className="text-[12px] text-muted-foreground">
                    Pas de phrase clé identifiée hors catégorie Description.
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

function Panel({
  icon: Icon, title, tone, children,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  tone: "green" | "amber" | "indigo";
  children: React.ReactNode;
}) {
  const headerCls = {
    green: "text-roi",
    amber: "text-notoriete",
    indigo: "text-primary",
  }[tone];
  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <h2 className={`text-sm font-semibold tracking-tight flex items-center gap-2 mb-3 ${headerCls}`}>
        <Icon className="h-4 w-4" /> {title}
      </h2>
      {children}
    </section>
  );
}

function verdictSentence(cat: Category, pct: number): string {
  if (cat === "ROI") return "Argumentaire fortement orienté gain financier et performance — adapté à un acheteur économique.";
  if (cat === "Notoriete") return "Forte mise en avant de l'image, du bien-être et de l'attractivité — adapté à une cible communication.";
  if (cat === "Obligation") return "Présence forte d'obligations réglementaires et de sécurité — adapté à un acheteur conformité.";
  return pct > 60
    ? "Argumentaire surtout descriptif — peu de valeur business directe identifiée."
    : "Équilibre entre description et arguments business.";
}

function buildStrengths(dist: Record<Category, number>) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  const out: { cat: Category; text: string }[] = [];
  const messages: Record<Exclude<Category, "Description">, (p: number) => string> = {
    ROI: (p) => `${p.toFixed(0)} % du contenu démontre un gain financier ou de performance.`,
    Notoriete: (p) => `${p.toFixed(0)} % des phrases valorisent l'image et l'expérience utilisateur.`,
    Obligation: (p) => `${p.toFixed(0)} % des arguments couvrent la conformité et la sécurité.`,
  };
  (["ROI", "Notoriete", "Obligation"] as const).forEach((c) => {
    const pct = (dist[c] / total) * 100;
    if (pct >= 20) out.push({ cat: c, text: messages[c](pct) });
  });
  if (out.length === 0) out.push({ cat: "Description", text: "Pas de catégorie business clairement dominante." });
  return out;
}
