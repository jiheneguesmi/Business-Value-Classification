import { cn } from "@/lib/utils";
import type { Category } from "@/lib/api";

const styles: Record<Category, string> = {
  ROI: "bg-roi-soft text-roi border-roi/30",
  Notoriete: "bg-notoriete-soft text-notoriete border-notoriete/40",
  Obligation: "bg-obligation-soft text-obligation border-obligation/30",
  Description: "bg-description-soft text-muted-foreground border-border",
};

const dot: Record<Category, string> = {
  ROI: "bg-roi",
  Notoriete: "bg-notoriete",
  Obligation: "bg-obligation",
  Description: "bg-description",
};

const labels: Record<Category, string> = {
  ROI: "ROI",
  Notoriete: "Notoriété",
  Obligation: "Obligation",
  Description: "Description",
};

export function CategoryBadge({
  category,
  className,
  size = "md",
}: {
  category: Category;
  className?: string;
  size?: "sm" | "md";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border font-medium tracking-tight",
        size === "sm" ? "px-1.5 py-0.5 text-[11px]" : "px-2 py-0.5 text-xs",
        styles[category],
        className,
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", dot[category])} />
      {labels[category]}
    </span>
  );
}

export const categoryLabels = labels;
export const categoryDot = dot;
