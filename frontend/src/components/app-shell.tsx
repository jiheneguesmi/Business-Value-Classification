import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import {
  LayoutDashboard,
  FileSearch,
  ListChecks,
  
  Sparkles,
  Gauge,
  Zap,
  Brain,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

const nav: Array<{ to: string; label: string; icon: typeof LayoutDashboard; end?: boolean }> = [
  { to: "/", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/analyse", label: "Analyse document", icon: FileSearch },
  { to: "/resultats", label: "Résultats métier", icon: ListChecks },
  
  { to: "/synthese", label: "Synthèse & reco.", icon: Sparkles },
];

export function AppShell() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <div className="min-h-screen flex w-full bg-background text-foreground">
      <aside className="hidden md:flex w-64 shrink-0 flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border">
        <div className="px-5 py-5 border-b border-sidebar-border">
          <div className="flex items-center gap-2.5">
            <div className="h-9 w-9 rounded-md bg-sidebar-primary/15 ring-1 ring-sidebar-primary/30 flex items-center justify-center">
              <Brain className="h-4.5 w-4.5 text-sidebar-primary" />
            </div>
            <div className="leading-tight">
              <div className="text-[13px] font-semibold tracking-tight">Business Value</div>
              <div className="text-[11px] text-sidebar-foreground/60">Classifier · v1.0</div>
            </div>
          </div>
        </div>

        <nav className="flex-1 px-2 py-4 space-y-0.5">
          {nav.map((item) => {
            const Icon = item.icon;
            const active = item.end ? pathname === item.to : pathname.startsWith(item.to);
            return (
              <Link
                key={item.to}
                to={item.to}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/75 hover:bg-sidebar-accent/60 hover:text-sidebar-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="px-3 py-4 border-t border-sidebar-border space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-sidebar-foreground/50 px-2">
            Pipeline IA
          </div>
          <div className="text-[11px] text-sidebar-foreground/70 px-2 leading-relaxed">
            5 modèles · 9 questions · vote majoritaire
          </div>
          <div className="flex items-center gap-2 px-2 pt-1">
            <Gauge className="h-3.5 w-3.5 text-sidebar-primary" />
            <span className="text-[11px] text-sidebar-foreground/70">Statut : opérationnel</span>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  modeBadge,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  modeBadge?: "rapide" | "expert" | null;
}) {
  return (
    <header className="border-b border-border bg-card/60 backdrop-blur sticky top-0 z-10">
      <div className="px-6 lg:px-8 py-4 flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="text-[19px] font-semibold tracking-tight text-foreground">{title}</h1>
            {modeBadge && <ModePill mode={modeBadge} />}
          </div>
          {description && (
            <p className="text-[13px] text-muted-foreground mt-1 max-w-3xl">{description}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </header>
  );
}

export function ModePill({ mode }: { mode: "rapide" | "expert" }) {
  if (mode === "rapide") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-sky-100 text-sky-700 border border-sky-200 px-2 py-0.5 text-[11px] font-medium">
        <Zap className="h-3 w-3" /> Mode Rapide
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-indigo-100 text-indigo-700 border border-indigo-200 px-2 py-0.5 text-[11px] font-medium">
      <Brain className="h-3 w-3" /> Mode Expert
    </span>
  );
}
