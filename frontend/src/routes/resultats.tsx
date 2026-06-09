import { createFileRoute } from "@tanstack/react-router";
import { PageHeader, ModePill } from "@/components/app-shell";
import { CategoryBadge, categoryLabels } from "@/components/category-badge";
import { api, type ApiDocument, type ApiPhrase, type Category } from "@/lib/api";
import { Download, Search, FileJson, Sheet, Gauge, Clock, Euro, Loader2, AlertCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

type Search = { documentId?: string };

export const Route = createFileRoute("/resultats")({
  head: () => ({ meta: [{ title: "Résultats métier — BVC" }] }),
  validateSearch: (s: Record<string, unknown>): Search => ({
    documentId: typeof s.documentId === "string" ? s.documentId : undefined,
  }),
  component: ResultsView,
});

const CATS: Category[] = ["ROI", "Notoriete", "Obligation", "Description"];

function ResultsView() {
  const { documentId } = Route.useSearch();
  const navigate = Route.useNavigate();

  const docsQ = useQuery({ queryKey: ["documents"], queryFn: api.documents });
  const docs: ApiDocument[] = docsQ.data?.documents ?? [];

  // Choose effective doc id: URL > first available
  const [selected, setSelected] = useState<string | undefined>(documentId);
  useEffect(() => {
    if (documentId) setSelected(documentId);
    else if (!selected && docs.length > 0) setSelected(docs[0].id);
  }, [documentId, docs, selected]);

  const effectiveId = selected ?? docs[0]?.id;

  const resultsQ = useQuery({
    queryKey: ["results", effectiveId],
    queryFn: () => api.results(effectiveId!),
    enabled: !!effectiveId,
  });

  const document = resultsQ.data?.document ?? null;
  const phrases: ApiPhrase[] = resultsQ.data?.phrases ?? [];

  const [active, setActive] = useState<Set<Category>>(new Set(CATS));
  const [q, setQ] = useState("");

  const filtered = useMemo(
    () =>
      phrases.filter(
        (p) =>
          active.has(p.categorie) &&
          (q === "" ||
            p.phrase.toLowerCase().includes(q.toLowerCase()) ||
            p.document.toLowerCase().includes(q.toLowerCase())),
      ),
    [phrases, active, q],
  );

  const toggle = (c: Category) => {
    const next = new Set(active);
    next.has(c) ? next.delete(c) : next.add(c);
    if (next.size === 0) next.add(c);
    setActive(next);
  };

  const counts = CATS.reduce((acc, c) => {
    acc[c] = phrases.filter((p) => p.categorie === c).length;
    return acc;
  }, {} as Record<Category, number>);

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

  const exportJSON = () => {
    const payload = filtered.map((p) => ({
      id: p.id,
      phrase: p.phrase,
      document: p.document,
      categorie: p.categorie,
      confidence: p.confidence,
      mode: p.modeUsed,
      scores: p.scores,
      responses: p.responses,
    }));
    downloadBlob(JSON.stringify(payload, null, 2), `bvc-resultats-${Date.now()}.json`, "application/json");
  };

  const exportCSV = () => {
    const escape = (v: string | number) => `"${String(v).replace(/"/g, '""')}"`;
    const header = ["id", "phrase", "document", "categorie", "confidence", "mode"];
    const rows = filtered.map((p) =>
      [p.id, p.phrase, p.document, p.categorie, p.confidence, p.modeUsed].map(escape).join(";"),
    );
    const csv = "\uFEFF" + [header.join(";"), ...rows].join("\n");
    downloadBlob(csv, `bvc-resultats-${Date.now()}.csv`, "text/csv;charset=utf-8;");
  };

  const onSelectDoc = (id: string) => {
    setSelected(id);
    navigate({ search: { documentId: id }, replace: true });
  };

  const costStr = document ? `${document.costEur.toFixed(2)} € sur ce document` : "—";
  const durationStr = document ? `≈ ${Math.round(document.durationS)} s` : "—";

  return (
    <>
      <PageHeader
        title="Résultats métier"
        description="Phrases classées et exploitables, avec score de confiance et coût réel."
        actions={
          <>
            {docs.length > 0 && (
              <select
                value={effectiveId ?? ""}
                onChange={(e) => onSelectDoc(e.target.value)}
                className="rounded-md border border-border bg-card px-3 py-1.5 text-[12px] focus:outline-none focus:ring-2 focus:ring-ring/40 max-w-[260px] truncate"
              >
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name} · {d.client}
                  </option>
                ))}
              </select>
            )}
            <button
              onClick={exportCSV}
              disabled={!filtered.length}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12px] font-medium hover:bg-secondary disabled:opacity-40"
            >
              <Sheet className="h-3.5 w-3.5" /> Export Excel (.csv)
            </button>
            <button
              onClick={exportJSON}
              disabled={!filtered.length}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-[12px] font-medium hover:bg-secondary disabled:opacity-40"
            >
              <FileJson className="h-3.5 w-3.5" /> Export JSON
            </button>
          </>
        }
      />

      <div className="p-6 lg:p-8 space-y-5">
        {(docsQ.error || resultsQ.error) && (
          <ApiError
            error={(docsQ.error as Error) || (resultsQ.error as Error)}
            onRetry={() => {
              docsQ.refetch();
              resultsQ.refetch();
            }}
          />
        )}

        {(docsQ.isLoading || resultsQ.isLoading) && (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement…
          </div>
        )}

        {/* Document header */}
        {document && (
          <div className="rounded-lg border border-border bg-card p-4 flex flex-wrap items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Document</div>
              <div className="text-[15px] font-semibold tracking-tight truncate">{document.name}</div>
              <div className="text-[12px] text-muted-foreground mt-0.5">
                {document.client} · {document.phrases} phrases · {document.pages} pages · <ModePill mode={document.mode} />
              </div>
            </div>
            <div className="text-[12px] text-muted-foreground">
              Dominante : <CategoryBadge category={document.dominant} size="sm" />
            </div>
          </div>
        )}

        {/* Estimations */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <EstimateCard icon={Euro} label="Coût réel" value={document ? `${document.costEur.toFixed(2)} €` : "—"} detail={costStr} tone="amber" />
          <EstimateCard
            icon={Gauge}
            label="Précision"
            value={document?.mode === "expert" ? "Élevée" : document?.mode === "rapide" ? "Correcte" : "—"}
            detail={document ? `Mode ${document.mode === "expert" ? "Expert" : "Rapide"}` : "—"}
            tone="green"
          />
          <EstimateCard icon={Clock} label="Temps d'analyse" value={durationStr} detail="Traitement métier complet" tone="slate" />
        </div>

        {/* Filters */}
        <div className="rounded-lg border border-border bg-card p-4 flex flex-col lg:flex-row lg:items-center gap-3 lg:gap-4">
          <div className="flex items-center gap-1.5 flex-wrap">
            {CATS.map((c) => {
              const on = active.has(c);
              return (
                <button
                  key={c}
                  onClick={() => toggle(c)}
                  className={`transition-opacity ${on ? "opacity-100" : "opacity-40 hover:opacity-70"}`}
                >
                  <CategoryBadge category={c} />
                  <span className="ml-1 text-[10px] text-muted-foreground font-mono">{counts[c]}</span>
                </button>
              );
            })}
          </div>
          <div className="flex-1" />
          <div className="relative w-full lg:w-72">
            <Search className="h-3.5 w-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Rechercher une phrase, un document…"
              className="w-full rounded-md border border-border bg-background pl-8 pr-3 py-1.5 text-[13px] focus:outline-none focus:ring-2 focus:ring-ring/40"
            />
          </div>
        </div>

        {/* Table */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-secondary/50 text-muted-foreground text-left">
                <tr>
                  <th className="px-5 py-2.5 font-medium w-[48%]">Phrase</th>
                  <th className="px-3 py-2.5 font-medium">Catégorie</th>
                  <th className="px-3 py-2.5 font-medium">Confiance</th>
                  <th className="px-3 py-2.5 font-medium">Document</th>
                  <th className="px-5 py-2.5 font-medium text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {filtered.map((p) => (
                  <tr key={p.id} className="hover:bg-secondary/30 align-top">
                    <td className="px-5 py-3 text-foreground leading-relaxed">{p.phrase}</td>
                    <td className="px-3 py-3"><CategoryBadge category={p.categorie} size="sm" /></td>
                    <td className="px-3 py-3 w-40">
                      <ConfidenceBar value={p.confidence} category={p.categorie} />
                    </td>
                    <td className="px-3 py-3 text-muted-foreground text-[12px]">{p.document}</td>
                    <td className="px-5 py-3 text-right">
                      <button
                        onClick={() => {
                          const payload = {
                            id: p.id,
                            phrase: p.phrase,
                            document: p.document,
                            categorie: p.categorie,
                            confidence: p.confidence,
                            mode: p.modeUsed,
                            scores: p.scores,
                            responses: p.responses,
                          };
                          downloadBlob(
                            JSON.stringify(payload, null, 2),
                            `phrase-${p.id}.json`,
                            "application/json",
                          );
                        }}
                        className="text-muted-foreground hover:text-foreground"
                        title="Exporter cette phrase (JSON)"
                      >
                        <Download className="h-3.5 w-3.5 inline" />
                      </button>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && !resultsQ.isLoading && (
                  <tr>
                    <td colSpan={5} className="px-5 py-10 text-center text-muted-foreground text-[13px]">
                      {phrases.length === 0
                        ? "Aucune phrase pour ce document — lancez une analyse depuis l'onglet « Analyse document »."
                        : "Aucune phrase ne correspond à vos filtres."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="px-5 py-2.5 border-t border-border text-[11px] text-muted-foreground flex items-center justify-between">
            <span>{filtered.length} phrase(s) affichée(s) sur {phrases.length}</span>
            <span>Catégories : {Array.from(active).map((c) => categoryLabels[c]).join(" · ")}</span>
          </div>
        </div>
      </div>
    </>
  );
}

function ApiError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return (
    <div className="rounded-lg border border-destructive/30 bg-destructive/5 text-destructive p-4 flex items-start gap-3">
      <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-semibold">Backend inaccessible</div>
        <div className="text-[12px] opacity-90 break-all">{error.message}</div>
      </div>
      <button
        onClick={onRetry}
        className="rounded-md border border-destructive/30 px-2.5 py-1 text-[12px] font-medium hover:bg-destructive/10"
      >
        Réessayer
      </button>
    </div>
  );
}

function ConfidenceBar({ value, category }: { value: number; category: Category }) {
  const color = {
    ROI: "var(--roi)",
    Notoriete: "var(--notoriete)",
    Obligation: "var(--obligation)",
    Description: "var(--description)",
  }[category];
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 bg-secondary rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span className="text-[11px] font-mono text-muted-foreground tabular-nums">
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function EstimateCard({
  icon: Icon, label, value, detail, tone,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string; value: string; detail: string;
  tone: "green" | "amber" | "slate";
}) {
  const toneCls = {
    green: "bg-roi-soft text-roi",
    amber: "bg-notoriete-soft text-notoriete",
    slate: "bg-description-soft text-muted-foreground",
  }[tone];
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex items-start gap-3">
      <div className={`h-9 w-9 rounded-md flex items-center justify-center ${toneCls}`}>
        <Icon className="h-4 w-4" />
      </div>
      <div>
        <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="text-[15px] font-semibold tracking-tight">{value}</div>
        <div className="text-[11px] text-muted-foreground">{detail}</div>
      </div>
    </div>
  );
}
