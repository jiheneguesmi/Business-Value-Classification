import { createFileRoute, Link } from "@tanstack/react-router";
import { PageHeader, ModePill } from "@/components/app-shell";
import { CategoryBadge } from "@/components/category-badge";
import { api, type Category, type DashboardPayload } from "@/lib/api";
import {
  FileText, Hash, Euro, Target, ArrowUpRight, Activity, Zap, Brain, Loader2, AlertCircle,
} from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Tableau de bord — Business Value Classifier" }] }),
  component: Dashboard,
});

const COLORS: Record<string, string> = {
  ROI: "var(--roi)",
  Notoriete: "var(--notoriete)",
  Obligation: "var(--obligation)",
  Description: "var(--description)",
};

const EMPTY_DIST: Record<Category, number> = { ROI: 0, Notoriete: 0, Obligation: 0, Description: 0 };

function Dashboard() {
  const [mode, setMode] = useState<"rapide" | "expert">("expert");

  const { data, isLoading, error, refetch, isFetching } = useQuery<DashboardPayload>({
    queryKey: ["dashboard"],
    queryFn: api.dashboard,
  });

  const distribution = data?.distribution ?? EMPTY_DIST;
  const stats = data?.corpusStats;
  const recent = data?.recentDocuments ?? [];

  const total = Object.values(distribution).reduce((a, b) => a + b, 0);
  const pieData = (Object.entries(distribution) as Array<[Category, number]>).map(([k, v]) => ({ name: k, value: v }));

  const kpis = [
    { label: "Documents analysés", value: stats?.documents ?? 0, icon: FileText, hint: `${stats?.clients ?? 0} clients` },
    { label: "Phrases classées", value: (stats?.phrases ?? 0).toLocaleString("fr-FR"), icon: Hash, hint: `${stats?.documents ?? 0} corpus` },
    { label: "Coût cumulé", value: `${(stats?.totalCostEur ?? 0).toFixed(2)} €`, icon: Euro, hint: "Multi-LLM" },
    { label: "Précision attendue", value: mode === "expert" ? "Élevée" : "Correcte", icon: Target, hint: mode === "expert" ? "Avec contexte" : "Sans contexte" },
  ];

  return (
    <>
      <PageHeader
        title="Tableau de bord"
        description="Vision d'ensemble du corpus analysé et performance du pipeline de classification."
        modeBadge={mode}
        actions={
          <Link
            to="/analyse"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary text-primary-foreground px-3 py-1.5 text-[13px] font-medium hover:bg-primary/90"
          >
            Nouvelle analyse <ArrowUpRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      <div className="p-6 lg:p-8 space-y-6">
        {error && <ApiError error={error as Error} onRetry={() => refetch()} />}
        {isLoading && (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Chargement du tableau de bord…
          </div>
        )}

        {/* KPIs */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {kpis.map((k) => {
            const Icon = k.icon;
            return (
              <div key={k.label} className="rounded-lg border border-border bg-card p-4 shadow-xs">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                      {k.label}
                    </div>
                    <div className="mt-1.5 text-2xl font-semibold tracking-tight text-foreground">
                      {k.value}
                    </div>
                    <div className="text-[11px] text-muted-foreground mt-0.5">{k.hint}</div>
                  </div>
                  <div className="h-8 w-8 rounded-md bg-secondary flex items-center justify-center">
                    <Icon className="h-4 w-4 text-primary" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Distribution */}
          <div className="lg:col-span-2 rounded-lg border border-border bg-card p-5">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold tracking-tight">Répartition des catégories business</h2>
                <p className="text-[12px] text-muted-foreground">
                  Sur l'ensemble du corpus ({total.toLocaleString("fr-FR")} phrases){isFetching ? " · maj…" : ""}
                </p>
              </div>
              <Activity className="h-4 w-4 text-muted-foreground" />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-center">
              <div className="h-56">
                {total === 0 ? (
                  <div className="h-full flex items-center justify-center text-[12px] text-muted-foreground">
                    Aucune donnée disponible.
                  </div>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={pieData} dataKey="value" innerRadius={55} outerRadius={88} paddingAngle={2} stroke="var(--card)" strokeWidth={2}>
                        {pieData.map((d) => (
                          <Cell key={d.name} fill={COLORS[d.name]} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{
                          background: "var(--popover)",
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          fontSize: 12,
                        }}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                )}
              </div>

              <div className="space-y-3">
                {(Object.keys(distribution) as Array<Category>).map((cat) => {
                  const v = distribution[cat] ?? 0;
                  const pct = total > 0 ? (v / total) * 100 : 0;
                  return (
                    <div key={cat}>
                      <div className="flex items-center justify-between text-[12px]">
                        <CategoryBadge category={cat} size="sm" />
                        <span className="font-mono text-foreground">
                          {v} <span className="text-muted-foreground">· {pct.toFixed(1)} %</span>
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 w-full rounded-full bg-secondary overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${pct}%`, background: COLORS[cat] }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Mode selector */}
          <div className="rounded-lg border border-border bg-card p-5">
            <h2 className="text-sm font-semibold tracking-tight">Mode d'analyse par défaut</h2>
            <p className="text-[12px] text-muted-foreground mb-4">
              Pour les prochaines analyses du corpus.
            </p>
            <div className="space-y-2.5">
              <ModeCard
                active={mode === "rapide"}
                onClick={() => setMode("rapide")}
                icon={Zap}
                title="Mode Rapide"
                subtitle="Phrase par phrase, sans contexte"
                meta="≈ 0,12 € · 2 min · précision correcte"
              />
              <ModeCard
                active={mode === "expert"}
                onClick={() => setMode("expert")}
                icon={Brain}
                title="Mode Expert"
                subtitle="Avec contexte paragraphe"
                meta="≈ 0,34 € · 4 min · précision élevée"
              />
            </div>
          </div>
        </div>

        {/* Recent documents */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-5 py-4 border-b border-border flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold tracking-tight">Derniers documents analysés</h2>
              <p className="text-[12px] text-muted-foreground">Historique récent du pipeline</p>
            </div>
            <Link to="/resultats" className="text-[12px] font-medium text-primary hover:underline">
              Voir tous les résultats →
            </Link>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead className="bg-secondary/50 text-muted-foreground">
                <tr className="text-left">
                  <th className="px-5 py-2.5 font-medium">Document</th>
                  <th className="px-3 py-2.5 font-medium">Client</th>
                  <th className="px-3 py-2.5 font-medium">Mode</th>
                  <th className="px-3 py-2.5 font-medium text-right">Phrases</th>
                  <th className="px-3 py-2.5 font-medium">Dominante</th>
                  <th className="px-3 py-2.5 font-medium text-right">Coût</th>
                  <th className="px-5 py-2.5 font-medium">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {recent.map((d) => (
                  <tr key={d.id} className="hover:bg-secondary/40">
                    <td className="px-5 py-2.5 font-medium text-foreground">
                      <Link
                        to="/resultats"
                        search={{ documentId: d.id }}
                        className="hover:underline"
                      >
                        {d.name}
                      </Link>
                    </td>
                    <td className="px-3 py-2.5 text-muted-foreground">{d.client}</td>
                    <td className="px-3 py-2.5"><ModePill mode={d.mode} /></td>
                    <td className="px-3 py-2.5 text-right font-mono">{d.phrases}</td>
                    <td className="px-3 py-2.5"><CategoryBadge category={d.dominant} size="sm" /></td>
                    <td className="px-3 py-2.5 text-right font-mono">{d.costEur.toFixed(2)} €</td>
                    <td className="px-5 py-2.5 text-muted-foreground">{d.date}</td>
                  </tr>
                ))}
                {recent.length === 0 && !isLoading && (
                  <tr>
                    <td colSpan={7} className="px-5 py-8 text-center text-[12px] text-muted-foreground">
                      Aucun document analysé pour le moment. Lancez une analyse depuis l'onglet
                      « Analyse document ».
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
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
        <div className="text-[11px] opacity-70 mt-1">
          Vérifie que <code className="font-mono">server.py</code> tourne (par défaut sur http://127.0.0.1:8000).
        </div>
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

function ModeCard({
  active, onClick, icon: Icon, title, subtitle, meta,
}: {
  active: boolean; onClick: () => void;
  icon: React.ComponentType<{ className?: string }>;
  title: string; subtitle: string; meta: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full text-left rounded-md border p-3 transition-all ${
        active
          ? "border-primary bg-primary/5 ring-1 ring-primary/30"
          : "border-border bg-background hover:border-primary/40"
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div className={`h-8 w-8 rounded-md flex items-center justify-center shrink-0 ${
          active ? "bg-primary text-primary-foreground" : "bg-secondary text-foreground"
        }`}>
          <Icon className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-[13px] font-semibold tracking-tight">{title}</div>
          <div className="text-[11px] text-muted-foreground">{subtitle}</div>
          <div className="text-[11px] text-muted-foreground mt-1 font-mono">{meta}</div>
        </div>
      </div>
    </button>
  );
}
