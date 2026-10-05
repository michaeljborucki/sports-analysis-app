import clsx from "clsx";

/**
 * Page title row shared by every page (spec §4). Title on the left, optional
 * inline controls (segmented mode switch, sport switcher) beside it, meta
 * (freshness) and actions on the right. `children` renders below the row —
 * filter bars, sentence filters, tabs.
 */
export function PageHeader({
  title,
  description,
  inline,
  meta,
  actions,
  children,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  inline?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={clsx("mb-5 flex flex-col gap-4", className)}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="min-w-0">
          <h1 className="text-[length:var(--fs-22)] leading-[var(--lh-22)] font-bold tracking-[-0.02em] text-text-1">
            {title}
          </h1>
          {description && (
            <p className="mt-0.5 text-[length:var(--fs-13)] leading-[var(--lh-13)] text-text-3">
              {description}
            </p>
          )}
        </div>
        {inline}
        {(meta || actions) && (
          <div className="ml-auto flex items-center gap-3">
            {meta}
            {actions}
          </div>
        )}
      </div>
      {children}
    </header>
  );
}
