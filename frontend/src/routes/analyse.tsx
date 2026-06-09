import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { PageHeader, ModePill } from "@/components/app-shell";
import { CategoryBadge } from "@/components/category-badge";
import {
  Upload, FileText, Zap, Brain, Play, CheckCircle2, Loader2, X,
  FileSearch, ArrowRight, AlertCircle,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { api, type Category, type ApiDocument, type ApiPhrase, type Mode } from "@/lib/api";

export const Route = createFileRoute("/analyse")({
  head: () => ({ meta: [{ title: "Analyse document — BVC" }] }),
  component: AnalyseView,
});

type Step = { key: string; label: string; detail: string };
const STEPS: Step[] = [
  { key: "extract", label: "Lecture du PDF", detail: "Extraction du texte structuré du document" },
  { key: "clean", label: "Nettoyage du contenu", detail: "Suppression du bruit et normalisation" },
  { key: "split", label: "Découpage en paragraphes & phrases", detail: "Préparation des unités d'analyse" },
  { key: "classify", label: "Classification métier", detail: "Attribution des catégories ROI / Notoriété / Obligation / Description" },
  { key: "synth", label: "Synthèse et scoring", detail: "Catégorie finale + score de confiance" },
];

interface PickedFile {
  file: File;
  name: string;
  sizeKb: number;
}

function AnalyseView() {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [mode, setMode] = useState<Mode>("expert");
  const [client, setClient] = useState<string>("");
  const [picked, setPicked] = useState<PickedFile | null>(null);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ document: ApiDocument; phrases: ApiPhrase[] } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const onFileSelected = (f: File | undefined) => {
    if (!f) return;
    setError(null);
    setResult(null);
    setProgress(0);
    setPicked({ file: f, name: f.name, sizeKb: Math.max(1, Math.round(f.size / 1024)) });
  };

  const clearFile = () => {
    setPicked(null);
    setResult(null);
    setError(null);
    setProgress(0);
    if (inputRef.current) inputRef.current.value = "";
  };

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); };
  const handleDragLeave = (e: React.DragEvent) => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); };
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation(); setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped && (dropped.type === "application/pdf" || dropped.name.toLowerCase().endsWith(".pdf"))) {
      onFileSelected(dropped);
    }
  };

  const launch = async () => {
    if (!picked) return;
    setRunning(true);
    setError(null);
    setResult(null);
    setProgress(1);

    // Visual stepper while the (synchronous) backend call runs.
    const interval = window.setInterval(() => {
      setProgress((p) => (p < STEPS.length - 1 ? p + 1 : p));
    }, mode === "expert" ? 1800 : 900);

    try {
      const res = await api.analyze(picked.file, mode, client.trim() || undefined);
      window.clearInterval(interval);
      setProgress(STEPS.length);
      const trimmed = client.trim();
      const doc = trimmed ? { ...res.document, client: trimmed } : res.document;
      setResult({ document: doc, phrases: res.phrases });
    } catch (e) {
      window.clearInterval(interval);
      setProgress(0);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  const done = !!result;
  const doc = result?.document;
  const distribution = doc?.distribution as Record<Category, number> | undefined;
  const totalPhrases = doc?.phrases ?? 0;
  const avgConfidence = useMemo(() => {
    if (!result?.phrases?.length) return 0;
    const s = result.phrases.reduce((acc, p) => acc + (p.confidence || 0), 0);
    return s / result.phrases.length;
  }, [result]);

  return (
    <>
      <PageHeader
        title="Analyse d'un document"
        description="Téléversez un PDF commercial, choisissez le mode d'analyse et obtenez la classification métier de chaque phrase."
        modeBadge={mode}
      />
      <div className="p-6 lg:p-8 grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left: setup */}
        <div className="xl:col-span-2 space-y-6">
          {/* Upload */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-sm font-semibold tracking-tight mb-3">1 · Document source</h2>

            <div className="mb-4">
              <label htmlFor="client-name" className="block text-[11px] uppercase tracking-wider text-muted-foreground mb-1.5">
                Nom du client <span className="normal-case text-muted-foreground/70">(optionnel)</span>
              </label>
              <input
                id="client-name"
                type="text"
                value={client}
                onChange={(e) => setClient(e.target.value)}
                disabled={running}
                placeholder="Ex. Acme SA, Mairie de Lyon…"
                maxLength={120}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-ring/40 disabled:opacity-50"
              />
              <p className="text-[11px] text-muted-foreground mt-1">
                Sert à organiser et retrouver vos documents par client après traitement.
              </p>
            </div>


            {!picked ? (
              <div
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`rounded-md border border-dashed px-6 py-10 transition-colors ${
                  isDragging
                    ? "border-primary bg-primary/10 ring-1 ring-primary/30"
                    : "border-border bg-secondary/30 hover:bg-secondary/60"
                }`}
              >
                <label className="flex items-center justify-center gap-3 cursor-pointer">
                  <input
                    ref={inputRef}
                    type="file"
                    accept="application/pdf"
                    className="hidden"
                    onChange={(e) => onFileSelected(e.target.files?.[0])}
                  />
                  <div className="flex items-center gap-3 text-muted-foreground">
                    <Upload className={`h-5 w-5 ${isDragging ? "text-primary" : ""}`} />
                    <div className="text-[13px]">
                      <span className="text-foreground font-medium">Cliquez pour téléverser</span>{" "}
                      ou déposez un PDF ici
                      <div className="text-[11px] text-muted-foreground/80 mt-0.5">
                        PDF uniquement · transmis pour analyse métier
                      </div>
                    </div>
                  </div>
                </label>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="flex items-start justify-between gap-3 rounded-md border border-border bg-background px-4 py-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="h-9 w-9 rounded-md bg-primary/10 text-primary flex items-center justify-center shrink-0">
                      <FileText className="h-4 w-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-[13px] font-medium truncate">{picked.name}</div>
                      <div className="text-[11px] text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                        <span>{(picked.sizeKb / 1024).toFixed(2)} Mo</span>
                        {doc && (
                          <>
                            <span className="text-border">•</span>
                            <span>{doc.pages} pages</span>
                            <span className="text-border">•</span>
                            <span>{doc.phrases} phrases extraites</span>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={clearFile}
                    disabled={running}
                    className="inline-flex items-center gap-1.5 shrink-0 rounded-md border border-border bg-background hover:bg-secondary hover:text-foreground text-muted-foreground px-2.5 py-1.5 text-[12px] font-medium disabled:opacity-40 disabled:cursor-not-allowed"
                    aria-label="Retirer le PDF"
                    title="Retirer le PDF et réinitialiser"
                  >
                    <X className="h-3.5 w-3.5" />
                    Retirer le PDF
                  </button>
                </div>

                {result?.phrases && result.phrases.length > 0 && (
                  <div>
                    <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2 flex items-center gap-1.5">
                      <FileSearch className="h-3 w-3" />
                      Aperçu (premières phrases classées)
                    </div>
                    <div className="rounded-md border border-border bg-secondary/30 divide-y divide-border max-h-56 overflow-y-auto">
                      {result.phrases.slice(0, 6).map((p, i) => (
                        <div key={p.id} className="flex gap-3 px-3 py-2 text-[12px]">
                          <span className="text-muted-foreground font-mono shrink-0">#{i + 1}</span>
                          <span className="text-foreground/90 leading-relaxed flex-1">{p.phrase}</span>
                          <CategoryBadge category={p.categorie} size="sm" />
                        </div>
                      ))}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-1.5">
                      {result.phrases.length} phrases au total, 6 affichées.
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Mode */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-sm font-semibold tracking-tight mb-3">2 · Mode d'analyse</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <ModeOption
                active={mode === "rapide"}
                onClick={() => setMode("rapide")}
                icon={Zap}
                title="Mode Rapide"
                description="Classification phrase par phrase, sans contexte. Moins coûteux, plus rapide."
                stats={[
                  ["Analyse", "Phrase par phrase"],
                  ["Coût", "≈ faible"],
                  ["Précision", "Correcte"],
                ]}
              />
              <ModeOption
                active={mode === "expert"}
                onClick={() => setMode("expert")}
                icon={Brain}
                title="Mode Expert"
                description="Classification avec contexte paragraphe. Plus coûteux mais plus précis."
                stats={[
                  ["Analyse", "Avec contexte"],
                  ["Coût", "≈ plus élevé"],
                  ["Précision", "Élevée"],
                ]}
              />
            </div>
          </div>

          {/* Launch */}
          <div className="rounded-lg border border-border bg-card p-5">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold tracking-tight">3 · Lancer l'analyse</h2>
                <p className="text-[12px] text-muted-foreground">5 étapes : lecture, nettoyage, découpage, classification, synthèse.</p>
              </div>
              <button
                onClick={launch}
                disabled={!picked || running}
                className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-4 py-2 text-[13px] font-medium hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                {running ? "Analyse en cours…" : "Lancer l'analyse"}
              </button>
            </div>

            {error && (
              <div className="mt-4 rounded-md border border-destructive/30 bg-destructive/5 text-destructive p-3 flex items-start gap-2 text-[12px]">
                <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                <div className="break-all">{error}</div>
              </div>
            )}

            <div className="mt-5 space-y-2">
              {STEPS.map((s, idx) => {
                const status =
                  progress > idx ? "done" : progress === idx && running ? "active" : "pending";
                return (
                  <div
                    key={s.key}
                    className={`flex items-center gap-3 rounded-md border px-3 py-2.5 ${
                      status === "active"
                        ? "border-primary/40 bg-primary/5"
                        : status === "done"
                        ? "border-roi/30 bg-roi-soft/50"
                        : "border-border bg-background"
                    }`}
                  >
                    <div
                      className={`h-6 w-6 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0 ${
                        status === "done"
                          ? "bg-roi text-roi-foreground"
                          : status === "active"
                          ? "bg-primary text-primary-foreground"
                          : "bg-secondary text-muted-foreground"
                      }`}
                    >
                      {status === "done" ? (
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      ) : status === "active" ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        idx + 1
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-medium text-foreground">{s.label}</div>
                      <div className="text-[11px] text-muted-foreground">{s.detail}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Right: summary */}
        <div className="space-y-6">
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-sm font-semibold tracking-tight mb-3">Résumé de l'analyse</h2>

            {!picked && (
              <p className="text-[12px] text-muted-foreground">
                Sélectionnez un PDF puis lancez l'analyse pour obtenir la classification métier de chaque phrase.
              </p>
            )}

            {picked && !done && (
              <div className="space-y-3">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Document chargé
                  </div>
                  <div className="text-[13px] font-medium truncate">{picked.name}</div>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  {running
                    ? "Analyse métier en cours…"
                    : "Cliquez sur « Lancer l'analyse » pour démarrer le traitement du document."}
                </p>
              </div>
            )}

            {doc && done && distribution && (
              <div className="space-y-4">
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground">
                    Document
                  </div>
                  <div className="text-[13px] font-medium truncate">{doc.name}</div>
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <Stat label="Phrases" value={doc.phrases.toString()} />
                  <Stat label="Pages" value={doc.pages.toString()} />
                  <Stat label="Coût" value={`${doc.costEur.toFixed(2)} €`} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-center">
                  <Stat label="Durée" value={`${Math.round(doc.durationS)} s`} />
                  <Stat label="Confiance" value={`${Math.round(avgConfidence * 100)} %`} />
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
                    Catégorie dominante
                  </div>
                  <CategoryBadge category={doc.dominant} />
                </div>
                <div>
                  <div className="text-[11px] uppercase tracking-wider text-muted-foreground mb-2">
                    Répartition
                  </div>
                  <div className="space-y-1.5 text-[12px]">
                    {(Object.entries(distribution) as Array<[Category, number]>).map(([k, v]) => {
                      const pct = totalPhrases > 0 ? Math.round((v / totalPhrases) * 100) : 0;
                      return (
                        <div key={k} className="flex items-center justify-between gap-2">
                          <CategoryBadge category={k} size="sm" />
                          <span className="font-mono text-foreground text-[11px]">
                            {v} <span className="text-muted-foreground">· {pct}%</span>
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div className="flex flex-col gap-2">
                  <button
                    onClick={() => navigate({ to: "/resultats", search: { documentId: doc.id } })}
                    className="inline-flex items-center justify-center gap-1.5 w-full rounded-md bg-primary text-primary-foreground hover:bg-primary/90 px-3 py-2 text-[12px] font-medium"
                  >
                    Voir le détail des phrases <ArrowRight className="h-3 w-3" />
                  </button>
                  <Link
                    to="/synthese"
                    search={{ documentId: doc.id }}
                    className="inline-flex items-center justify-center gap-1.5 w-full rounded-md border border-border bg-secondary/40 hover:bg-secondary px-3 py-2 text-[12px] font-medium"
                  >
                    Ouvrir la synthèse métier
                  </Link>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-sm font-semibold tracking-tight mb-2">Déroulé de l'analyse</h2>
            <p className="text-[12px] text-muted-foreground mb-3">
              Lecture du PDF, nettoyage, découpage en phrases puis classification métier
              (ROI, Notoriété, Obligation, Description). Mode sélectionné :
            </p>
            <div className="flex items-center gap-1.5 text-[11px]">
              <ModePill mode={mode} />
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function ModeOption({
  active, onClick, icon: Icon, title, description, stats,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description: string;
  stats: [string, string][];
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`text-left rounded-md border p-4 transition-all ${
        active ? "border-primary bg-primary/5 ring-1 ring-primary/30" : "border-border hover:border-primary/40"
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <Icon className="h-4 w-4 text-primary" />
        <span className="text-[13px] font-semibold tracking-tight">{title}</span>
      </div>
      <p className="text-[12px] text-muted-foreground mb-3 leading-relaxed">{description}</p>
      <div className="grid grid-cols-3 gap-2">
        {stats.map(([k, v]) => (
          <div key={k} className="rounded bg-secondary/60 px-2 py-1.5">
            <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{k}</div>
            <div className="text-[12px] font-medium font-mono">{v}</div>
          </div>
        ))}
      </div>
    </button>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-secondary/60 px-2 py-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="text-[14px] font-semibold font-mono">{value}</div>
    </div>
  );
}
